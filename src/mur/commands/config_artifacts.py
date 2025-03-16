import configparser
import logging
from pathlib import Path
from typing import Optional

import click

from ..utils.constants import DEFAULT_MURMUR_EXTRA_INDEX_URLS, DEFAULT_MURMUR_INDEX_URL, GLOBAL_MURMURRC_PATH
from ..utils.error_handler import MurError
from .base import ArtifactCommand

logger = logging.getLogger(__name__)

MAIN_CONFIG_SECTION = 'murmur-nexus'


class ConfigCommand(ArtifactCommand):
    """Manages Murmur configuration settings.

    Handles setting, getting, listing and unsetting configuration values
    in both global and local scopes using .murmurrc files.
    Local settings take precedence when present.
    """

    def __init__(self, verbose: bool = False) -> None:
        """Initialize config command.

        Override parent to prevent automatic .murmurrc creation. Initializes paths
        to both global and local configuration files.

        Args:
            verbose (bool): Whether to enable verbose output. Defaults to False.

        Attributes:
            global_config_path (Path): Path to global .murmurrc file
            local_config_path (Path): Path to local .murmurrc in current directory
        """
        super().__init__('config', verbose)

        # Initialize path
        self.global_config_path = GLOBAL_MURMURRC_PATH
        self.local_config_path = Path.cwd() / '.murmurrc'

    def _load_config(self, path: Path) -> configparser.ConfigParser:
        """Load configuration from .murmurrc file.

        Args:
            path: Path to .murmurrc file

        Returns:
            Loaded configuration
        """
        config = configparser.ConfigParser()
        if path.exists():
            config.read(path)
        if MAIN_CONFIG_SECTION not in config:
            config[MAIN_CONFIG_SECTION] = {}
        return config

    def set_config(self, key: str, value: str, use_global: bool = False) -> None:
        """Set configuration value.

        If local .murmurrc exists, it will be used unless use_global is True.
        If no local .murmurrc exists, global will be used.

        Args:
            key: Configuration key
            value: Configuration value
            use_global: Force using global config even if local exists

        Raises:
            MurError: If config file cannot be written
        """
        try:
            # Determine which config to use
            use_local = self.local_config_path.exists() and not use_global
            config_path = self.local_config_path if use_local else self.global_config_path
            scope = 'local' if use_local else 'global'

            config_path.parent.mkdir(parents=True, exist_ok=True)
            config = self._load_config(config_path)
            config[MAIN_CONFIG_SECTION][key] = value

            with open(config_path, 'w') as f:
                config.write(f)

            self.log_success(f'Set {key}={value} in {scope} .murmurrc')

        except Exception as e:
            raise MurError(code=401, message=f'Failed to set {key} in configuration', original_error=e)

    def get_config(self, key: str) -> Optional[str]:
        """Get configuration value.

        Checks local .murmurrc first if it exists, falls back to global.

        Args:
            key: Configuration key to retrieve

        Returns:
            Configuration value if found, None otherwise
        """
        try:
            # Check local first if it exists
            if self.local_config_path.exists():
                local_config = self._load_config(self.local_config_path)
                if key in local_config[MAIN_CONFIG_SECTION]:
                    value = local_config[MAIN_CONFIG_SECTION][key]
                    click.echo(f'{key}: {value} (local)')
                    return value

            # Fall back to global
            if self.global_config_path.exists():
                global_config = self._load_config(self.global_config_path)
                if key in global_config[MAIN_CONFIG_SECTION]:
                    value = global_config[MAIN_CONFIG_SECTION][key]
                    click.echo(f'{key}: {value} (global)')
                    return value

            click.echo(f"Configuration key '{key}' not found in local or global .murmurrc")
            return None

        except Exception as e:
            raise MurError(code=402, message=f'Failed to get configuration for {key}', original_error=e)

    def list_config(self) -> None:
        """List all configuration values.

        Raises:
            MurError: If configs cannot be read
        """
        try:
            # Load both configs
            global_config = self._load_config(self.global_config_path)
            local_config = self._load_config(self.local_config_path)

            # Display global settings
            if global_config[MAIN_CONFIG_SECTION]:
                click.echo('\nGlobal settings (.murmurrc):')
                click.echo(f'Path: {self.global_config_path}')
                for key, value in global_config[MAIN_CONFIG_SECTION].items():
                    click.echo(f'{key}: {value}')

            # Display local settings
            if local_config[MAIN_CONFIG_SECTION]:
                click.echo('\nLocal settings (.murmurrc):')
                click.echo(f'Path: {self.local_config_path}')
                for key, value in local_config[MAIN_CONFIG_SECTION].items():
                    click.echo(f'{key}: {value}')

            if not (global_config[MAIN_CONFIG_SECTION] or local_config[MAIN_CONFIG_SECTION]):
                click.echo('No configuration values found')

        except Exception as e:
            raise MurError(code=403, message='Failed to list configurations', original_error=e)

    def unset_config(self, key: str, use_global: bool = False) -> None:
        """Unset configuration value.

        If local .murmurrc exists, it will be used unless use_global is True.
        If no local .murmurrc exists, global will be used.

        Args:
            key: Configuration key to unset
            use_global: Force using global config even if local exists
        """
        try:
            # Determine which config to use
            use_local = self.local_config_path.exists() and not use_global
            config_path = self.local_config_path if use_local else self.global_config_path
            scope = 'local' if use_local else 'global'

            if config_path.exists():
                config = self._load_config(config_path)
                if key in config[MAIN_CONFIG_SECTION]:
                    del config[MAIN_CONFIG_SECTION][key]
                    with open(config_path, 'w') as f:
                        config.write(f)
                    self.log_success(f'Removed {key} from {scope} .murmurrc')
                    return

            click.echo(f"Configuration key '{key}' not found in {scope} .murmurrc")

        except Exception as e:
            raise MurError(code=404, message=f'Failed to unset configuration for {key}', original_error=e)

    def init_config(self, use_global: bool = False) -> None:
        """Initialize a new .murmurrc file.

        Creates a new .murmurrc file with default settings in either local
        or global location. If file exists, notifies user.

        Args:
            use_global: Force creating global config even if local exists
        """
        try:
            config_path = self.global_config_path if use_global else self.local_config_path
            scope = 'global' if use_global else 'local'
            alt_path = self.local_config_path if use_global else self.global_config_path

            if config_path.exists():
                message = f'{scope.capitalize()} .murmurrc already exists at: {config_path}'
                # Only show alternative if it doesn't exist
                if not alt_path.exists():
                    message += (
                        f"\nTo create a {'local' if use_global else 'global'} config instead, "
                        f"run: mur config init{' --global' if not use_global else ''}"
                    )
                click.echo(message)
                return

            # Create parent directories if they don't exist
            config_path.parent.mkdir(parents=True, exist_ok=True)

            # Create new config with default settings
            config = configparser.ConfigParser()
            config[MAIN_CONFIG_SECTION] = {
                'index-url': DEFAULT_MURMUR_INDEX_URL,
                'extra-index-url': ' '.join(DEFAULT_MURMUR_EXTRA_INDEX_URLS),
            }

            with open(config_path, 'w') as f:
                config.write(f)

            message = f'Created {scope} .murmurrc at: {config_path}'
            # Only show alternative if it doesn't exist
            if not alt_path.exists():
                message += (
                    f"\nTo create a {'local' if use_global else 'global'} config instead, "
                    f"run: mur config init{' --global' if not use_global else ''}"
                )
            self.log_success(message)

        except Exception as e:
            raise MurError(code=405, message=f'Failed to create {scope} .murmurrc', original_error=e)


def config_command() -> click.Group:
    """Create the config command group for Click.

    Returns:
        Click command group for managing configurations
    """

    @click.group()
    def config() -> None:
        """Manage Murmur configuration settings."""
        pass

    @config.command()
    @click.argument('key')
    @click.argument('value')
    @click.option('--global', 'use_global', is_flag=True, help='Force using global config')
    @click.option('--verbose', '-v', is_flag=True, help='Enable verbose output')
    def set(key: str, value: str, use_global: bool, verbose: bool) -> None:
        """Set a configuration value."""
        cmd = ConfigCommand(verbose)
        cmd.set_config(key, value, use_global)

    @config.command()
    @click.argument('key')
    @click.option('--verbose', '-v', is_flag=True, help='Enable verbose output')
    def get(key: str, verbose: bool) -> None:
        """Get a configuration value."""
        cmd = ConfigCommand(verbose)
        cmd.get_config(key)

    @config.command()
    @click.option('--verbose', '-v', is_flag=True, help='Enable verbose output')
    def list(verbose: bool) -> None:
        """List all configuration values."""
        cmd = ConfigCommand(verbose)
        cmd.list_config()

    @config.command()
    @click.argument('key')
    @click.option('--global', 'use_global', is_flag=True, help='Force using global config')
    @click.option('--verbose', '-v', is_flag=True, help='Enable verbose output')
    def unset(key: str, use_global: bool, verbose: bool) -> None:
        """Unset a configuration value."""
        cmd = ConfigCommand(verbose)
        cmd.unset_config(key, use_global)

    @config.command()
    @click.option('--global', 'use_global', is_flag=True, help='Create global config instead of local')
    @click.option('--verbose', '-v', is_flag=True, help='Enable verbose output')
    def init(use_global: bool, verbose: bool) -> None:
        """Initialize a new .murmurrc file.

        Creates a new configuration file with default settings. By default creates
        a local .murmurrc in the current directory. Use --global to create in the
        user's home directory instead.
        """
        cmd = ConfigCommand(verbose)
        cmd.init_config(use_global)

    return config
