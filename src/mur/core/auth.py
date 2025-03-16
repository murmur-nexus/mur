import logging

import click

from ..utils.constants import MURMUR_SERVER_URL
from ..utils.error_handler import MurError
from ..utils.models import AccountListResponse, LoginRequest, LoginResponse, UserConfig
from .api_client import ApiClient
from .cache import CredentialCache
from .config import ConfigManager

logger = logging.getLogger(__name__)


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
            MurError: If initialization fails
        """
        try:
            self.verbose = verbose
            self.cache = CredentialCache()
            self.config_manager = config_manager
            self.config = self.config_manager.get_config()
            self.base_url = base_url

            if verbose:
                logger.setLevel(logging.DEBUG)

            self.api_client = ApiClient(base_url, verbose)

        except MurError:
            raise
        except Exception as e:
            raise MurError(code=501, message='Failed to initialize authentication', original_error=e)

    def authenticate(self) -> str:
        """Get a valid access token, using cached credentials when possible.

        This method implements the following authentication flow:
        1. Try to use cached access token
        2. Try to authenticate with cached credentials
        3. Prompt user for credentials if needed

        Returns:
            str: Valid access token for API authentication

        Raises:
            MurError: If authentication fails at any step
        """
        try:
            # Try cached access token
            if access_token := self.cache.load_credential('access_token'):
                if self._validate_token(access_token):
                    logger.debug('Using cached access token')
                    return access_token

            # Try using cached credentials
            if (username := str(self.config.get('username'))) and (password := self.cache.load_credential('password')):
                if self.verbose:
                    logger.info('Authenticating with cached credentials')
                if access_token := self._authenticate(username, password):
                    # Fetch user accounts
                    self.fetch_user_accounts()
                    return access_token

            # Need to prompt for credentials
            return self._prompt_and_authenticate()

        except MurError:
            raise
        except Exception as e:
            raise MurError(
                code=501,
                message='Authentication failed',
                detail='Failed to authenticate with provided credentials',
                original_error=e,
            )

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

        Raises:
            MurError: If authentication fails due to invalid credentials or server error
        """
        try:
            login_payload = LoginRequest(username=username, password=password)

            response = self.api_client.post(
                endpoint='/auth/login',
                payload=login_payload,
                response_model=LoginResponse,
                query_params={'grant_type': 'password'},
                content_type='application/x-www-form-urlencoded',
            )

            if response.status_code == 200 and response.data:
                logger.debug(f'Access token: {response.data.access_token}')

                if not response.data.user:
                    raise MurError(code=507, message='Missing User Data', detail='Missing user data in response')

                # User is already a UserConfig object, no need to create a new one
                self._save_user_session(response.data.user)
                self._save_credentials(password, response.data.access_token, response.data.refresh_token)
                return response.data.access_token

            return None

        except MurError:
            raise
        except Exception as e:
            logger.debug(f'Error: {e}')
            raise MurError(
                code=501,
                message='Authentication failed',
                detail='Failed to authenticate with provided credentials',
                original_error=e,
            )

    def _save_user_session(self, user: UserConfig) -> None:
        """Save user session for future use."""
        try:
            # Get the current config from the manager and update it
            config = self.config_manager.config

            # Since user is already a UserConfig object, we can directly use it
            config.update(user.model_dump(exclude_none=True))

            # Save the updated config
            self.config_manager.save_config()

            # Update our local copy
            self.config = self.config_manager.get_config()

            logger.debug('Saved user session')
        except MurError:
            raise
        except Exception as e:
            raise MurError(code=501, message='Failed to save user session', original_error=e)

    def _save_credentials(self, password: str, access_token: str, refresh_token: str) -> None:
        """Save credentials for future use."""
        try:
            self.cache.save_credential('access_token', access_token)
            self.cache.save_credential('refresh_token', refresh_token)
            self.cache.save_credential('password', password)
            logger.debug('Saved credentials')
        except MurError:
            raise
        except Exception as e:
            raise MurError(code=501, message='Failed to save credentials', original_error=e)

    def _prompt_and_authenticate(self) -> str:
        """Prompt for credentials and authenticate.

        Interactively prompts the user for credentials and attempts authentication.
        Uses cached username if available.

        Returns:
            str: Valid access token

        Raises:
            MurError: If authentication fails
            click.Abort: If user cancels authentication
        """
        click.echo('Authentication required')

        try:
            # Get and validate username
            cached_username = self.config.get('username')
            if not cached_username:
                username = click.prompt('Username', type=str)
            else:
                # Ensure username is str type
                username = str(cached_username)
                logger.debug(f'Using cached username: {username}')

            password = click.prompt('Password', type=str, hide_input=True)

            # At this point username is guaranteed to be a str
            if access_token := self._authenticate(username, password):
                # Fetch user accounts
                self.fetch_user_accounts()
                return access_token

            raise MurError(
                code=503, message='Invalid credentials', detail='Please check your username and password and try again'
            )

        except click.Abort:
            logger.debug('User cancelled authentication')
            raise
        except MurError:
            raise
        except Exception as e:
            raise MurError(code=501, message='Authentication failed', original_error=e)

    def clear_credentials(self) -> None:
        """Clear all stored credentials.

        Removes all cached credentials including:
        - Access token
        - Refresh token
        - Password
        - User data from configuration (id, username, email, etc.)
        - User accounts from configuration
        Raises:
            MurError: If credentials cannot be cleared
        """
        try:
            # Clear cached tokens and password
            self.cache.clear_credential('access_token')
            self.cache.clear_credential('refresh_token')
            self.cache.clear_credential('password')

            # Clear user data from config using UserConfig model fields
            user_keys = list(UserConfig.model_fields.keys())

            for key in user_keys:
                if key in self.config_manager.config:
                    self.config_manager.config.pop(key, None)

            # Clear user_accounts from config
            self.config_manager.config.pop('user_accounts', None)

            # Save the updated config
            self.config_manager.save_config()

            # Update our local copy
            self.config = self.config_manager.get_config()

            logger.debug(f'Cleared all credentials and user data fields: {user_keys}')
        except MurError:
            raise
        except Exception as e:
            raise MurError(code=501, message='Failed to clear credentials', original_error=e)

    @classmethod
    def create(cls, verbose: bool = False, base_url: str = MURMUR_SERVER_URL.rstrip('/')) -> 'AuthenticationManager':
        """Create an AuthenticationManager with dependencies.

        Factory method to create a new instance with proper configuration.

        Args:
            verbose (bool, optional): Enable verbose logging. Defaults to False.
            base_url (str, optional): Base URL for the registry API.
                Defaults to MURMUR_SERVER_URL.rstrip('/').

        Returns:
            AuthenticationManager: Configured instance

        Raises:
            MurError: If manager creation fails
        """
        try:
            config_manager = ConfigManager()
            return cls(config_manager, base_url, verbose)
        except Exception as e:
            raise MurError(code=501, message='Failed to create authentication manager', original_error=e)

    def is_authenticated(self) -> bool:
        """Check if the user is currently authenticated.

        Returns:
            bool: True if the user has valid credentials, False otherwise
        """
        try:
            # Check if we have a valid access token
            # TODO: Check expiration date and attempt refresh token auth
            access_token = self.cache.load_credential('access_token')
            if access_token and self._validate_token(access_token):
                return True

            # Check if we have cached credentials
            username = self.config.get('username')
            password = self.cache.load_credential('password')

            # Consider the user authenticated if both username and password are present
            return bool(username and password)

        except Exception:
            logger.debug('Error checking authentication status', exc_info=True)
            return False

    def fetch_user_accounts(self) -> list[str]:
        """Fetch user accounts and store their names in configuration.

        Returns:
            list[str]: List of account names

        Raises:
            MurError: If fetching accounts fails
        """
        try:
            # Get user ID from config
            user_id = self.config.get('id')
            if not user_id:
                logger.debug('Missing user ID, cannot fetch accounts')
                raise MurError(code=507, message='Missing User Data', detail='User ID is required to fetch accounts')

            # Get access token from the current session
            access_token = self.cache.load_credential('access_token')
            if not access_token:
                logger.debug('Missing access token, cannot fetch accounts')
                raise MurError(
                    code=507, message='Missing User Data', detail='Access token is required to fetch accounts'
                )

            response = self.api_client.get(
                endpoint=f'/users/{user_id}/accounts',
                headers={'Authorization': f'Bearer {access_token}'},
                response_model=AccountListResponse,
            )

            if response.status_code != 200 or not response.data:
                logger.debug(f'Failed to fetch accounts: {response.status_code}')
                raise MurError(
                    code=507,
                    message='Failed to fetch user accounts',
                    detail=f'Server returned status code {response.status_code}',
                )

            # Extract account names from the list of Account objects
            account_names = [account.name for account in response.data]

            # Save account names to config
            self._save_user_accounts(account_names)

            logger.debug(f'Saved user accounts: {account_names}')
            return account_names

        except MurError:
            raise
        except Exception as e:
            logger.debug(f'Error fetching user accounts: {e}')
            raise MurError(code=507, message='Failed to fetch user accounts', original_error=e)

    def _save_user_accounts(self, account_names: list[str]) -> None:
        """Save user accounts to configuration.

        Args:
            account_names: List of account names to save
        """
        self.config_manager.config['user_accounts'] = account_names  # type: ignore
        self.config_manager.save_config()

        # Update local config
        self.config = self.config_manager.get_config()
