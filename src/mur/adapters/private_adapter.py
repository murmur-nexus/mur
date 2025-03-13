import configparser
import logging
from pathlib import Path
from typing import Any

from twine.commands.upload import upload
from twine.settings import Settings

from mur.core.packaging import ArtifactManifest

from ..utils.constants import (
    MURMUR_INDEX_URL,
    PYPI_PASSWORD,
    PYPI_USERNAME,
    GLOBAL_MURMURRC_PATH,
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

    def __init__(self, verbose: bool = False):
        super().__init__(verbose)
        self.base_url = MURMUR_INDEX_URL
        self.is_private_registry = True

    def publish_artifact(
        self,
        manifest: ArtifactManifest,
    ) -> dict[str, Any]:
        """Publish an artifact to the private PyPI registry.

        Args:
            manifest (ArtifactManifest): The artifact manifest containing metadata and file info

        Returns:
            dict[str, Any]: Response containing status and message about the publish operation.

        Raises:
            MurError: If artifact file is not found (201) or if publishing fails (200).
        """
        try:
            logger.debug(f'Publishing artifact: {manifest.to_dict()}')

            repository_url = self.base_url.rstrip('/').replace('/simple', '')
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
            raise MurError(200, f'Failed to publish to private registry: {e!s}') from e

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

            # Get primary index from config
            index_url = config.get('murmur-nexus', 'index-url', fallback=None)

            # If no index URL, raise error
            if not index_url:
                raise MurError(
                    code=807,
                    message='No private registry URL configured',
                    detail="Set 'index-url' in .murmurrc [murmur-nexus] section.",
                )

            # Get extra indexes from config
            extra_indexes = []
            if config.has_option('murmur-nexus', 'extra-index-url'):
                extra_urls = config.get('murmur-nexus', 'extra-index-url')
                extra_indexes.extend(url.strip() for url in extra_urls.split('\n') if url.strip())

            indexes = [index_url]
            indexes.extend(extra_indexes)

            return indexes

        except Exception as e:
            if isinstance(e, MurError):
                raise
            logger.warning(f'Failed to read .murmurrc config: {e}')
            raise MurError(
                code=807,
                message='Failed to get private registry configuration',
                detail='Ensure .murmurrc is properly configured with [murmur-nexus] section and index-url.',
            )
