import configparser
import logging
from pathlib import Path
from typing import Any

from twine.commands.upload import upload
from twine.settings import Settings

from mur.core.packaging import ArtifactManifest

from ..utils.constants import (
    GLOBAL_MURMURRC_PATH,
    PYPI_PASSWORD,
    PYPI_USERNAME,
)
from ..utils.error_handler import MurError
from .base_adapter import RegistryAdapter

logger = logging.getLogger(__name__)


class PrivateRegistryAdapter(RegistryAdapter):
    """Adapter for private PyPI registry instances.

    This adapter handles publishing artifacts to and retrieving package indexes from
    private PyPI registries.

    Args:
        verbose (bool, optional): Enable verbose logging output. Defaults to False.
    """

    def __init__(self, verbose: bool = False, index_url: str | None = None):
        """Initialize the private registry adapter.

        Args:
            verbose (bool, optional): Enable verbose logging output. Defaults to False.
            index_url (str | None, optional): URL of the private PyPI registry. Defaults to None.
        """
        super().__init__(verbose, index_url)

    def publish_artifact(
        self,
        manifest: ArtifactManifest,
        scope: str | None = None,  # Intentionally ignored for private registry
    ) -> dict[str, Any]:
        """Publish an artifact to the private PyPI registry.

        Args:
            manifest (ArtifactManifest): The artifact manifest containing metadata and file info
            scope (str | None, optional): Scope parameter is ignored for private registry. Defaults to None.

        Returns:
            dict[str, Any]: Response containing status and message about the publish operation.

        Raises:
            MurError: If artifact file is not found (201) or if publishing fails (200).
        """
        try:
            logger.debug(f'Publishing artifact: {manifest.to_dict()}')

            # Check if index_url is None before using string methods
            if self.index_url is None:
                raise MurError(213, 'No private registry URL configured')

            repository_url = self.index_url.rstrip('/').replace('/simple', '')
            response = {
                'status': 'pending',
                'message': 'Ready for file upload',
                'signed_upload_urls': [
                    {'file_type': 'wheel', 'signed_url': repository_url},
                    {'file_type': 'source', 'signed_url': repository_url},
                ],
            }

            return response

        except Exception as e:
            if isinstance(e, MurError):
                raise
            raise MurError(600, f'Failed to publish to private registry: {e!s}') from e

    def upload_file(self, file_path: Path, signed_url: str) -> None:
        """Upload a file to the registry using a URL.

        Args:
            file_path (Path): The path to the file to upload.
            signed_url (str): The URL to use for uploading the file.

        Raises:
            MurError: If the file upload fails or the file doesn't exist.
        """
        if not file_path.exists():
            raise MurError(201, f'File not found: {file_path}')

        try:
            settings = Settings(
                repository_url=signed_url,
                sign=False,
                verbose=self.verbose,
                repository_name='private',  # Required to identify the repository
                skip_existing=True,
                non_interactive=True,  # Skip authentication prompts
                username=PYPI_USERNAME,
                password=PYPI_PASSWORD,
            )

            if self.verbose:
                logger.info(f'Uploading {file_path} to private PyPI at {signed_url}')

            upload(upload_settings=settings, dists=[str(file_path)])

        except Exception as e:
            raise MurError(200, f'Upload failed: {e!s}')

    def get_package_indexes(self) -> list[str]:
        """Get package indexes from .murmurrc configuration file.

        Reads package index URLs from the .murmurrc configuration file, looking first
        for a local file in the current directory, then falling back to the global config.

        Returns:
            list[str]: List of package index URLs with primary index first.

        Raises:
            MurError: If no private registry URL is configured (807) or if reading configuration fails.
        """
        try:
            # Get the path to the .murmurrc file
            local_murmurrc = Path.cwd() / '.murmurrc'
            murmurrc_path = local_murmurrc if local_murmurrc.exists() else GLOBAL_MURMURRC_PATH

            config = configparser.ConfigParser()
            config.read(murmurrc_path)

            # Add extra index URLs from config if present
            extra_indexes: list[str] = []
            if config.has_option('murmur-nexus', 'extra-index-url'):
                extra_urls = config.get('murmur-nexus', 'extra-index-url')
                extra_indexes.extend(url.strip() for url in extra_urls.split('\n') if url.strip())

            # Ensure index_url is not None before adding it to the list
            if self.index_url is None:
                raise MurError(807, 'No private registry URL configured')

            indexes = [self.index_url]
            indexes.extend(extra_indexes)

            return indexes

        except Exception as e:
            if isinstance(e, MurError):
                raise
            logger.warning(f'Failed to read .murmurrc config: {e}')
            raise MurError(
                code=213,
                message='Failed to get private registry configuration',
                detail='Ensure .murmurrc is properly configured with [murmur-nexus] section and index-url.',
            )
