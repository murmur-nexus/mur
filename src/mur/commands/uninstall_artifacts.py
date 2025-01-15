import logging
import subprocess
import sys
from pathlib import Path

import click

logger = logging.getLogger(__name__)


class UninstallArtifactCommand:
    """Handles package uninstallation.

    Attributes:
        name (str): The name of the package to uninstall.
        verbose (bool): Whether to enable verbose logging output.
    """

    def __init__(self, name: str, verbose: bool = False) -> None:
        self.name = name
        self.verbose = verbose

    def _uninstall_package(self, package_name: str) -> None:
        """Uninstall a package using pip.

        Args:
            package_name (str): Name of the package to uninstall.

        """
        command = [sys.executable, '-m', 'pip', 'uninstall', '-y', package_name]

        if self.verbose:
            logger.info(f'Uninstalling {package_name}...')

        result = subprocess.run(command, capture_output=True, text=True)  # nosec B603

        if 'not installed' in result.stdout or 'not installed' in result.stderr:
            if self.verbose:
                logger.info(f'Package {package_name} is not installed')
            return

        if result.returncode != 0:
            raise MurError(
                code=309,
                message=f"Failed to uninstall {package_name}",
                original_error=result.stderr
            )

        if self.verbose:
            logger.info(f'Successfully uninstalled {package_name}')

    def _remove_from_init_file(self, package_name: str, artifact_type: str) -> None:
        """Remove package import from __init__.py if it exists.

        Args:
            package_name (str): Name of the package whose import should be removed.
            artifact_type (str): Type of artifact ('agents' or 'tools').
        """
        try:
            import importlib.util
            import murmur

            # Get the path to the namespace package
            spec = importlib.util.find_spec('murmur')
            if spec is None or not spec.submodule_search_locations:
                raise MurError(
                    code=211,
                    message="Could not locate murmur namespace",
                    type=MessageType.WARNING
                )

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
                    message=f"Could not find {artifact_type} __init__.py in murmur namespace locations",
                    type=MessageType.WARNING
                )

            if self.verbose:
                logger.info(f'Removing import from {init_path} for {artifact_type}')

            # Normalize package name to lowercase and replace hyphens with underscores
            package_name_pep8 = package_name.lower().replace('-', '_')
            package_prefix = f'from .{package_name_pep8}.'

            with open(init_path) as f:
                lines = f.readlines()

            with open(init_path, 'w') as f:
                # Keep lines that don't start with imports from this package
                f.writelines(line for line in lines if not line.strip().startswith(package_prefix))

        except Exception as e:
            raise MurError(
                code=200,
                message="Failed to clean up init files",
                type=MessageType.WARNING,
                original_error=e
            )

    def execute(self) -> None:
        """Execute the uninstall command.

        Raises:
            MurError: If the uninstallation process fails.
        """
        try:
            self._uninstall_package(self.name)
            self._remove_from_init_file(self.name, 'agents')
            self._remove_from_init_file(self.name, 'tools')
            click.echo(click.style(f'Successfully uninstalled {self.name}', fg='green'))
        except Exception as e:
            raise MurError(
                code=309,
                message=f"Failed to uninstall {self.name}",
                original_error=e
            )


def uninstall_command() -> click.Command:
    """Create the uninstall command.

    Returns:
        click.Command: A Click command for package uninstallation.
    """

    @click.command()
    @click.argument('name', required=True)
    @click.option('--verbose', '-v', is_flag=True, help='Enable verbose output')
    def uninstall(name: str, verbose: bool) -> None:
        """Uninstall a package.

        Args:
            name (str): Name of the package to uninstall.
            verbose (bool): Whether to enable verbose output.

        Raises:
            MurError: If the uninstallation process fails.
        """
        cmd = UninstallArtifactCommand(name, verbose)
        cmd.execute()

    return uninstall
