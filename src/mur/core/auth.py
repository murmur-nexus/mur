import logging

import click
import requests

from ..utils.constants import DEFAULT_TIMEOUT, MURMUR_SERVER_URL
from .cache import CacheError, CredentialCache
from .config import ConfigManager

logger = logging.getLogger(__name__)


class AuthenticationError(Exception):
    """Raised when authentication operations fail.

    This exception is used throughout the authentication module to indicate
    failures in authentication-related operations such as login attempts,
    credential management, and token validation.
    """

    pass


class AuthenticationManager:
    """Centralized authentication management for Mur CLI.

    This class handles all authentication-related operations including token management,
    credential caching, and user authentication flows.

    Attributes:
        verbose (bool): Flag for enabling verbose logging output
        cache (CredentialCache): Instance for managing cached credentials
        config_manager (ConfigManager): Instance for managing configuration
        config (dict): Current configuration settings
        base_url (str): Base URL for the registry API
    """

    def __init__(self, config_manager: ConfigManager, base_url: str, verbose: bool = False) -> None:
        """Initialize authentication manager.

        Args:
            config_manager: Configuration manager instance
            base_url: Base URL for the registry API
            verbose: Whether to enable verbose output

        Raises:
            AuthenticationError: If initialization fails
        """
        try:
            self.verbose = verbose
            self.cache = CredentialCache()
            self.config_manager = config_manager
            self.config = self.config_manager.get_config()
            self.base_url = base_url

            if verbose:
                logger.setLevel(logging.DEBUG)

        except (Exception, CacheError) as e:
            raise AuthenticationError(f'Failed to initialize authentication: {e}')

    def authenticate(self) -> str:
        """Get a valid access token, using cached credentials when possible.

        This method implements the following authentication flow:
        1. Try to use cached access token
        2. Try to authenticate with cached credentials
        3. Prompt user for credentials if needed

        Returns:
            str: Valid access token for API authentication

        Raises:
            AuthenticationError: If authentication fails at any step
        """
        try:
            # Try cached access token
            if access_token := self.cache.load_access_token():
                if self._validate_token(access_token):
                    logger.debug('Using cached access token')
                    return access_token

            # Try using cached credentials
            if (username := str(self.config.get('username'))) and (password := self.cache.load_password()):
                if self.verbose:
                    logger.info('Authenticating with cached credentials')
                if access_token := self._authenticate(username, password):
                    return access_token

            # Need to prompt for credentials
            return self._prompt_and_authenticate()

        except (CacheError, Exception) as e:
            raise AuthenticationError(f'Authentication failed: {e}')

    def _validate_token(self, token: str) -> bool:
        """Validate if the token is still valid.

        Args:
            token (str): Access token to validate

        Returns:
            bool: True if token is valid, False otherwise

        Note:
            Currently assumes token is valid if it exists.
            Should be updated to validate against server.
        """
        return bool(token)

    def _authenticate(self, username: str, password: str) -> str | None:
        """Authenticate with username and password.

        Attempts to authenticate against the server using provided credentials.

        Args:
            username (str): Username for authentication
            password (str): Password for authentication

        Returns:
            str | None: Access token if authentication successful, None otherwise

        Note:
            On successful authentication, credentials are automatically cached.
        """
        try:
            url = f'{self.base_url}/login'
            payload = {'grant_type': 'password', 'username': username, 'password': password}
            headers = {'Content-Type': 'application/x-www-form-urlencoded'}

            logger.debug(f'Authenticating user at {url}')

            response = requests.post(url, headers=headers, data=payload, timeout=DEFAULT_TIMEOUT)

            if response.status_code == 200:
                data = response.json()
                if access_token := data.get('access_token'):
                    self._save_credentials(username, password, access_token)
                    return access_token

            return None

        except Exception as e:
            logger.debug(f'Authentication failed: {e}')
            return None

    def _save_credentials(self, username: str, password: str, access_token: str) -> None:
        """Save credentials for future use.

        Args:
            username: Username to save
            password: Password to save
            access_token: Access token to save

        Raises:
            AuthenticationError: If credentials cannot be saved
        """
        try:
            self.cache.save_access_token(access_token)
            self.config['username'] = username
            self.config_manager.save_config()
            self.cache.save_password(password)
            logger.debug('Saved credentials')
        except (CacheError, Exception) as e:
            raise AuthenticationError(f'Failed to save credentials: {e}')

    def _prompt_and_authenticate(self) -> str:
        """Prompt for credentials and authenticate.

        Interactively prompts the user for credentials and attempts authentication.
        Uses cached username if available.

        Returns:
            str: Valid access token

        Raises:
            AuthenticationError: If authentication fails
            click.Abort: If user cancels authentication
        """
        click.echo('Authentication required')

        try:
            username = str(self.config.get('username'))
            if not username:
                username = click.prompt('Username', type=str)

            password = click.prompt('Password', type=str, hide_input=True)

            if access_token := self._authenticate(username, password):
                return access_token

            raise AuthenticationError('Invalid credentials')

        except click.Abort:
            logger.debug('User cancelled authentication')
            raise
        except Exception as e:
            raise AuthenticationError(f'Authentication failed: {e}')

    def clear_credentials(self) -> None:
        """Clear all stored credentials.

        Removes all cached credentials including:
        - Access token
        - Password
        - Username from configuration

        Raises:
            AuthenticationError: If credentials cannot be cleared
        """
        try:
            self.cache.clear_access_token()
            self.cache.clear_password()
            if 'username' in self.config:
                del self.config['username']
                self.config_manager.save_config()
            logger.debug('Cleared all credentials')
        except (CacheError, Exception) as e:
            raise AuthenticationError(f'Failed to clear credentials: {e}')

    @classmethod
    def create(cls, verbose: bool = False, base_url: str = MURMUR_SERVER_URL) -> 'AuthenticationManager':
        """Create an AuthenticationManager with dependencies.

        Factory method to create a new instance with proper configuration.

        Args:
            verbose (bool, optional): Enable verbose logging. Defaults to False.
            base_url (str, optional): Base URL for the registry API.
                Defaults to MURMUR_SERVER_URL.

        Returns:
            AuthenticationManager: Configured instance

        Raises:
            AuthenticationError: If manager creation fails
        """
        try:
            config_manager = ConfigManager()
            return cls(config_manager, base_url, verbose)
        except Exception as e:
            raise AuthenticationError(f'Failed to create authentication manager: {e}')
