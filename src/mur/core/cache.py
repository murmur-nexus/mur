import logging

import keyring
from keyring.errors import PasswordDeleteError

from mur.utils.error_handler import MurError

logger = logging.getLogger(__name__)


class CredentialCache:
    """Handles secure storage and retrieval of credentials.

    This class provides methods to securely store and retrieve access tokens
    and passwords using the system keyring.
    """

    def __init__(self) -> None:
        """Initialize credential cache.

        The cache uses 'mur' as the service name for keyring operations.
        """
        self.service_name = 'mur'

    def save_access_token(self, access_token: str) -> None:
        """Save access token securely.

        Args:
            access_token: The access token string to store.

        Raises:
            MurError: If saving the access token fails.
        """
        try:
            keyring.set_password(self.service_name, 'access_token', access_token)
            logger.debug('Saved access token to keyring')
        except Exception as e:
            raise MurError(
                code=208,
                message='Failed to save access token',
                detail='Could not store access token in storage.',
                original_error=e,
            )

    def load_access_token(self) -> str | None:
        """Load access token from secure storage.

        Returns:
            The stored access token if found, None otherwise.

        Raises:
            MurError: If loading the access token fails.
        """
        try:
            token = keyring.get_password(self.service_name, 'access_token')
            logger.debug('Retrieved access token from keyring')
            return token
        except Exception as e:
            raise MurError(
                code=208,
                message='Failed to load access token',
                detail='Could not retrieve access token from storage.',
                original_error=e,
            )

    def clear_access_token(self) -> None:
        """Clear stored access token.

        Raises:
            MurError: If clearing the access token fails.
        """
        try:
            keyring.delete_password(self.service_name, 'access_token')
            logger.debug('Cleared access token from keyring')
        except PasswordDeleteError:
            logger.debug('No access token to clear')
        except Exception as e:
            raise MurError(
                code=208,
                message='Failed to clear access token',
                detail='Could not remove access token from storage.',
                original_error=e,
            )

    def save_password(self, password: str) -> None:
        """Save password securely.

        Args:
            password: The password string to store.

        Raises:
            MurError: If saving the password fails.
        """
        try:
            keyring.set_password(self.service_name, 'password', password)
            logger.debug('Saved password to keyring')
        except Exception as e:
            raise MurError(
                code=208,
                message='Failed to save password',
                detail='Could not store password in storage.',
                original_error=e,
            )

    def load_password(self) -> str | None:
        """Load password from secure storage.

        Returns:
            The stored password if found, None otherwise.

        Raises:
            MurError: If loading the password fails.
        """
        try:
            password = keyring.get_password(self.service_name, 'password')
            logger.debug('Retrieved password from keyring')
            return password
        except Exception as e:
            raise MurError(
                code=208,
                message='Failed to load password',
                detail='Could not retrieve password from storage.',
                original_error=e,
            )

    def clear_password(self) -> None:
        """Clear stored password.

        Raises:
            MurError: If clearing the password fails.
        """
        try:
            keyring.delete_password(self.service_name, 'password')
            logger.debug('Cleared password from keyring')
        except PasswordDeleteError:
            logger.debug('No password to clear')
        except Exception as e:
            raise MurError(
                code=208,
                message='Failed to clear password',
                detail='Could not remove password from storage.',
                original_error=e,
            )
