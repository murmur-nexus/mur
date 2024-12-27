import logging

from ..utils.constants import MURMUR_INDEX_URL
from .base_adapter import RegistryAdapter
from .private_adapter import PrivateRegistryAdapter
from .public_adapter import PublicRegistryAdapter

logger = logging.getLogger(__name__)


def get_registry_adapter(verbose: bool = False) -> RegistryAdapter:
    """Get the appropriate registry adapter based on environment.

    Determines whether to use a public or private registry adapter based on
    the MURMUR_INDEX_URL environment variable.

    Args:
        verbose (bool, optional): Whether to enable verbose logging. Defaults to False.

    Returns:
        RegistryAdapter: Registry adapter instance:
            - PrivateRegistryAdapter: If MURMUR_INDEX_URL is set
            - PublicRegistryAdapter: If MURMUR_INDEX_URL is not set
    """
    if MURMUR_INDEX_URL:
        logger.info(f'Using private PyPI server at {MURMUR_INDEX_URL}')
        return PrivateRegistryAdapter(verbose)

    logger.info('Using public Murmur Nexus registry')
    return PublicRegistryAdapter(verbose)
