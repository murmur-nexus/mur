import configparser
import importlib.metadata
import importlib.util
import logging
import subprocess
import sys
import sysconfig
from pathlib import Path
from typing import Optional

import click
import requests
from requests.exceptions import ConnectionError as RequestsConnectionError, RequestException, Timeout

from ..core.capsule_client import CapsuleClient
from ..utils.error_handler import MurError
from ..utils.loading import Spinner
from .base import ArtifactCommand

logger = logging.getLogger(__name__)

# Config section constants
PUBLIC_CONFIG_SECTION = 'murmur-nexus'
PRIVATE_CONFIG_SECTION = 'murmur-private'


class InstallArtifactCommand(ArtifactCommand):
    """Handles artifact installation.

    This class manages the installation of Murmur artifacts (agents and tools) from
    a murmur.yaml manifest file.
    """

    def __init__(self, verbose: bool = False, host: Optional[str] = None) -> None:
        """Initialize install command.

        Args:
            verbose: Whether to enable verbose output
            host: Optional host URL for using CapsuleClient instead of direct installation
        """
        super().__init__('install', verbose)
        self.host = host or self._get_host_from_config()
        self.capsule_client = CapsuleClient(base_url=self.host) if self.host else None

    def _get_host_from_config(self) -> Optional[str]:
        """Get host URL from configuration file.

        Returns:
            Optional[str]: Host URL if found in config, None otherwise
        """
        try:
            # Determine which config section to use based on registry type
            section = PRIVATE_CONFIG_SECTION if self.is_private_registry else PUBLIC_CONFIG_SECTION

            config = configparser.ConfigParser()
            config.read(self.murmurrc_path)

            # Only look in the appropriate section
            if section in config and 'host' in config[section]:
                return config[section]['host']

            return None
        except Exception as e:
            logger.debug(f'Failed to read host from config: {e}')
            return None

    def _get_murmur_artifacts_dir(self) -> Path:
        """Get the murmur artifacts directory path.

        Returns:
            Path: Path to site-artifacts/murmur/artifacts/
        """
        site_artifacts = Path(sysconfig.get_path('purelib')) / 'murmur' / 'artifacts'
        site_artifacts.mkdir(parents=True, exist_ok=True)
        return site_artifacts

    def _is_artifact_installed(self, artifact_name: str, version: str) -> bool:
        """Check if artifact is already installed with specified version.

        Args:
            artifact_name (str): Name of the artifact
            version (str): Version to check for, or 'latest'

        Returns:
            bool: True if artifact is installed with matching version
        """
        try:
            installed_version = importlib.metadata.version(artifact_name)
            if version.lower() == 'latest' or version == '':
                return True
            return installed_version == version
        except importlib.metadata.PackageNotFoundError:
            return False

    def _install_artifact(self, artifact_name: str, version: str) -> None:
        """Install a artifact using pip with configured index URLs or via capsule client."""
        try:
            artifact_spec = artifact_name if version.lower() in ['latest', ''] else f'{artifact_name}=={version}'

            # Skip installation check when using a host
            if self.host:
                self._install_via_capsule(artifact_name, artifact_spec)
            else:
                # Check if artifact is already installed locally
                if self._is_artifact_installed(artifact_name, version):
                    logger.info(f'Skipping {artifact_spec} - already installed')
                    return
                self._install_via_pip(artifact_name, artifact_spec)

        except MurError:
            raise
        except Exception as e:
            raise MurError(
                code=302,
                message=f'Failed to install {artifact_name}',
                detail='An unexpected error occurred during artifact installation.',
                original_error=e,
            )

    def _install_via_capsule(self, artifact_name: str, artifact_spec: str) -> None:
        """Install artifact using the capsule client.

        Args:
            artifact_name: Name of the artifact
            artifact_spec: Full artifact specification (may include version)
        """
        response = None
        index_url, _ = self._get_index_urls_from_murmurrc(self.murmurrc_path)
        artifact_url = f'{index_url}/{artifact_name}'

        if not self.verbose:
            with Spinner() as spinner:
                spinner.start(f'Installing {artifact_spec} via host {self.host}')
                try:
                    response = self._request_tool_installation(artifact_name, artifact_url)
                except Exception as e:
                    raise MurError(
                        code=608,
                        message=f'Failed to communicate with host for {artifact_name}',
                        detail='Error occurred while sending install request to the host.',
                        original_error=e,
                    )
        else:
            try:
                response = self._request_tool_installation(artifact_name, artifact_url)
            except Exception as e:
                raise MurError(
                    code=608,
                    message=f'Failed to communicate with host for {artifact_name}',
                    detail='Error occurred while sending install request to the host.',
                    original_error=e,
                )

        # Display results after installation
        if response:
            self._display_installation_results(response, artifact_spec)

    def _request_tool_installation(self, artifact_name: str, artifact_url: str):
        """Send installation request to the capsule client.

        Args:
            artifact_name: Name of the artifact to install
            artifact_url: URL for the artifact

        Returns:
            The response from the capsule client

        Raises:
            MurError: If the installation request fails
        """
        response = self.capsule_client.install_tool(tool_name=artifact_name, artifact_url=artifact_url)  # type: ignore

        # Check response status to determine success/failure
        if response.status_code >= 400:
            raise MurError(
                code=608,
                message=f'Failed to install {artifact_name} via host',
                detail=f'Host returned error: {response.status_code} - {response.error or "Unknown error"}',
            )

        return response

    def _display_installation_results(self, response, artifact_spec: str) -> None:
        """Display the results of a tool installation.

        Args:
            response: The response from the capsule client
            artifact_spec: The artifact specification string
        """
        if not response.raw_data:
            return

        status = response.raw_data.get('status', 'success')

        # Only display messages for non-success results
        if status.lower() != 'success':
            message = response.raw_data.get('message') or response.raw_data.get('result') or 'Installation had issues'
            click.echo(click.style(f'{artifact_spec}: {message}', fg='yellow'))

        if tools := response.raw_data.get('tools', []):
            if len(tools) == 1:
                # Single tool case
                click.echo(f'Added tool 🔧 {tools[0]}')
            else:
                # Multiple tools case
                click.echo(f'Added toolkit 🧰 with {len(tools)} tools:')
                for tool in tools:
                    click.echo(f'  🔧 {tool}')

        # Show tool installation any warnings
        if warnings := response.raw_data.get('warnings', []):
            click.echo(click.style('Warnings:', fg='yellow'))
            for warning in warnings:
                click.echo(click.style(f'  ! {warning}', fg='yellow'))

    def _install_via_pip(self, artifact_name: str, artifact_spec: str) -> None:
        """Install artifact using pip.

        Args:
            artifact_name: Name of the artifact
            artifact_spec: Full artifact specification (may include version)
        """
        index_url, extra_index_urls = self._get_index_urls_from_murmurrc(self.murmurrc_path)

        with Spinner() as spinner:
            if not self.verbose:
                spinner.start(f'Installing {artifact_spec}')

            self._handle_artifact_installation(artifact_spec, artifact_name, index_url, extra_index_urls)

    def _handle_artifact_installation(
        self, artifact_spec: str, artifact_name: str, index_url: str, extra_index_urls: list[str]
    ) -> None:
        """Handle the artifact installation process."""
        if '.murmur.nexus' in index_url:
            self._install_nexus_artifact(artifact_spec, artifact_name, index_url, extra_index_urls)
        else:
            self._private_artifact_command(artifact_spec, index_url)

    def _install_nexus_artifact(
        self, artifact_spec: str, artifact_name: str, index_url: str, extra_index_urls: list[str]
    ) -> None:
        """Install a artifact from Murmur Nexus repository."""
        try:
            self._main_artifact_command(artifact_spec, index_url)
        except subprocess.CalledProcessError as e:
            if 'Connection refused' in str(e) or 'Could not find a version' in str(e):
                raise MurError(
                    code=806,
                    message=f'Failed to connect to artifact registry for {artifact_name}',
                    detail='Could not establish connection to the artifact registry. Please check your network connection and registry URL.',
                    original_error=e,
                )
            raise MurError(
                code=307,
                message=f'Failed to install {artifact_name}',
                detail='The artifact installation process failed.',
                original_error=e,
            )

        self._process_artifact_metadata(artifact_name, index_url, extra_index_urls)

    def _process_artifact_metadata(self, artifact_name: str, index_url: str, extra_index_urls: list[str]) -> None:
        """Process artifact metadata and install dependencies."""
        try:
            normalized_artifact_name = artifact_name.replace('_', '-')
            logger.debug(f'Checking metadata for {artifact_name} from {index_url}')
            logger.debug(f'{index_url}/{normalized_artifact_name}/metadata')
            response = requests.get(f'{index_url}/{normalized_artifact_name}/metadata/', timeout=30)
            response.raise_for_status()
            artifact_info = response.json()

            logger.debug(f'Artifact info: {artifact_info}')

            if dependencies := artifact_info.get('requires_dist'):
                logger.debug(f'Dependencies: {dependencies}')
                for dep_spec in dependencies:
                    self._dependencies_artifact_command(dep_spec, index_url, extra_index_urls)

        except RequestsConnectionError as e:
            raise MurError(
                code=806,
                message=f'Failed to connect to artifact registry for {artifact_name}',
                detail='Could not establish connection to the artifact registry. Please check your network connection and registry URL.',
                original_error=e,
            )
        except Timeout as e:
            raise MurError(
                code=804,
                message=f'Connection timed out while fetching metadata for {artifact_name}',
                detail='The request to the artifact registry timed out. Please try again or check your network connection.',
                original_error=e,
            )
        except RequestException as e:
            raise MurError(
                code=803,
                message=f'Failed to fetch metadata for {artifact_name}',
                detail='Encountered an error while communicating with the artifact registry.',
                original_error=e,
            )

    def _main_artifact_command(self, artifact_spec: str, index_url: str) -> None:
        command = [
            sys.executable,
            '-m',
            'pip',
            'install',
            '--no-deps',
            '--disable-pip-version-check',
            artifact_spec,
            '--index-url',
            index_url,
        ]

        if not self.verbose:
            command.append('--quiet')

        subprocess.check_call(command)  # nosec B603

    def _dependencies_artifact_command(self, artifact_spec: str, index_url: str, extra_index_urls: list[str]) -> None:
        command = [
            sys.executable,
            '-m',
            'pip',
            'install',
            '--disable-pip-version-check',
            artifact_spec,
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

    def _private_artifact_command(self, artifact_spec: str, index_url: str) -> None:
        command = [
            sys.executable,
            '-m',
            'pip',
            'install',
            '--disable-pip-version-check',
            artifact_spec,
            '--index-url',
            index_url,
        ]

        if not self.verbose:
            command.append('--quiet')

        subprocess.check_call(command)  # nosec B603

    def _murmur_must_be_installed(self) -> None:
        """Check if the main murmur artifact is installed.

        Raises:
            MurError: If murmur artifact is not installed
        """
        if importlib.util.find_spec('murmur') is None:
            raise MurError(
                code=308,
                message='Murmur artifact is not installed',
                detail='Please install the murmur artifact before installing your agent or tool',
                debug_messages=["importlib.util.find_spec('murmur') returned None"],
            )

    def _update_init_file(self, artifact_name: str) -> None:
        """Update __init__.py file with import statement.

        Updates or creates the __init__.py file in the artifacts directory
        with an import statement for the installed artifact.

        Args:
            artifact_name (str): Name of the artifact to import
        """
        init_path = self._get_murmur_artifacts_dir() / '__init__.py'

        artifact_name_pep8 = artifact_name.lower().replace('-', '_')

        import_line = f'from .{artifact_name_pep8}.main import {artifact_name_pep8}'

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

    def _install_artifact_group(self, artifacts: list[dict]) -> None:
        """Install a group of artifacts.

        Args:
            artifacts (list[dict]): List of artifacts to install from yaml manifest
        """
        for artifact in artifacts:
            self._install_artifact(artifact['name'], artifact['version'])
            # Update __init__.py file
            self._update_init_file(artifact['name'])

            # Also install tools if this is an agent
            if tools := artifact.get('tools', []):
                self._install_artifact_group(tools)

    def _install_single_artifact(self, artifact_name: str) -> None:
        """Install a single artifact.

        Args:
            artifact_name: Name of the artifact to install
        """
        try:
            # If using host mode, verify host is available
            if self.host is None and '--host' in sys.argv:
                raise MurError(
                    code=609,
                    message='No host specified for artifact installation',
                    detail='The install command with --host flag requires a host to be specified via --host URL or found in configuration.',
                )

            # Install the artifact with latest version
            self._install_artifact(artifact_name, 'latest')
            self._update_init_file(artifact_name)

            self.log_success(f"Successfully installed artifact '{artifact_name}'")

        except Exception as e:
            self.handle_error(e, f"Failed to install '{artifact_name}'")

    def execute(self) -> None:
        """Execute the install command.

        Reads the murmur.yaml manifest file from the current directory and
        installs all specified agents and tools.
        """
        try:
            # If using host mode, verify host is available
            if self.host is None and '--host' in sys.argv:
                raise MurError(
                    code=609,
                    message='No host specified for artifact installation',
                    detail='The install command with --host flag requires a host to be specified via --host URL or found in configuration.',
                )

            # Check for murmur artifact first
            self._murmur_must_be_installed()

            manifest = self._load_murmur_yaml_from_current_dir()
            artifacts = []

            # Collect all artifacts from the manifest
            if agents := manifest.get('agents', []):
                artifacts.extend(agents)

            if tools := manifest.get('tools', []):
                artifacts.extend(tools)

            # Install all artifacts
            self._install_artifact_group(artifacts)

            self.log_success('Successfully installed all artifacts')

        except Exception as e:
            self.handle_error(e, 'Failed to install artifacts')


def install_command() -> click.Command:
    """Create the install command for Click."""

    @click.command()
    @click.argument('artifact_name', required=False)
    @click.option('--verbose', '-v', is_flag=True, help='Enable verbose output')
    @click.option(
        '--host', is_flag=False, flag_value='from_config', help='Host URL to use for installation via CapsuleClient'
    )
    def install(artifact_name: str | None, verbose: bool, host: str | None) -> None:
        """Install artifacts from murmur.yaml or a specific artifact.

        Usage patterns:
        - mur install                 # Install all artifacts from murmur.yaml
        - mur install my-artifact     # Install a specific artifact
        - mur install --host URL      # Install using remote host
        - mur install --host          # Install using host from config
        - mur install my-artifact --host URL  # Install specific artifact using remote host
        """
        # Only convert flag_value to None when it's the default flag_value
        # Otherwise, keep the specific host URL provided
        if host == 'from_config':
            host = None

        cmd = InstallArtifactCommand(verbose, host)
        cmd._murmur_must_be_installed()

        # Case 1: No arguments - install from manifest
        if not artifact_name:
            cmd.execute()
            return

        # Case 2: One argument - install specific artifact
        cmd._install_single_artifact(artifact_name)

    return install
