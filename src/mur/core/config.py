import json
import logging
from pathlib import Path

import click

from ..utils.constants import CONFIG_FILE, DEFAULT_CACHE_DIR, DEFAULT_TIMEOUT

logger = logging.getLogger(__name__)


class ConfigError(Exception):
    """Raised when configuration operations fail.

    This exception is used to indicate errors during configuration file operations
    such as saving or loading configuration data.
    """

    pass


ConfigDict = dict[str, str | int | bool | None]


class ConfigManager:
    """Manages Mur CLI configuration.

    This class handles loading, saving, and accessing configuration settings
    for the Mur CLI application.

    Attributes:
        config_file (Path): Path to the configuration file.
        config (ConfigDict): Dictionary containing configuration settings.
    """

    def __init__(self, config_file: Path | str = CONFIG_FILE) -> None:
        """Initialize configuration manager.

        Args:
            config_file (Path | str): Path to configuration file. Defaults to CONFIG_FILE.
        """
        self.config_file = Path(config_file)
        self.config: ConfigDict = {'cache_dir': str(DEFAULT_CACHE_DIR), 'default_timeout': DEFAULT_TIMEOUT}
        self._load_config()

    def _load_config(self) -> None:
        """Load configuration from file.

        Updates default configuration with values from file.
        Silently uses defaults if file doesn't exist or is invalid.

        Note:
            If the configuration file cannot be read or parsed, warning messages
            will be displayed and default values will be used.
        """
        try:
            if self.config_file.exists():
                with open(self.config_file) as f:
                    file_config = json.load(f)
                self.config.update(file_config)
                logger.debug(f'Loaded configuration from {self.config_file}')
        except json.JSONDecodeError as e:
            click.echo(f'Warning: Invalid config file format: {e}', err=True)
        except Exception as e:
            click.echo(f'Warning: Failed to load config file: {e}', err=True)

    def save_config(self) -> None:
        """Save current configuration to file.

        Creates configuration directory if it doesn't exist.

        Raises:
            ConfigError: If the configuration cannot be saved due to file system
                errors or permission issues.
        """
        try:
            self.config_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.config_file, 'w') as f:
                json.dump(self.config, f, indent=4)
            logger.debug(f'Saved configuration to {self.config_file}')
        except Exception as e:
            raise ConfigError(f'Failed to save configuration: {e}')

    def get_config(self) -> ConfigDict:
        """Get current configuration.

        Returns:
            ConfigDict: A copy of the current configuration dictionary to prevent
                direct modification of internal state.
        """
        return self.config.copy()
