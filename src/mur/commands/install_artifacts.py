import importlib.util
import logging
import subprocess
import sys
import sysconfig
from pathlib import Path

import click
import requests
from requests.exceptions import ConnectionError as RequestsConnectionError, RequestException, Timeout

from ..core.auth import AuthenticationManager
from ..utils.constants import MURMUR_EXTRAS_INDEX_URL, MURMUR_INDEX_URL, MURMURRC_PATH
from ..utils.error_handler import MurError
from ..utils.loading import Spinner
from .base import ArtifactCommand

logger = logging.getLogger(__name__)


class InstallArtifactCommand(ArtifactCommand):
    """Handles artifact installation.

    This class manages the installation of Murmur artifacts (agents and tools) from
    a murmur.yaml manifest file.
    """

    def __init__(self, verbose: bool = False) -> None:
        """Initialize install command.

        Args:
            verbose: Whether to enable verbose output
        """
        super().__init__('install', verbose)

        # Add auth manager initialization
        self.auth_manager = AuthenticationManager.create(verbose=verbose)
        self.username = self.auth_manager.config.get('username')

    def _get_murmur_packages_dir(self, artifact_type: str) -> Path:
        """Get the murmur packages directory path.

        Args:
            artifact_type (str): Type of artifact (e.g., 'agents', 'tools')

        Returns:
            Path: Path to site-packages/murmur/<artifact_type>/
        """
        site_packages = Path(sysconfig.get_path('purelib')) / 'murmur' / artifact_type
        site_packages.mkdir(parents=True, exist_ok=True)
        return site_packages

    def _install_artifact(self, package_name: str, version: str, artifact_type: str) -> None:
        """Install a package using pip with configured index URLs."""
        try:
            package_spec = package_name if version.lower() in ['latest', ''] else f'{package_name}=={version}'
            index_url, extra_index_urls = self._get_index_urls_from_murmurrc(MURMURRC_PATH)

            if index_url == MURMUR_INDEX_URL:
                index_url = MURMUR_INDEX_URL

            if MURMUR_EXTRAS_INDEX_URL:
                extra_index_urls = [url.strip() for url in MURMUR_EXTRAS_INDEX_URL.split(',')]

            with Spinner() as spinner:
                if not self.verbose:
                    spinner.start(f'Installing {package_spec}')

                self._handle_package_installation(package_spec, package_name, index_url, extra_index_urls)

        except MurError:
            raise
        except Exception as e:
            raise MurError(
                code=300,
                message=f'Failed to install {package_name}',
                detail='An unexpected error occurred during package installation.',
                original_error=e,
            )

    def _handle_package_installation(
        self, package_spec: str, package_name: str, index_url: str, extra_index_urls: list[str]
    ) -> None:
        """Handle the package installation process."""
        if '.murmur.nexus' in index_url:
            self._install_nexus_package(package_spec, package_name, index_url, extra_index_urls)
        else:
            self._private_package_command(package_spec, index_url)

    def _install_nexus_package(
        self, package_spec: str, package_name: str, index_url: str, extra_index_urls: list[str]
    ) -> None:
        """Install a package from Murmur Nexus repository."""
        try:
            self._main_package_command(package_spec, index_url)
        except subprocess.CalledProcessError as e:
            if 'Connection refused' in str(e) or 'Could not find a version' in str(e):
                raise MurError(
                    code=806,
                    message=f'Failed to connect to package registry for {package_name}',
                    detail='Could not establish connection to the package registry. Please check your network connection and registry URL.',
                    original_error=e,
                )
            raise MurError(
                code=307,
                message=f'Failed to install {package_name}',
                detail='The package installation process failed.',
                original_error=e,
            )

        self._process_package_metadata(package_name, index_url, extra_index_urls)

    def _process_package_metadata(self, package_name: str, index_url: str, extra_index_urls: list[str]) -> None:
        """Process package metadata and install dependencies."""
        try:
            logger.debug(f'Checking metadata for {package_name} from {index_url}')
            logger.debug(f'{index_url}/{package_name}/metadata')
            response = requests.get(f'{index_url}/{package_name}/metadata/', timeout=30)
            response.raise_for_status()
            package_info = response.json()

            logger.debug(f'Package info: {package_info}')

            if dependencies := package_info.get('requires_dist'):
                logger.debug(f'Dependencies: {dependencies}')
                for dep_spec in dependencies:
                    self._dependencies_package_command(dep_spec, index_url, extra_index_urls)

        except RequestsConnectionError as e:
            raise MurError(
                code=806,
                message=f'Failed to connect to package registry for {package_name}',
                detail='Could not establish connection to the package registry. Please check your network connection and registry URL.',
                original_error=e,
            )
        except Timeout as e:
            raise MurError(
                code=804,
                message=f'Connection timed out while fetching metadata for {package_name}',
                detail='The request to the package registry timed out. Please try again or check your network connection.',
                original_error=e,
            )
        except RequestException as e:
            raise MurError(
                code=803,
                message=f'Failed to fetch metadata for {package_name}',
                detail='Encountered an error while communicating with the package registry.',
                original_error=e,
            )

    def _main_package_command(self, package_spec: str, index_url: str) -> None:
        command = [
            sys.executable,
            '-m',
            'pip',
            'install',
            '--no-deps',
            '--disable-pip-version-check',
            package_spec,
            '--index-url',
            index_url,
        ]

        if not self.verbose:
            command.append('--quiet')

        subprocess.check_call(command)  # nosec B603

    def _dependencies_package_command(self, package_spec: str, index_url: str, extra_index_urls: list[str]) -> None:
        command = [
            sys.executable,
            '-m',
            'pip',
            'install',
            '--disable-pip-version-check',
            package_spec,
            '--index-url',
            extra_index_urls[0],
            '--extra-index-url',
            index_url,
        ]

        if not self.verbose:
            command.append('--quiet')

        # Add additional extra index URLs only if exist
        if len(extra_index_urls[1:]) > 1:
            for url in extra_index_urls[1:]:
                command.extend(['--extra-index-url', url])

        subprocess.check_call(command)  # nosec B603

    def _private_package_command(self, package_spec: str, index_url: str) -> None:
        command = [
            sys.executable,
            '-m',
            'pip',
            'install',
            '--disable-pip-version-check',
            package_spec,
            '--index-url',
            index_url,
        ]

        if not self.verbose:
            command.append('--quiet')

        subprocess.check_call(command)  # nosec B603

    def _murmur_must_be_installed(self) -> None:
        """Check if the main murmur package is installed.

        Raises:
            MurError: If murmur package is not installed
        """
        if importlib.util.find_spec('murmur') is None:
            raise MurError(
                code=308,
                message='Murmur package is not installed',
                detail='Please install the murmur package before installing your agent or tool',
                debug_messages=["importlib.util.find_spec('murmur') returned None"],
            )

    def _remove_scope(self, package_name: str) -> str:
        """Remove username scope from package name if present.

        Args:
            package_name (str): Package name that might include username scope

        Returns:
            str: Package name with username scope removed if it was present
        """
        if not self.username:
            return package_name

        scope_prefix = f'{self.username}_'
        if package_name.startswith(scope_prefix):
            return package_name[len(scope_prefix) :]
        return package_name

    def _update_init_file(self, package_name: str, artifact_type: str) -> None:
        """Update __init__.py file with import statement.

        Updates or creates the __init__.py file in the appropriate murmur package directory
        with an import statement for the installed artifact.

        Args:
            package_name (str): Name of the package to import
            artifact_type (str): Type of artifact ('agents' or 'tools')
        """
        init_path = self._get_murmur_packages_dir(artifact_type) / '__init__.py'

        # Normalize package name to lowercase, replace hyphens with underscores,
        # and remove username scope if present
        package_name_pep8 = self._remove_scope(package_name.lower().replace('-', '_'))

        import_line = f'from .{package_name_pep8}.main import {package_name_pep8}'

        # Create file if it doesn't exist
        if not init_path.exists():
            init_path.write_text(import_line + '\n')
            return

        # Check if import already exists and ensure proper line endings
        current_content = init_path.read_text()
        if not current_content.endswith('\n'):
            current_content += '\n'

        if import_line not in current_content:
            with open(init_path, 'w') as f:
                f.write(current_content + import_line + '\n')

    def _install_artifact_group(self, artifacts: list[dict], artifact_type: str) -> None:
        """Install a group of artifacts of the same type.

        Installs multiple artifacts and their dependencies. For agents, also installs
        their associated tools.

        Args:
            artifacts (list[dict]): List of artifacts to install from yaml manifest
            artifact_type (str): Type of artifact ('agents' or 'tools')
        """
        for artifact in artifacts:
            self._install_artifact(artifact['name'], artifact['version'], artifact_type)
            # Update __init__.py file
            self._update_init_file(artifact['name'], artifact_type)

            # If this is an agent, also install its tools
            if artifact_type == 'agents' and (tools := artifact.get('tools', [])):
                self._install_artifact_group(tools, 'tools')

    def execute(self) -> None:
        """Execute the install command.

        Reads the murmur.yaml manifest file from the current directory and
        installs all specified agents and tools.
        """
        try:
            # Check for murmur package first
            self._murmur_must_be_installed()

            manifest = self._load_murmur_yaml_from_current_dir()

            # Install agents and their tools if any
            if agents := manifest.get('agents', []):
                self._install_artifact_group(agents, 'agents')

            # Install root-level tools if any
            if tools := manifest.get('tools', []):
                self._install_artifact_group(tools, 'tools')

            self.log_success('Successfully installed all artifacts')

        except Exception as e:
            self.handle_error(e, 'Failed to install artifacts')


def install_command() -> click.Command:
    """Create the install command for Click.

    Creates a Click command that handles the installation of Murmur artifacts
    from a murmur.yaml manifest file.

    Returns:
        click.Command: Click command for installing artifacts
    """

    @click.command()
    @click.option('--verbose', '-v', is_flag=True, help='Enable verbose output')
    def install(verbose: bool) -> None:
        """Install artifacts from murmur.yaml."""
        cmd = InstallArtifactCommand(verbose)
        cmd.execute()

    return install
