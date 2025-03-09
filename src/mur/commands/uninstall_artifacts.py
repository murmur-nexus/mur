import json
import logging
import subprocess
import sys
from pathlib import Path

import click

from mur.core.auth import AuthenticationManager
from mur.utils.error_handler import MessageType, MurError
from mur.commands.base import ArtifactCommand

logger = logging.getLogger(__name__)


class UninstallArtifactCommand(ArtifactCommand):
    """Handles artifact uninstallation.

    Attributes:
        name (str): The name of the artifact to uninstall.
        verbose (bool): Whether to enable verbose logging output.
        username (str | None): The current user's username for scoped artifacts.
    """

    def __init__(self, name: str | None, verbose: bool = False) -> None:
        """Initialize uninstall command.

        Args:
            name: Name of the artifact to uninstall, or None to uninstall from manifest
            verbose: Whether to enable verbose output
        """
        super().__init__('uninstall', verbose)
        self.name = name
        self.username = self.auth_manager.config.get('username')

    def _get_scoped_name(self, artifact_name: str) -> str:
        """Get the scoped artifact name if username exists.

        Args:
            artifact_name (str): Original artifact name

        Returns:
            str: Scoped artifact name if username exists, original name otherwise
        """
        if self.username:
            return f'{self.username}_{artifact_name}'
        return artifact_name

    def _remove_scope(self, artifact_name: str) -> str:
        """Remove username scope from artifact name if present.

        Args:
            artifact_name (str): artifact name that might include username scope

        Returns:
            str: artifact name with username scope removed if it was present
        """
        if not self.username:
            return artifact_name

        scope_prefix = f'{self.username}_'
        if artifact_name.startswith(scope_prefix):
            return artifact_name[len(scope_prefix) :]
        return artifact_name

    def _normalize_artifact_name(self, artifact_name: str) -> str:
        """Normalize artifact name to snake case.

        Args:
            artifact_name (str): artifact name to normalize

        Returns:
            str: Normalized artifact name in snake case
        """
        return artifact_name.lower().replace('-', '_').replace('.', '_')

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
        normalized_name = self._normalize_artifact_name(artifact_name)
        if self.verbose:
            logger.debug(f'Looking for normalized name: {normalized_name}')

        for pkg in artifacts:
            if self._normalize_artifact_name(pkg['name']) == normalized_name:
                return pkg['name']
        return None

    def _uninstall_artifact(self, artifact_name: str) -> None:
        """Uninstall a artifact using pip.

        Args:
            artifact_name: Name of the artifact to uninstall.

        Raises:
            MurError: If artifact check or uninstallation fails.
        """
        try:
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

    def _remove_from_init_file(self, artifact_name: str, artifact_type: str) -> None:
        """Remove artifact import from __init__.py if it exists.

        Args:
            artifact_name (str): Name of the artifact whose import should be removed.
            artifact_type (str): Type of artifact ('agents' or 'tools').
        """
        try:
            import importlib.util

            # Get the path to the namespace artifact
            spec = importlib.util.find_spec('murmur')
            if spec is None or not spec.submodule_search_locations:
                raise MurError(code=211, message='Could not locate murmur namespace', type=MessageType.WARNING)

            # Find first valid init file in namespace locations
            init_path = None
            for location in spec.submodule_search_locations:
                if self.verbose:
                    logger.info(f'Checking murmur namespace location for {artifact_type}: {location}')
                path = Path(location) / artifact_type / '__init__.py'
                if path.exists():
                    init_path = path
                    break

            if not init_path:
                raise MurError(
                    code=201,
                    message=f'Could not find {artifact_type} __init__.py in murmur namespace locations',
                    type=MessageType.WARNING,
                )

            if self.verbose:
                logger.info(f'Removing import from {init_path} for {artifact_type}')

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
            
            # Uninstall agents
            for agent in manifest.get('agents', []):
                try:
                    if self.verbose:
                        logger.debug(f'Uninstalling agent: {agent["name"]}')
                    self._uninstall_single_artifact(agent['name'])
                except Exception as e:
                    logger.warning(f'Failed to uninstall agent {agent["name"]}: {e}')

            # Uninstall tools
            for tool in manifest.get('tools', []):
                try:
                    if self.verbose:
                        logger.debug(f'Uninstalling tool: {tool["name"]}')
                    self._uninstall_single_artifact(tool['name'])
                except Exception as e:
                    logger.warning(f'Failed to uninstall tool {tool["name"]}: {e}')

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

            # If that didn't work and we have a username, try with the scope
            if self.username and not (
                artifact_name.startswith(f'{self.username}_')
                or artifact_name.startswith(f'{self.username}-')
                or artifact_name.startswith(f'{self.username}.')
            ):
                scoped_name = f'{self.username}-{artifact_name}'
                if self.verbose:
                    logger.debug(f'Attempting to uninstall with scope: {scoped_name}')
                self._uninstall_artifact(scoped_name)

            # Always remove any username prefix for init file cleanup
            unscoped_name = self._remove_scope(
                artifact_name.replace(f'{self.username}-', '')
                .replace(f'{self.username}.', '')
                .replace(f'{self.username}_', '')
            )

            if self.verbose:
                logger.debug(f'Cleaning up init files with unscoped name: {unscoped_name}')

            self._remove_from_init_file(unscoped_name, 'agents')
            self._remove_from_init_file(unscoped_name, 'tools')

        except Exception as e:
            raise MurError(code=309, message=f'Failed to uninstall {artifact_name}', original_error=e)

    def execute(self) -> None:
        """Execute the uninstall command.

        Raises:
            MurError: If the uninstallation process fails.
        """
        try:
            if self.name:
                # Single artifact uninstall
                self._uninstall_single_artifact(self.name)
                click.echo(click.style(f'Successfully uninstalled {self.name}', fg='green'))
            else:
                # Bulk uninstall from manifest
                self._uninstall_from_manifest()
        except Exception as e:
            raise MurError(code=309, message='Uninstallation failed', original_error=e)


def uninstall_command() -> click.Command:
    """Create the uninstall command.

    Returns:
        click.Command: A Click command for artifact uninstallation.
    """

    @click.command()
    @click.argument('name', required=False)
    @click.option('--verbose', '-v', is_flag=True, help='Enable verbose output')
    def uninstall(name: str | None, verbose: bool) -> None:
        """Uninstall a artifact or all artifacts from murmur.yaml.

        If name is provided, uninstalls that specific artifact.
        If no name is provided, attempts to uninstall all artifacts from murmur.yaml.

        Args:
            name: Optional name of the artifact to uninstall.
            verbose: Whether to enable verbose output.

        Raises:
            MurError: If the uninstallation process fails.
        """
        cmd = UninstallArtifactCommand(name, verbose)
        cmd.execute()

    return uninstall
