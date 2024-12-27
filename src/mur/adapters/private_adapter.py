import configparser
import logging
from pathlib import Path
from typing import Any

from twine.commands.upload import upload
from twine.settings import Settings

from ..utils.constants import (
    MURMUR_EXTRAS_INDEX_URL,
    MURMUR_INDEX_URL,
    MURMURRC_PATH,
    PYPI_PASSWORD,
    PYPI_USERNAME,
)
from ..utils.error_handler import CodeError
from .base_adapter import RegistryAdapter

logger = logging.getLogger(__name__)


class PrivateRegistryAdapter(RegistryAdapter):
    """Adapter for private PyPI registry instances.

    This adapter handles publishing artifacts to and retrieving package indexes from
    private PyPI registries.

    Args:
        verbose (bool, optional): Enable verbose logging output. Defaults to False.
    """

    def __init__(self, verbose: bool = False):
        super().__init__(verbose)
        self.base_url = MURMUR_INDEX_URL

    def publish_artifact(
        self,
        artifact_type: str,
        name: str,
        version: str,
        description: str,
        metadata: dict[str, Any],
        file_path: Path | str,
    ) -> dict[str, Any]:
        """Publish an artifact to the private PyPI registry.

        Args:
            artifact_type (str): Type of the artifact being published.
            name (str): Name of the artifact.
            version (str): Version of the artifact.
            description (str): Description of the artifact.
            metadata (dict[str, Any]): Additional metadata for the artifact.
            file_path (Path | str): Path to the artifact file to publish.

        Returns:
            dict[str, Any]: Response containing status and message about the publish operation.

        Raises:
            CodeError: If artifact file is not found (201) or if publishing fails (200).
        """
        try:
            file_path = Path(file_path)
            if not file_path.exists():
                raise CodeError(201, f'Artifact file not found: {file_path}')

            # Remove /simple from the URL if present
            repository_url = self.base_url.rstrip('/').replace('/simple', '')

            settings = Settings(
                repository_url=repository_url,
                sign=False,
                verbose=self.verbose,
                repository_name='private',  # Required to identify the repository
                skip_existing=True,
                non_interactive=True,  # Skip authentication prompts
                username=PYPI_USERNAME,
                password=PYPI_PASSWORD,
            )

            if self.verbose:
                logger.info(f'Publishing {file_path} to private PyPI at {repository_url}')

            upload(upload_settings=settings, dists=[str(file_path)])

            return {'status': 'success', 'message': f'Published {file_path.name} to {repository_url}'}

        except Exception as e:
            raise CodeError(200, f'Failed to publish to private registry: {e!s}') from e

    def get_package_indexes(self) -> list[str]:
        """Get package indexes, prioritizing environment variables over .murmurrc config.

        The method first checks environment variables (MURMUR_INDEX_URL and MURMUR_EXTRAS_INDEX_URL)
        for package index URLs. If not found, falls back to reading from .murmurrc configuration file.

        Returns:
            list[str]: List of package index URLs with primary index first.

        Raises:
            CodeError: If no private registry URL is configured (807) or if reading configuration fails.
        """
        # Get URLs from environment variables
        index_url = MURMUR_INDEX_URL
        extra_indexes = []

        if MURMUR_EXTRAS_INDEX_URL:
            extra_indexes = [url.strip() for url in MURMUR_EXTRAS_INDEX_URL.split(',')]

        # If no environment variables, fall back to .murmurrc
        if not index_url:
            try:
                config = configparser.ConfigParser()
                config.read(MURMURRC_PATH)

                # Get primary index from config
                index_url = config.get('global', 'index-url', fallback=None)

                # If still no index URL, raise error
                if not index_url:
                    raise CodeError(
                        807,
                        'No private registry URL configured. Set MURMUR_INDEX_URL environment variable '
                        "or 'index-url' in .murmurrc [global] section.",
                    )

                # Get extra indexes from config if no env var extras
                if not extra_indexes and config.has_option('global', 'extra-index-url'):
                    extra_urls = config.get('global', 'extra-index-url')
                    extra_indexes.extend(url.strip() for url in extra_urls.split('\n') if url.strip())

            except Exception as e:
                if isinstance(e, CodeError):
                    raise
                logger.warning(f'Failed to read .murmurrc config: {e}')
                raise CodeError(
                    807,
                    'Failed to get private registry configuration. Ensure either MURMUR_INDEX_URL '
                    'environment variable is set or .murmurrc is properly configured.',
                )

        indexes = [index_url]
        indexes.extend(extra_indexes)

        return indexes
