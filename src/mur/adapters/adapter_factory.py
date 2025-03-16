import configparser
import logging
from pathlib import Path

from ..utils.constants import DEFAULT_MURMUR_INDEX_URL
from ..utils.error_handler import MurError
from .base_adapter import RegistryAdapter
from .private_adapter import PrivateRegistryAdapter
from .public_adapter import PublicRegistryAdapter

logger = logging.getLogger(__name__)


def get_index_url_from_config(murmurrc_path: Path, verbose: bool = False) -> str:
    """Get the index-url from the .murmurrc configuration file.

    Args:
        murmurrc_path: Path to the .murmurrc file
        verbose: Whether to enable verbose logging

    Returns:
        str: The index URL from the configuration or the default URL if not found

    Raises:
        MurError: If index-url is not found in the .murmurrc file
    """
    try:
        config = configparser.ConfigParser()
        config.read(murmurrc_path)

        if not config.has_section('murmur-nexus') or not config.has_option('murmur-nexus', 'index-url'):
            raise MurError(
                code=213,
                message='Missing registry configuration',
                detail="No 'index-url' found in .murmurrc under [murmur-nexus] section.",
            )

        index_url = config.get('murmur-nexus', 'index-url')

        # Validate URL format
        if not index_url.startswith('http'):
            raise MurError(
                code=213, message='Invalid registry URL', detail="Registry URL must start with 'http' or 'https'"
            )

        return index_url

    except Exception as e:
        if not isinstance(e, MurError):
            raise MurError(
                code=213,
                message='Failed to read registry settings',
                detail=f'Error reading registry configuration: {e!s}',
                original_error=e,
            )
        raise


def verify_registry_settings(murmurrc_path: Path, verbose: bool = False) -> bool:
    """Verify registry settings in the .murmurrc file.

    Checks if the index-url in the .murmurrc file is different from the default,
    which indicates a private registry is being used.

    Args:
        murmurrc_path: Path to the .murmurrc file
        verbose: Whether to enable verbose logging

    Returns:
        bool: True if a private registry is configured, False otherwise
    """
    try:
        index_url = get_index_url_from_config(murmurrc_path, verbose)

        # Return False if it matches default URL
        if index_url == DEFAULT_MURMUR_INDEX_URL:
            return False

        return True

    except MurError:
        raise
    except Exception as e:
        raise MurError(
            code=213,
            message='Failed to verify registry settings',
            detail=f'Error verifying registry configuration: {e!s}',
            original_error=e,
        )


def get_registry_adapter(murmurrc_path: Path, command_name: str, verbose: bool = False) -> RegistryAdapter:
    """Get the appropriate registry adapter based on environment.

    Determines whether to use a public or private registry adapter based on
    the configuration in .murmurrc file.

    Args:
        murmurrc_path: Path to the .murmurrc file
        command_name: Name of the command being executed, used for logging control
        verbose: Whether to enable verbose logging. Defaults to False.

    Returns:
        RegistryAdapter: Registry adapter instance:
            - PrivateRegistryAdapter: If a private registry is configured
            - PublicRegistryAdapter: If using the default public registry
    """
    # Check if it's a private registry based on the murmurrc file
    use_private = verify_registry_settings(murmurrc_path, verbose)
    index_url = get_index_url_from_config(murmurrc_path, verbose)

    omit_logging_commands = ['config']

    if use_private:
        if command_name not in omit_logging_commands:
            logger.info('Using private PyPI server')
        return PrivateRegistryAdapter(verbose, index_url)

    if command_name not in omit_logging_commands:
        logger.info('Using public Murmur Nexus registry')
    return PublicRegistryAdapter(verbose, index_url)
