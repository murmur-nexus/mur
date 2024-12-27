import configparser
import logging
import os
import sys
from pathlib import Path
from typing import ClassVar

import click
from ruamel.yaml import YAML

from ..adapters.adapter_factory import get_registry_adapter
from ..core.auth import AuthenticationManager
from ..core.config import ConfigManager
from ..core.packaging import PackageConfig
from ..utils.constants import DEFAULT_MURMUR_EXTRA_INDEX_URLS, DEFAULT_MURMUR_INDEX_URL, MURMURRC_PATH

logger = logging.getLogger(__name__)


class ArtifactCommand:
    """Base class for artifact-related commands.

    This class provides common functionality for commands that interact with artifacts,
    including configuration management, authentication, and registry operations.

    Attributes:
        REGISTRY_COMMANDS: List of commands that require registry configuration.
    """

    REGISTRY_COMMANDS: ClassVar[list[str]] = ['install', 'publish']

    def __init__(self, command_name: str, verbose: bool = False) -> None:
        """Initialize artifact command.

        Args:
            command_name: Name of the command
            verbose: Whether to enable verbose output
        """
        self.command_name = command_name
        self.verbose = verbose
        self._ensure_murmur_namespace_in_path()

        # Initialize yaml and current_dir for config loading
        self.current_dir = self.get_current_dir()
        self.yaml = self._configure_yaml()

        # Only ensure .murmurrc exists for commands that need it
        if self.command_name in self.REGISTRY_COMMANDS:
            if self.verbose:
                logger.info(f'Setting up registry configuration for {self.command_name} command')
            self._ensure_murmurrc_exists()

        self.config = ConfigManager()
        self.auth_manager = AuthenticationManager.create(verbose)

        # Use adapter
        self.registry = get_registry_adapter(verbose)

        if verbose:
            logger.setLevel(logging.DEBUG)

    def _get_index_urls_from_murmurrc(self, murmurrc_path: str) -> tuple[str, list[str]]:
        """Get index URLs from .murmurrc file.

        Args:
            murmurrc_path: Path to .murmurrc file.

        Returns:
            tuple: A tuple containing:
                - str: The primary index URL
                - list[str]: List of extra index URLs

        Raises:
            FileNotFoundError: If .murmurrc file does not exist.
            ValueError: If index-url is not found in config.
        """
        config = configparser.ConfigParser()
        if not os.path.exists(murmurrc_path):
            raise FileNotFoundError(f'{murmurrc_path} not found.')
        config.read(murmurrc_path)

        index_url = config.get('global', 'index-url', fallback=None)
        if not index_url:
            raise ValueError("No 'index-url' found in .murmurrc under [global].")

        # Get all extra-index-url values
        extra_index_urls: list[str] = []
        if config.has_option('global', 'extra-index-url'):
            # Handle both single and multiple extra-index-url entries
            extra_urls = config.get('global', 'extra-index-url')
            extra_index_urls.extend(url.strip() for url in extra_urls.split('\n') if url.strip())

        return index_url, extra_index_urls

    def _ensure_murmurrc_exists(self) -> None:
        """Create or update .murmurrc with index URLs from environment or defaults.

        Creates a new .murmurrc file if it doesn't exist, or updates the existing one.
        Uses environment variables MURMUR_INDEX_URL and MURMUR_EXTRA_INDEXES if available,
        otherwise falls back to default values.
        """
        if self.verbose:
            logger.info('Checking .murmurrc configuration...')

        config = configparser.ConfigParser()

        # Get primary index URL
        index_url = os.getenv('MURMUR_INDEX_URL', DEFAULT_MURMUR_INDEX_URL)

        # Get extra indexes
        extra_indexes = os.getenv('MURMUR_EXTRA_INDEXES')
        if extra_indexes:
            extra_index_list = [url.strip() for url in extra_indexes.split(',')]
        else:
            extra_index_list = DEFAULT_MURMUR_EXTRA_INDEX_URLS

        # Create/update .murmurrc
        config['global'] = {'index-url': index_url, 'extra-index-url': '\n'.join(extra_index_list)}

        with open(MURMURRC_PATH, 'w') as f:
            config.write(f)

        if self.verbose:
            logger.info(f'Updated {MURMURRC_PATH} with index URLs')

    def _ensure_murmur_namespace_in_path(self) -> None:
        """Ensure murmur packages directory is in Python path.

        Adds the .murmur_packages directory from the user's home directory to sys.path
        if it's not already present.
        """
        namespace_dir = Path.home() / '.murmur_packages'
        namespace_dir_str = str(namespace_dir)

        if namespace_dir_str not in sys.path:
            sys.path.append(namespace_dir_str)
            if self.verbose:
                logger.info(f'Added {namespace_dir} to Python path')
            logger.debug(f'Updated sys.path: {sys.path}')

    def get_current_dir(self) -> Path:
        """Get current working directory.

        Returns:
            Path to current directory

        Raises:
            click.ClickException: If current directory cannot be accessed
        """
        try:
            return Path.cwd()
        except Exception:
            raise click.ClickException(
                'Cannot access the current directory. '
                "This usually happens when the current directory has been deleted or you don't have permissions. "
                "Please ensure you're in a valid directory and try again."
            )

    def handle_error(self, error: Exception, message: str) -> None:
        """Handle command errors consistently.

        Args:
            error: The exception that occurred.
            message: Error message prefix to display before the error details.

        Raises:
            click.Abort: Always raised after logging the error.
        """
        error_msg = f'{message}:\n{error!s}'
        logger.error(error_msg, exc_info=True)
        raise click.Abort()

    def log_success(self, message: str) -> None:
        """Log success message in green color.

        Args:
            message: Success message to display.
        """
        click.echo(click.style(message, fg='green'))

    def _configure_yaml(self) -> YAML:
        """Configure YAML parser settings.

        Returns:
            YAML: Configured YAML parser instance with specific formatting settings.
        """
        yaml = YAML()
        yaml.default_flow_style = False
        yaml.explicit_start = False
        yaml.explicit_end = False
        yaml.preserve_quotes = True
        return yaml

    def _load_murmur_yaml_from_current_dir(self) -> PackageConfig:
        """Load installation manifest from murmur.yaml in current directory.

        Returns:
            PackageConfig: Package configuration from the installation manifest.

        Raises:
            click.ClickException: If murmur.yaml is not found or cannot be loaded.
        """
        config_file = self.current_dir / 'murmur.yaml'

        logger.debug(f'Checking config file at: {config_file}')

        if config_file.exists():
            try:
                return PackageConfig(config_file, is_build_manifest=False)  # Installation manifest
            except Exception as e:
                logger.debug(f'Error loading {config_file}: {e!s}')
                raise click.ClickException(f'Failed to load murmur.yaml: {e!s}')

        raise click.ClickException('murmur.yaml not found in current directory')

    def _load_murmur_yaml_from_package(self) -> PackageConfig:
        """Load build manifest from murmur-build.yaml in package entry folder.

        Searches for murmur-build.yaml in both agent and tool package directories.

        Returns:
            PackageConfig: Package configuration from the build manifest.

        Raises:
            click.ClickException: If murmur-build.yaml is not found in any package directory.
        """
        for artifact_type in ['agent', 'tool']:
            package_entry_path = self.current_dir / 'src' / 'murmur' / f'{artifact_type}s' / self.current_dir.name
            config_file = package_entry_path / 'murmur-build.yaml'

            logger.debug(f'Checking config file at: {config_file}')

            if config_file.exists():
                try:
                    return PackageConfig(config_file, is_build_manifest=True)  # Build manifest
                except Exception as e:
                    logger.debug(f'Error loading {config_file}: {e!s}')
                    continue
            else:
                logger.debug('Failed to load murmur-build.yaml: trying next artifact type instead')

        raise click.ClickException('Failed to load: murmur-build.yaml not found in package directory')
