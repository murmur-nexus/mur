import json
import logging
import os
from pathlib import Path
from threading import Lock
from typing import Optional

from ..utils.constants import DEFAULT_TIMEOUT
from ..utils.error_handler import MessageType, MurError

logger = logging.getLogger(__name__)

# Determine the base configuration directory following XDG standard
XDG_CONFIG_HOME = Path(os.getenv('XDG_CONFIG_HOME', Path.home() / '.config'))
MURMUR_CONFIG_DIR = XDG_CONFIG_HOME / 'murmur'
DEFAULT_CONFIG_FILE = MURMUR_CONFIG_DIR / 'config.json'

# Get the XDG cache path or fallback to `~/.cache/murmur/`
XDG_CACHE_HOME = Path(os.getenv('XDG_CACHE_HOME', Path.home() / '.cache'))
MURMUR_CACHE_DIR = XDG_CACHE_HOME / 'murmur'

ConfigDict = dict[str, str | int | bool | None]


class ConfigManager:
    """Singleton class for managing application configuration.

    This class handles loading, saving, and accessing configuration settings from a JSON file.
    It implements the singleton pattern to ensure only one configuration manager exists
    throughout the application lifecycle.

    Attributes:
        config_file (Path): Path to the configuration file
        config (ConfigDict): Dictionary containing the configuration settings
    """

    _instance: Optional['ConfigManager'] = None
    _lock = Lock()
    _initialized: bool = False

    def __new__(cls, config_file: Path | str = DEFAULT_CONFIG_FILE) -> 'ConfigManager':
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self, config_file: Path | str = DEFAULT_CONFIG_FILE) -> None:
        """Initialize the configuration manager.

        Args:
            config_file: Path to the configuration file
        """
        # Prevent re-initialization of the singleton instance
        if self._initialized:
            return

        self.config_file = Path(config_file)
        self.config: ConfigDict = {'cache_dir': str(MURMUR_CACHE_DIR), 'default_timeout': DEFAULT_TIMEOUT}

        # Ensure XDG directories and default config file exist
        self._ensure_xdg_directories()

        # Load config (which now always exists)
        self._load_config()

        self._initialized = True

    @classmethod
    def reset(cls) -> None:
        """Reset the singleton instance (primarily for testing)."""
        with cls._lock:
            cls._instance = None

    def _ensure_xdg_directories(self) -> None:
        """Ensure that the config and cache directories exist following XDG standards.

        Also creates a default config file if it doesn't exist.
        """
        # Ensure config directory exists
        MURMUR_CONFIG_DIR.mkdir(parents=True, exist_ok=True)

        # Ensure cache directory exists
        MURMUR_CACHE_DIR.mkdir(parents=True, exist_ok=True)

        # Create default config file if it doesn't exist
        if not self.config_file.exists():
            logger.debug(f'Config file {self.config_file} not found, creating with default values')
            with open(self.config_file, 'w') as f:
                json.dump(self.config, f, indent=4)
            logger.debug(f'Created default config file at {self.config_file}')

        logger.debug(f'Ensured config directory at: {MURMUR_CONFIG_DIR}')
        logger.debug(f'Ensured cache directory at: {MURMUR_CACHE_DIR}')

    def _load_config(self) -> None:
        """Load configuration from file."""
        try:
            if self.config_file.exists():
                with open(self.config_file) as f:
                    file_config = json.load(f)
                self.config.update(file_config)
                logger.debug(f'Loaded configuration from {self.config_file}')
            else:
                logger.debug('Config file does not exist')
        except json.JSONDecodeError as e:
            raise MurError(
                code=204,
                message='Invalid configuration file format',
                detail='The configuration file is not valid JSON',
                original_error=e,
                type=MessageType.WARNING,
            )
        except Exception as e:
            raise MurError(
                code=200,
                message='Failed to load configuration file',
                detail='Check file permissions and try again',
                original_error=e,
                type=MessageType.WARNING,
            )

    def save_config(self) -> None:
        """Thread-safe save of configuration to file with timeout."""
        if not self._lock.acquire(timeout=1.0):
            raise MurError(
                code=208,
                message='Failed to acquire lock for saving configuration',
                detail='Another process might be updating the configuration',
            )
        try:
            self.config_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.config_file, 'w') as f:
                json.dump(self.config, f, indent=4)
            logger.debug(f'Successfully saved config to {self.config_file}')
        except Exception as e:
            raise MurError(
                code=200,
                message='Failed to save configuration',
                detail='Check file permissions and available disk space',
                original_error=e,
            )
        finally:
            self._lock.release()

    def get_config(self) -> ConfigDict:
        """Get current configuration.

        Returns:
            ConfigDict: A copy of the current configuration dictionary to prevent
                direct modification of internal state.
        """
        # Reload config before returning
        self._load_config()
        return self.config.copy()

    def get_cache_dir(self) -> Path:
        """Get the path to the cache directory.

        Returns:
            Path: The path to the cache directory.
        """
        cache_dir_value = self.config.get('cache_dir')
        # Ensure we have a valid string path
        if cache_dir_value is None or not isinstance(cache_dir_value, (str, os.PathLike)):
            cache_dir = MURMUR_CACHE_DIR
        else:
            cache_dir = Path(cache_dir_value)
        cache_dir.mkdir(parents=True, exist_ok=True)
        return cache_dir
