import json
import logging
import subprocess
import sys
from pathlib import Path

import click

from mur.core.auth import AuthenticationManager
from mur.utils.error_handler import MessageType, MurError

logger = logging.getLogger(__name__)


class UninstallArtifactCommand:
    """Handles package uninstallation.

    Attributes:
        name (str): The name of the package to uninstall.
        verbose (bool): Whether to enable verbose logging output.
        username (str | None): The current user's username for scoped packages.
    """

    def __init__(self, name: str, verbose: bool = False) -> None:
        """Initialize uninstall command.

        Args:
            name: Name of the package to uninstall
            verbose: Whether to enable verbose output
        """
        self.name = name
        self.verbose = verbose

        # Get username for scoped packages
        self.auth_manager = AuthenticationManager.create(verbose=verbose)
        self.username = self.auth_manager.config.get('username')

    def _get_scoped_name(self, package_name: str) -> str:
        """Get the scoped package name if username exists.

        Args:
            package_name (str): Original package name

        Returns:
            str: Scoped package name if username exists, original name otherwise
        """
        if self.username:
            return f'{self.username}_{package_name}'
        return package_name

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

    def _normalize_package_name(self, package_name: str) -> str:
        """Normalize package name by converting hyphens and dots to underscores.

        Args:
            package_name (str): Package name to normalize

        Returns:
            str: Normalized package name
        """
        return package_name.lower().replace('-', '_').replace('.', '_')

    def _get_installed_packages(self) -> list[dict[str, str]]:
        """Get list of installed packages from pip.

        Returns:
            list[dict[str, str]]: List of installed packages with their details

        Raises:
            MurError: If package check fails
        """
        check_command = [sys.executable, '-m', 'pip', 'list', '--format=json']
        try:
            result = subprocess.run(check_command, capture_output=True, text=True)  # nosec B603
            if result.returncode != 0:
                raise MurError(code=309, message='Failed to check package status', original_error=result.stderr)
            return json.loads(result.stdout)
        except json.JSONDecodeError as e:
            raise MurError(code=309, message='Failed to parse pip output', original_error=str(e))

    def _get_package_variations(self, package_name: str) -> set[str]:
        """Generate possible variations of package name.

        Args:
            package_name: Base package name

        Returns:
            set[str]: Set of possible package name variations
        """
        return {
            package_name,  # original: tim-scoped-agent
            package_name.replace('-', '.'),  # dots: tim.scoped.agent
            package_name.replace('-', '_'),  # underscores: tim_scoped_agent
            f'{self.username}.{self._remove_scope(package_name)}',  # scoped with dot: tim.scoped-agent
        }

    def _find_installed_package(self, package_name: str, packages: list[dict[str, str]]) -> str | None:
        """Find actual installed package name from variations.

        Args:
            package_name: Package name to search for
            packages: List of installed packages

        Returns:
            str | None: Actual installed package name if found, None otherwise
        """
        variations = self._get_package_variations(package_name)
        if self.verbose:
            logger.debug(f'Trying package name variations: {variations}')

        for pkg in packages:
            if pkg['name'] in variations or self._normalize_package_name(pkg['name']) in {
                self._normalize_package_name(v) for v in variations
            }:
                return pkg['name']
        return None

    def _uninstall_package(self, package_name: str) -> None:
        """Uninstall a package using pip.

        Args:
            package_name: Name of the package to uninstall.

        Raises:
            MurError: If package check or uninstallation fails.
        """
        try:
            packages = self._get_installed_packages()
            if self.verbose:
                logger.debug(f'Found installed packages: {[p["name"] for p in packages]}')

            package_to_uninstall = self._find_installed_package(package_name, packages)
            if not package_to_uninstall:
                if self.verbose:
                    logger.info(f'Package {package_name} is not installed')
                return

            if self.verbose:
                logger.info(f'Uninstalling {package_to_uninstall}...')

            uninstall_command = [sys.executable, '-m', 'pip', 'uninstall', '-y', package_to_uninstall]
            result = subprocess.run(uninstall_command, capture_output=True, text=True)  # nosec B603

            if result.returncode != 0:
                raise MurError(
                    code=309, message=f'Failed to uninstall {package_to_uninstall}', original_error=result.stderr
                )

            if self.verbose:
                logger.info(f'Successfully uninstalled {package_to_uninstall}')

        except Exception as e:
            if not isinstance(e, MurError):
                raise MurError(code=309, message=f'Failed to process {package_name}', original_error=str(e))
            raise

    def _remove_from_init_file(self, package_name: str, artifact_type: str) -> None:
        """Remove package import from __init__.py if it exists.

        Args:
            package_name (str): Name of the package whose import should be removed.
            artifact_type (str): Type of artifact ('agents' or 'tools').
        """
        try:
            import importlib.util

            # Get the path to the namespace package
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
                code=200, message='Failed to clean up init files', type=MessageType.WARNING, original_error=e
            )

    def execute(self) -> None:
        """Execute the uninstall command.

        Raises:
            MurError: If the uninstallation process fails.
        """
        try:
            # First try with the name as provided
            if self.verbose:
                logger.debug(f'Attempting to uninstall package as provided: {self.name}')

            self._uninstall_package(self.name)

            # If that didn't work and we have a username, try with the scope
            if self.username and not (
                self.name.startswith(f'{self.username}_')
                or self.name.startswith(f'{self.username}-')
                or self.name.startswith(f'{self.username}.')
            ):
                scoped_name = f'{self.username}-{self.name}'
                if self.verbose:
                    logger.debug(f'Attempting to uninstall with scope: {scoped_name}')
                self._uninstall_package(scoped_name)

            # Always remove any username prefix for init file cleanup
            # This handles both cases: when prefix was provided or when we added it
            unscoped_name = self._remove_scope(
                self.name.replace(f'{self.username}-', '')
                .replace(f'{self.username}.', '')
                .replace(f'{self.username}_', '')
            )

            if self.verbose:
                logger.debug(f'Cleaning up init files with unscoped name: {unscoped_name}')

            self._remove_from_init_file(unscoped_name, 'agents')
            self._remove_from_init_file(unscoped_name, 'tools')
            click.echo(click.style(f'Successfully uninstalled {self.name}', fg='green'))
        except Exception as e:
            raise MurError(code=309, message=f'Failed to uninstall {self.name}', original_error=e)


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
