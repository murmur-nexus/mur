import configparser
import logging
from pathlib import Path
from typing import Any

import requests
from requests.exceptions import RequestException

from ..core.api_client import ApiClient
from ..core.auth import AuthenticationManager
from ..core.packaging import ArtifactManifest
from ..utils.constants import GLOBAL_MURMURRC_PATH
from ..utils.error_handler import MurError
from ..utils.models import ArtifactPublishRequest, ArtifactPublishResponse
from .base_adapter import RegistryAdapter

logger = logging.getLogger(__name__)


class PublicRegistryAdapter(RegistryAdapter):
    """Adapter for the public Murmur registry.

    This class handles interactions with the public Murmur registry, including authentication,
    artifact publishing, and package index management.

    Args:
        verbose (bool, optional): Enable verbose logging. Defaults to False.
        index_url (str | None, optional): The index URL to use for publishing. Defaults to None.
    """

    def __init__(self, verbose: bool = False, index_url: str | None = None):
        super().__init__(verbose, index_url)
        self.auth_manager = AuthenticationManager.create(verbose=verbose)
        self.api_client = ApiClient(verbose=verbose)
        self.base_url = self.api_client.base_url

    def publish_artifact(
        self,
        manifest: ArtifactManifest,
        scope: str | None = None,
    ) -> dict[str, Any]:
        """Publish an artifact to the registry.

        Args:
            manifest (ArtifactManifest): The artifact manifest containing metadata and file info
            scope (str | None, optional): The scope to publish the artifact under. Defaults to None.

        Returns:
            dict[str, Any]: Server response containing artifact details.

        Raises:
            MurError: If connection fails or server returns an error.
        """
        logger.debug(f'Publishing artifact: {manifest.to_dict()}')

        try:
            # Create request payload from manifest
            payload = ArtifactPublishRequest.from_manifest(manifest)

            # Add scope to payload if provided
            if scope:
                payload.name = f'{scope}-{payload.name}'
            else:
                raise MurError(502, 'Scope is required for public registry')

            if self.verbose:
                logger.debug(f'Publishing payload: {payload.model_dump(exclude_none=True)}')

            # Get authentication headers
            headers = self._get_headers()

            # Make API request
            response = self.api_client.post(
                endpoint='/artifacts', payload=payload, response_model=ArtifactPublishResponse, headers=headers
            )

            if response.status_code != 200:
                self._handle_error_response(response.status_code, response.error or 'Unknown error')

            return response.raw_data

        except RequestException as e:
            if 'Connection refused' in str(e):
                raise MurError(
                    code=804,
                    message='Failed to connect to server',
                    detail=f'Connection refused. Is the server running at {self.base_url}?',
                    original_error=e,
                )
            elif 'Failed to resolve' in str(e) or 'nodename nor servname provided' in str(e):
                raise MurError(
                    code=804,
                    message='Failed to resolve server hostname',
                    detail=f'{self.base_url}. Please check your network connection and DNS settings.',
                    original_error=e,
                )
            raise MurError(803, f'Connection error: {e!s}')

    def upload_file(self, file_path: Path, signed_url: str) -> None:
        """Upload a file to the registry using a signed URL.

        Args:
            file_path (Path): The path to the file to upload.
            signed_url (str): The signed URL to use for uploading the file.

        Raises:
            MurError: If the file upload fails or the file doesn't exist.
        """
        if not file_path.exists():
            raise MurError(201, f'File not found: {file_path}')

        try:
            from tqdm import tqdm

            file_size = file_path.stat().st_size

            with open(file_path, 'rb') as f:
                with tqdm(total=file_size, unit='B', unit_scale=True, desc=f'Uploading {file_path.name}') as pbar:
                    data = f.read()
                    pbar.update(file_size)

                    response = requests.put(
                        signed_url, data=data, headers={'Content-Type': 'application/octet-stream'}, timeout=300
                    )

            if not response.ok:
                raise MurError(800, f'Failed to upload file: {response.text}')

        except RequestException as e:
            raise MurError(200, f'Upload failed: {e!s}')

    def _get_headers(self) -> dict[str, str]:
        """Get authentication headers for API requests.

        Returns:
            dict[str, str]: Headers dictionary containing Bearer token.

        Raises:
            MurError: If authentication fails.
        """
        try:
            access_token = self.auth_manager.authenticate()
            return {'Authorization': f'Bearer {access_token}'}
        except MurError:
            raise

    def _handle_error_response(self, status_code: int, error_message: str) -> None:
        """Handle error responses from the server.

        Args:
            status_code (int): HTTP status code from the response
            error_message (str): Error message from the response

        Raises:
            MurError: With appropriate error code and message based on the response.
        """
        # Handle specific error messages
        if 'Token has expired' in error_message:
            raise MurError(
                code=504,
                message='Token has expired. Please log in again',
                detail='Please run `mur logout` and try again.',
            )
        if 'Could not validate credentials' in error_message:
            raise MurError(502, 'Could not validate credentials')
        if 'The package or file already exists in the feed' in error_message:
            raise MurError(302, 'Package with version already exists')

        # Map standard HTTP status codes
        STATUS_CODE_MAPPING = {
            400: (600, 'Bad request'),
            401: (502, 'Unauthorized'),
            403: (505, 'Permission denied'),
            404: (600, 'Resource not found'),
            500: (600, 'Server error'),
            502: (806, 'Bad gateway'),
            503: (804, 'Service unavailable'),
        }

        # Get error code and message, with fallback to generic server error
        error_code, default_message = STATUS_CODE_MAPPING.get(status_code, (800, 'Server error'))

        # Use provided detail if available
        error_detail = error_message if error_message else default_message

        raise MurError(error_code, error_detail)

    def get_package_indexes(self) -> list[str]:
        """Get package indexes from .murmurrc configuration.

        Reads the primary index URL and any additional index URLs from the .murmurrc
        configuration file. Falls back to the default index if configuration cannot be read.

        Returns:
            list[str]: List of package index URLs with primary index first.
        """
        try:
            # Get the path to the .murmurrc file
            local_murmurrc = Path.cwd() / '.murmurrc'
            murmurrc_path = local_murmurrc if local_murmurrc.exists() else GLOBAL_MURMURRC_PATH

            config = configparser.ConfigParser()
            config.read(murmurrc_path)
            extra_indexes: list[str] = []

            # Add extra index URLs from config if present
            if config.has_option('murmur-nexus', 'extra-index-url'):
                extra_urls = config.get('murmur-nexus', 'extra-index-url')
                extra_indexes.extend(url.strip() for url in extra_urls.split('\n') if url.strip())

            # Ensure index_url is a string before adding to indexes
            primary_index = self.index_url if self.index_url is not None else ''
            indexes = [primary_index]
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
