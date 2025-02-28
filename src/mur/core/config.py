import json
import logging
from pathlib import Path
from threading import Lock
from typing import Optional

from ..utils.constants import CONFIG_FILE, DEFAULT_CACHE_DIR, DEFAULT_TIMEOUT
from ..utils.error_handler import MessageType, MurError

logger = logging.getLogger(__name__)


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

    def __new__(cls, config_file: Path | str = CONFIG_FILE) -> 'ConfigManager':
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self, config_file: Path | str = CONFIG_FILE) -> None:
        # Prevent re-initialization of the singleton instance
        if self._initialized:
            return

        self.config_file = Path(config_file)
        self.config: ConfigDict = {'cache_dir': str(DEFAULT_CACHE_DIR), 'default_timeout': DEFAULT_TIMEOUT}
        self._load_config()
        self._initialized = True

    @classmethod
    def reset(cls) -> None:
        """Reset the singleton instance (primarily for testing)."""
        with cls._lock:
            cls._instance = None

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
