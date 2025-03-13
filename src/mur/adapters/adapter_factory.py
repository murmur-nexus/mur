import logging
import configparser
from pathlib import Path

from ..utils.constants import DEFAULT_MURMUR_INDEX_URL, GLOBAL_MURMURRC_PATH
from .base_adapter import RegistryAdapter
from .private_adapter import PrivateRegistryAdapter
from .public_adapter import PublicRegistryAdapter
from ..utils.error_handler import MurError

logger = logging.getLogger(__name__)


def verify_registry_settings(murmurrc_path: Path, verbose: bool = False) -> bool:
    """Verify registry settings in the .murmurrc file.
    
    Checks if the index-url in the .murmurrc file is different from the default,
    which indicates a private registry is being used.
    
    Args:
        murmurrc_path: Path to the .murmurrc file
        verbose: Whether to enable verbose logging
        
    Returns:
        bool: True if a private registry is configured, False otherwise
        
    Raises:
        MurError: If index-url is not found in the .murmurrc file
    """
    try:
        config = configparser.ConfigParser()
        config.read(murmurrc_path)
        
        if not config.has_section('murmur-nexus') or not config.has_option('murmur-nexus', 'index-url'):
            raise MurError(
                code=213,
                message="Missing registry configuration",
                detail="No 'index-url' found in .murmurrc under [murmur-nexus] section."
            )
        
        index_url = config.get('murmur-nexus', 'index-url')
        # If index_url is different from default, it's a private registry
        if verbose:
            logger.info(f"Using registry at {index_url}")
        return index_url != DEFAULT_MURMUR_INDEX_URL
        
    except Exception as e:
        if not isinstance(e, MurError):
            raise MurError(
                code=213,
                message="Failed to verify registry settings",
                detail=f"Error reading registry configuration: {str(e)}",
                original_error=e
            )
        raise


def get_registry_adapter(murmurrc_path: Path, verbose: bool = False) -> RegistryAdapter:
    """Get the appropriate registry adapter based on environment.

    Determines whether to use a public or private registry adapter based on
    the configuration in .murmurrc file.

    Args:
        verbose (bool, optional): Whether to enable verbose logging. Defaults to False.

    Returns:
        RegistryAdapter: Registry adapter instance:
            - PrivateRegistryAdapter: If a private registry is configured
            - PublicRegistryAdapter: If using the default public registry
    """
    # Check if it's a private registry based on the murmurrc file
    use_private = verify_registry_settings(murmurrc_path, verbose)
    
    if use_private:
        logger.info('Using private PyPI server')
        return PrivateRegistryAdapter(verbose)

    logger.info('Using public Murmur Nexus registry')
    return PublicRegistryAdapter(verbose)
