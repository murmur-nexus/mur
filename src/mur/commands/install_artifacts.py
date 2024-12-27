import importlib.util
import logging
import subprocess
import sys
import sysconfig
from pathlib import Path

import click

from ..utils.constants import MURMUR_EXTRAS_INDEX_URL, MURMUR_INDEX_URL, MURMURRC_PATH
from .base import ArtifactCommand

logger = logging.getLogger(__name__)


class InstallArtifactCommand(ArtifactCommand):
    """Handles artifact installation.

    This class manages the installation of Murmur artifacts (agents and tools) from
    a murmur.yaml configuration file.
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

    def _install_package(self, package_name: str, version: str, artifact_type: str) -> None:
        """Install a package using pip with configured index URLs.

        Args:
            package_name (str): Name of the package to install
            version (str): Version of the package to install ('latest' or specific version)
            artifact_type (str): Type of artifact ('agents' or 'tools')

        Raises:
            click.ClickException: If package installation fails
        """
        try:
            # Handle versions including 'latest' or empty
            # TODO: Add support for private namespace since it can conflict with public packages
            package_spec = package_name if version.lower() in ['latest', ''] else f'{package_name}=={version}'

            # Get index URLs from .murmurrc
            index_url, extra_index_urls = self._get_index_urls_from_murmurrc(MURMURRC_PATH)

            # Override index_url if it matches MURMUR_INDEX_URL
            if index_url == MURMUR_INDEX_URL:
                # Use private registry URL
                index_url = MURMUR_INDEX_URL

            # Override extra_index_urls if MURMUR_EXTRAS_INDEX_URL is set
            if MURMUR_EXTRAS_INDEX_URL:
                extra_index_urls = [
                    url.strip() for url in MURMUR_EXTRAS_INDEX_URL.split(',')
                ]  # Override index_url if it matches MURMUR_INDEX_URL

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

            # Add extra index URLs if any
            for url in extra_index_urls:
                command.extend(['--extra-index-url', url])

            if self.verbose:
                logger.info(f'Installing {package_spec}...')

            subprocess.check_call(command)  # nosec B603

            if self.verbose:
                logger.info(f'Successfully installed {package_spec}')

        except Exception as e:
            raise click.ClickException(f'Failed to install {package_name}: {e}')

    def _check_murmur_installed(self) -> None:
        """Check if the main murmur package is installed.

        Raises:
            click.ClickException: If murmur package is not installed
        """
        if importlib.util.find_spec('murmur') is None:
            raise click.ClickException(
                'The murmur package is not installed. Please install it before installing your agent or tool.'
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

        # Normalize package name to lowercase and replace hyphens with underscores
        package_name_pep8 = package_name.lower().replace('-', '_')

        import_line = f'from .{package_name_pep8}.main import {package_name_pep8}\n'

        # Create file if it doesn't exist
        if not init_path.exists():
            init_path.write_text(import_line)
            return

        # Check if import already exists
        current_content = init_path.read_text()
        if import_line not in current_content:
            with open(init_path, 'a') as f:
                f.write(import_line)

    def _install_artifact_group(self, artifacts: list[dict], artifact_type: str) -> None:
        """Install a group of artifacts of the same type.

        Installs multiple artifacts and their dependencies. For agents, also installs
        their associated tools.

        Args:
            artifacts (list[dict]): List of artifacts to install from yaml config
            artifact_type (str): Type of artifact ('agents' or 'tools')
        """
        for artifact in artifacts:
            self._install_package(artifact['name'], artifact['version'], artifact_type)
            # Update __init__.py file
            self._update_init_file(artifact['name'], artifact_type)

            # If this is an agent, also install its tools
            if artifact_type == 'agents' and (tools := artifact.get('tools', [])):
                self._install_artifact_group(tools, 'tools')

    def execute(self) -> None:
        """Execute the install command.

        Reads the murmur.yaml configuration file from the current directory and
        installs all specified agents and tools.

        Raises:
            click.ClickException: If installation fails
        """
        try:
            # Check for murmur package first
            self._check_murmur_installed()

            config = self._load_murmur_yaml_from_current_dir()

            # Install agents and their tools if any
            if agents := config.get('agents', []):
                self._install_artifact_group(agents, 'agents')

            # Install root-level tools if any
            if tools := config.get('tools', []):
                self._install_artifact_group(tools, 'tools')

            self.log_success('Successfully installed all artifacts')

        except Exception as e:
            self.handle_error(e, 'Failed to install artifacts')


def install_command() -> click.Command:
    """Create the install command for Click.

    Creates a Click command that handles the installation of Murmur artifacts
    from a murmur.yaml configuration file.

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
