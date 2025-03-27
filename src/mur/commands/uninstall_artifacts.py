import importlib.util
import json
import logging
import subprocess
import sys
from pathlib import Path
from typing import Optional

import click

from mur.commands.base import ArtifactCommand
from mur.utils.error_handler import MessageType, MurError

from ..core.capsule_client import CapsuleClient
from ..core.packaging import normalize_artifact_name
from ..utils.loading import Spinner

logger = logging.getLogger(__name__)


class UninstallArtifactCommand(ArtifactCommand):
    """Handles artifact uninstallation.

    Attributes:
        name (str): The name of the artifact to uninstall.
        verbose (bool): Whether to enable verbose logging output.
    """

    def __init__(self, artifact_name: str | None, verbose: bool = False, host: Optional[str] = None) -> None:
        """Initialize uninstall command.

        Args:
            artifact_name: Name of the artifact to uninstall, or None to uninstall from manifest
            verbose: Whether to enable verbose output
            host: Optional host URL for using CapsuleClient instead of direct uninstallation
        """
        super().__init__('uninstall', verbose)
        self.artifact_name = artifact_name
        self.host = host
        self.capsule_client = CapsuleClient(base_url=host) if host else None

    def _get_installed_artifacts(self) -> list[dict[str, str]]:
        """Get list of installed artifacts from pip.

        Returns:
            list[dict[str, str]]: List of installed artifacts with their details

        Raises:
            MurError: If artifact check fails
        """
        check_command = [sys.executable, '-m', 'pip', 'list', '--format=json']
        try:
            result = subprocess.run(check_command, capture_output=True, text=True)  # nosec B603
            if result.returncode != 0:
                raise MurError(code=309, message='Failed to check artifact status', original_error=result.stderr)
            return json.loads(result.stdout)
        except json.JSONDecodeError as e:
            raise MurError(code=309, message='Failed to parse pip output', original_error=str(e))

    def _find_installed_artifact(self, artifact_name: str, artifacts: list[dict[str, str]]) -> str | None:
        """Find actual installed artifact name.

        Args:
            artifact_name: artifact name to search for
            artifacts: List of installed artifacts

        Returns:
            str | None: Actual installed artifact name if found, None otherwise
        """
        normalized_name = normalize_artifact_name(artifact_name)
        if self.verbose:
            logger.debug(f'Looking for normalized name: {normalized_name}')

        for pkg in artifacts:
            if normalize_artifact_name(pkg['name']) == normalized_name:
                return pkg['name']
        return None

    def _uninstall_artifact(self, artifact_name: str) -> None:
        """Uninstall a artifact using pip or capsule client.

        Args:
            artifact_name: Name of the artifact to uninstall.

        Raises:
            MurError: If artifact check or uninstallation fails.
        """
        try:
            # When using a host, use capsule client for uninstallation
            if self.host:
                self._uninstall_via_capsule(artifact_name)
                return

            artifacts = self._get_installed_artifacts()
            if self.verbose:
                logger.debug(f'Found installed artifacts: {[p["name"] for p in artifacts]}')

            artifact_to_uninstall = self._find_installed_artifact(artifact_name, artifacts)
            if not artifact_to_uninstall:
                if self.verbose:
                    logger.info(f'artifact {artifact_name} is not installed')
                return

            if self.verbose:
                logger.info(f'Uninstalling {artifact_to_uninstall}...')

            uninstall_command = [sys.executable, '-m', 'pip', 'uninstall', '-y', artifact_to_uninstall]
            result = subprocess.run(uninstall_command, capture_output=True, text=True)  # nosec B603

            if result.returncode != 0:
                raise MurError(
                    code=309, message=f'Failed to uninstall {artifact_to_uninstall}', original_error=result.stderr
                )

            if self.verbose:
                logger.info(f'Successfully uninstalled {artifact_to_uninstall}')

        except Exception as e:
            if not isinstance(e, MurError):
                raise MurError(code=309, message=f'Failed to process {artifact_name}', original_error=str(e))
            raise

    def _uninstall_via_capsule(self, artifact_name: str) -> None:
        """Uninstall artifact using the capsule client.

        Args:
            artifact_name: Name of the artifact to uninstall

        Raises:
            MurError: If uninstallation via capsule client fails
        """
        response = None

        with Spinner() as spinner:
            if not self.verbose:
                spinner.start(f'Uninstalling {artifact_name} via host {self.host}')

            try:
                response = self.capsule_client.uninstall_tool(tool_name=artifact_name)  # type: ignore

                if self.verbose:
                    logger.debug(f'Response status: {response.status_code}')
                    logger.debug(f'Response data: {response.raw_data}')
                    logger.debug(f'Response error: {response.error}')

                if response.status_code >= 400:
                    error_message = response.error or f'HTTP {response.status_code}'
                    raise MurError(
                        code=608,
                        message=f'Failed to uninstall {artifact_name} via host',
                        detail=f'Host returned error: {error_message}',
                    )

            except Exception as e:
                if self.verbose:
                    logger.error(f'Uninstall error: {e!s}')

                if not isinstance(e, MurError):
                    raise MurError(
                        code=608,
                        message=f'Failed to communicate with host for uninstalling {artifact_name}',
                        detail='Error occurred while sending uninstall request to the host.',
                        original_error=e,
                    )
                raise

        # Display results after spinner is stopped
        if response:
            self._display_uninstallation_results(response, artifact_name)

    def _display_uninstallation_results(self, response, artifact_name: str) -> None:
        """Display the results of a tool uninstallation.

        Args:
            response: The response from the capsule client
            artifact_name: The artifact name
        """
        # Access raw_data to display results
        if not response.raw_data:
            return  # Don't display anything for success case

        # Get status and only show non-success messages
        status = response.raw_data.get('status', 'success')

        # Only display messages for non-success results
        if status.lower() != 'success':
            message = response.raw_data.get('message') or response.raw_data.get('result') or 'Uninstallation had issues'
            click.echo(click.style(f'{artifact_name}: {message}', fg='yellow'))

        # Show any warnings
        if warnings := response.raw_data.get('warnings', []):
            click.echo(click.style('Warnings:', fg='yellow'))
            for warning in warnings:
                click.echo(click.style(f'  ! {warning}', fg='yellow'))

    def _remove_from_init_file(self, artifact_name: str) -> None:
        """Remove artifact import from artifacts/__init__.py if it exists.

        Args:
            artifact_name (str): Name of the artifact whose import should be removed.
        """
        try:
            # Get the path to the namespace artifact
            spec = importlib.util.find_spec('murmur')
            if spec is None or not spec.submodule_search_locations:
                raise MurError(code=211, message='Could not locate murmur namespace', type=MessageType.WARNING)

            # Find first valid init file in namespace locations
            init_path = None
            for location in spec.submodule_search_locations:
                if self.verbose:
                    logger.info(f'Checking murmur namespace location for artifacts: {location}')
                path = Path(location) / 'artifacts' / '__init__.py'
                if path.exists():
                    init_path = path
                    break

            if not init_path:
                raise MurError(
                    code=201,
                    message='Could not find artifacts/__init__.py in murmur namespace locations',
                    type=MessageType.WARNING,
                )

            if self.verbose:
                logger.info(f'Removing import from {init_path}')

            # Normalize artifact name to lowercase and replace hyphens with underscores
            artifact_name_pep8 = artifact_name.lower().replace('-', '_')
            artifact_prefix = f'from .{artifact_name_pep8}.'

            with open(init_path) as f:
                lines = f.readlines()

            with open(init_path, 'w') as f:
                # Keep lines that don't start with imports from this artifact
                f.writelines(line for line in lines if not line.strip().startswith(artifact_prefix))

        except Exception as e:
            raise MurError(
                code=200, message='Failed to clean up init files', type=MessageType.WARNING, original_error=e
            )

    def _uninstall_from_manifest(self) -> None:
        """Uninstall all artifacts specified in murmur.yaml."""
        try:
            manifest = self._load_murmur_yaml_from_current_dir()
            artifacts = []

            # Collect all artifacts from the manifest
            if agents := manifest.get('agents', []):
                artifacts.extend(agents)

            if tools := manifest.get('tools', []):
                artifacts.extend(tools)

            # Uninstall all artifacts
            for artifact in artifacts:
                try:
                    if self.verbose:
                        logger.debug(f'Uninstalling artifact: {artifact["name"]}')
                    self._uninstall_single_artifact(artifact['name'])
                except Exception as e:
                    logger.warning(f'Failed to uninstall artifact {artifact["name"]}: {e}')

            click.echo(click.style('Successfully uninstalled all artifacts from manifest', fg='green'))
        except Exception as e:
            raise MurError(code=309, message='Failed to uninstall artifacts from manifest', original_error=e)

    def _uninstall_single_artifact(self, artifact_name: str) -> None:
        """Handle uninstallation of a single artifact."""
        try:
            # First try with the name as provided
            if self.verbose:
                logger.debug(f'Attempting to uninstall artifact as provided: {artifact_name}')

            self._uninstall_artifact(artifact_name)
            self._remove_from_init_file(artifact_name)

            # Only show success message if uninstallation completed without errors
            self.log_success(f'Successfully uninstalled {artifact_name}')

        except MurError:
            # Re-raise MurErrors directly without wrapping them again
            raise
        except Exception as e:
            raise MurError(code=309, message=f'Failed to uninstall {artifact_name}', original_error=e)

    def execute(self) -> None:
        """Execute the uninstall command.

        Raises:
            MurError: If the uninstallation process fails.
        """
        try:
            if self.artifact_name:
                # Single artifact uninstall
                self._uninstall_single_artifact(self.artifact_name)
            else:
                # Bulk uninstall from manifest
                self._uninstall_from_manifest()
        except MurError:
            # Re-raise MurErrors directly without wrapping them again
            raise
        except Exception as e:
            raise MurError(code=309, message='Uninstallation failed', original_error=e)


def uninstall_command() -> click.Command:
    """Create the uninstall command.

    Returns:
        click.Command: A Click command for artifact uninstallation.
    """

    @click.command()
    @click.argument('artifact_name', required=False)
    @click.option('--verbose', '-v', is_flag=True, help='Enable verbose output')
    @click.option('--host', help='Host URL to use for uninstallation via CapsuleClient')
    def uninstall(artifact_name: str | None, verbose: bool, host: str | None) -> None:
        """Uninstall a artifact or all artifacts from murmur.yaml.

        If artifact_name is provided, uninstalls that specific artifact.
        If no artifact_name is provided, attempts to uninstall all artifacts from murmur.yaml.

        Usage patterns:
        - mur uninstall                # Uninstall all artifacts from murmur.yaml
        - mur uninstall my-artifact    # Uninstall a specific artifact
        - mur uninstall --host URL     # Uninstall using remote host
        - mur uninstall my-artifact --host URL  # Uninstall specific artifact using remote host

        Args:
            artifact_name: Optional name of the artifact to uninstall.
            verbose: Whether to enable verbose output.
            host: Optional host URL for using CapsuleClient instead of direct uninstallation.

        Raises:
            MurError: If the uninstallation process fails.
        """
        cmd = UninstallArtifactCommand(artifact_name, verbose, host)
        cmd.execute()

    return uninstall
