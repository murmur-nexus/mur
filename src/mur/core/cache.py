import logging

import keyring
from keyring.errors import PasswordDeleteError

from mur.utils.error_handler import MurError

logger = logging.getLogger(__name__)


class CredentialCache:
    """Handles secure storage and retrieval of credentials.

    This class provides methods to securely store and retrieve credentials
    using the system keyring.
    """

    def __init__(self) -> None:
        """Initialize credential cache.

        The cache uses 'mur' as the service name for keyring operations.
        """
        self.service_name = 'mur'

    def save_credential(self, credential_type: str, value: str) -> None:
        """Save credential securely.

        Args:
            credential_type: Type of credential (e.g., 'access_token', 'password').
            value: The credential value to store.

        Raises:
            MurError: If saving the credential fails.
        """
        try:
            keyring.set_password(self.service_name, credential_type, value)
            logger.debug(f'Saved {credential_type} to keyring')
        except Exception as e:
            raise MurError(
                code=208,
                message=f'Failed to save {credential_type}',
                detail=f'Could not store {credential_type} in storage.',
                original_error=e,
            )

    def load_credential(self, credential_type: str) -> str | None:
        """Load credential from secure storage.

        Args:
            credential_type: Type of credential to load.

        Returns:
            The stored credential if found, None otherwise.

        Raises:
            MurError: If loading the credential fails.
        """
        try:
            value = keyring.get_password(self.service_name, credential_type)
            logger.debug(f'Retrieved {credential_type} from keyring')
            return value
        except Exception as e:
            raise MurError(
                code=208,
                message=f'Failed to load {credential_type}',
                detail=f'Could not retrieve {credential_type} from storage.',
                original_error=e,
            )

    def clear_credential(self, credential_type: str) -> None:
        """Clear stored credential.

        Args:
            credential_type: Type of credential to clear.

        Raises:
            MurError: If clearing the credential fails.
        """
        try:
            keyring.delete_password(self.service_name, credential_type)
            logger.debug(f'Cleared {credential_type} from keyring')
        except PasswordDeleteError:
            logger.debug(f'No {credential_type} to clear')
        except Exception as e:
            raise MurError(
                code=208,
                message=f'Failed to clear {credential_type}',
                detail=f'Could not remove {credential_type} from storage.',
                original_error=e,
            )
