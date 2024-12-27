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

        Raises:
            click.ClickException: If package uninstallation fails.
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
            raise click.ClickException(f'Failed to uninstall {package_name}: {result.stderr}')

        if self.verbose:
            logger.info(f'Successfully uninstalled {package_name}')

    def _remove_from_init_file(self, package_name: str, artifact_type: str) -> None:
        """Remove package import from __init__.py if it exists.

        Args:
            package_name (str): Name of the package whose import should be removed.
            artifact_type (str): Type of artifact ('agents' or 'tools').

        Note:
            Silently continues if the package or init file cannot be found.
        """
        try:
            command = [sys.executable, '-m', 'pip', 'show', 'murmur']
            result = subprocess.run(command, capture_output=True, text=True)  # nosec B603

            if result.returncode != 0:
                if self.verbose:
                    logger.warning('Could not locate murmur package')
                return

            # Extract the Location line from pip show output
            location_line = next((line for line in result.stdout.split('\n') if line.startswith('Location: ')), None)
            if not location_line:
                return

            package_path = Path(location_line.split('Location: ')[1].strip())
            init_path = package_path / 'murmur' / artifact_type / '__init__.py'

            if not init_path.exists():
                return

            # Normalize package name to lowercase and replace hyphens with underscores
            package_name_pep8 = package_name.lower().replace('-', '_')
            import_line = f'from .{package_name_pep8}.main import {package_name_pep8}\n'

            with open(init_path) as f:
                lines = f.readlines()

            with open(init_path, 'w') as f:
                f.writelines(line for line in lines if line != import_line)

        except Exception as e:
            if self.verbose:
                logger.warning(f'Failed to clean up init files: {e}')

    def execute(self) -> None:
        """Execute the uninstall command.

        Raises:
            click.ClickException: If the uninstallation process fails.
        """
        try:
            self._uninstall_package(self.name)
            self._remove_from_init_file(self.name, 'agents')
            self._remove_from_init_file(self.name, 'tools')
            click.echo(click.style(f'Successfully uninstalled {self.name}', fg='green'))
        except click.ClickException:
            raise
        except Exception as e:
            raise click.ClickException(f'Failed to uninstall {self.name}: {e}')


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
            click.ClickException: If the uninstallation process fails.
        """
        cmd = UninstallArtifactCommand(name, verbose)
        cmd.execute()

    return uninstall
