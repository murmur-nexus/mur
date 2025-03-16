import importlib.metadata
import importlib.util
import logging
import subprocess
import sys
import sysconfig
from pathlib import Path

import click
import requests
from requests.exceptions import ConnectionError as RequestsConnectionError, RequestException, Timeout

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

    def _is_package_installed(self, package_name: str, version: str) -> bool:
        """Check if package is already installed with specified version.

        Args:
            package_name (str): Name of the package
            version (str): Version to check for, or 'latest'

        Returns:
            bool: True if package is installed with matching version
        """
        try:
            installed_version = importlib.metadata.version(package_name)
            if version.lower() == 'latest' or version == '':
                return True
            return installed_version == version
        except importlib.metadata.PackageNotFoundError:
            return False

    def _install_artifact(self, package_name: str, version: str) -> None:
        """Install a package using pip with configured index URLs."""
        try:
            package_spec = package_name if version.lower() in ['latest', ''] else f'{package_name}=={version}'

            # Check if package is already installed
            if self._is_package_installed(package_name, version):
                logger.info(f'Skipping {package_spec} - already installed')
                return

            index_url, extra_index_urls = self._get_index_urls_from_murmurrc(self.murmurrc_path)

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
            normalized_artifact_name = package_name.replace('_', '-')
            logger.debug(f'Checking metadata for {package_name} from {index_url}')
            logger.debug(f'{index_url}/{normalized_artifact_name}/metadata')
            response = requests.get(f'{index_url}/{normalized_artifact_name}/metadata/', timeout=30)
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

    def _update_init_file(self, package_name: str, artifact_type: str) -> None:
        """Update __init__.py file with import statement.

        Updates or creates the __init__.py file in the appropriate murmur package directory
        with an import statement for the installed artifact.

        Args:
            package_name (str): Name of the package to import
            artifact_type (str): Type of artifact ('agents' or 'tools')
        """
        init_path = self._get_murmur_packages_dir(artifact_type) / '__init__.py'

        package_name_pep8 = package_name.lower().replace('-', '_')

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

        Args:
            artifacts (list[dict]): List of artifacts to install from yaml manifest
            artifact_type (str): Type of artifact ('agents' or 'tools')
        """
        for artifact in artifacts:
            self._install_artifact(artifact['name'], artifact['version'])
            # Update __init__.py file
            self._update_init_file(artifact['name'], artifact_type)

            # If this is an agent, also install its tools
            if artifact_type == 'agents' and (tools := artifact.get('tools', [])):
                self._install_artifact_group(tools, 'tools')

    def _install_single_artifact(
        self, artifact_name: str, artifact_type: str | None, fetch_metadata: bool = False
    ) -> None:
        """Install a single artifact.

        Args:
            artifact_name: Name of the artifact to install
            artifact_type: Type of the artifact ('agent' or 'tool'), or None to auto-detect
            fetch_metadata: Whether to fetch metadata to determine artifact type
        """
        try:
            # If artifact_type is not provided, try to fetch from metadata
            if fetch_metadata and not artifact_type:
                index_url, _ = self._get_index_urls_from_murmurrc(self.murmurrc_path)

                # Denormalize artifact name
                normalized_artifact_name = artifact_name.replace('_', '-')
                print(f'Denormalized artifact name: {normalized_artifact_name}')

                try:
                    response = requests.get(f'{index_url}/{normalized_artifact_name}/metadata/', timeout=30)
                    response.raise_for_status()
                    package_info = response.json()
                    artifact_type = package_info.get('artifact_type')

                    if not artifact_type:
                        raise MurError(
                            code=606,
                            message=f"Could not determine artifact type for '{normalized_artifact_name}'",
                            detail="The artifact metadata doesn't specify a type. Please use 'mur install [agent|tool] [artifact_name]' instead.",
                        )

                except RequestException as e:
                    raise MurError(
                        code=606,
                        message=f"Metadata not available for '{normalized_artifact_name}'",
                        detail="The artifact server doesn't support metadata or the artifact doesn't exist. Please use 'mur install [agent|tool] [artifact_name]' instead.",
                        original_error=e,
                    )

            if not artifact_type:
                raise MurError(
                    code=104,
                    message='Missing artifact type',
                    detail="Please specify the artifact type: 'mur install [agent|tool] [artifact_name]",
                )

            # Normalize artifact type (singular to plural)
            artifact_type_plural = f'{artifact_type}s'

            # Install the artifact with latest version
            self._install_artifact(artifact_name, 'latest')
            self._update_init_file(artifact_name, artifact_type_plural)

            self.log_success(f"Successfully installed {artifact_type} '{artifact_name}'")

        except Exception as e:
            self.handle_error(e, f"Failed to install '{artifact_name}'")

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
    """Create the install command for Click."""

    @click.command()
    @click.argument('arg1', required=False)
    @click.argument('arg2', required=False)
    @click.option('--verbose', '-v', is_flag=True, help='Enable verbose output')
    def install(arg1: str | None, arg2: str | None, verbose: bool) -> None:
        """Install artifacts from murmur.yaml or a specific artifact.

        Usage patterns:
        - mur install                      # Install all artifacts from murmur.yaml
        - mur install my-artifact          # Install artifact with auto-detected type
        - mur install agent my-agent       # Install agent with explicit type
        - mur install tool my-tool         # Install tool with explicit type
        """
        cmd = InstallArtifactCommand(verbose)
        cmd._murmur_must_be_installed()

        # Case 1: No arguments - install from manifest
        if not arg1:
            cmd.execute()
            return

        # Case 2: Two arguments - explicit artifact type and name
        if arg1 in ['agent', 'tool'] and arg2:
            print(f'Installing 2 args: {arg1} {arg2}')
            cmd._install_single_artifact(arg2, arg1, fetch_metadata=False)
            return

        # Case 3: One argument - artifact name only, try to detect type
        if arg1 and not arg2:
            print(f'Installing 1 arg:{arg1}')
            cmd._install_single_artifact(arg1, None, fetch_metadata=True)
            return

        # Case 4: Invalid usage
        raise MurError(
            code=101,
            message='Invalid command usage',
            detail='Usage: mur install [artifact_name] or mur install [agent|tool] [artifact_name]',
        )

    return install
