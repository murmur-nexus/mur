import configparser
import json
import logging
from pathlib import Path
from typing import Any

import requests
from requests.exceptions import RequestException

from ..core.auth import AuthenticationManager
from ..core.packaging import ArtifactManifest
from ..utils.constants import DEFAULT_MURMUR_INDEX_URL, MURMUR_SERVER_URL, MURMURRC_PATH
from ..utils.error_handler import MurError
from .base_adapter import RegistryAdapter

logger = logging.getLogger(__name__)


class PublicRegistryAdapter(RegistryAdapter):
    """Adapter for the public Murmur registry.

    This class handles interactions with the public Murmur registry, including authentication,
    artifact publishing, and package index management.

    Args:
        verbose (bool, optional): Enable verbose logging. Defaults to False.
    """

    def __init__(self, verbose: bool = False):
        super().__init__(verbose)
        self.base_url = MURMUR_SERVER_URL.rstrip('/')
        self.auth_manager = AuthenticationManager.create(verbose=verbose, base_url=self.base_url)

    def publish_artifact(
        self,
        manifest: ArtifactManifest,
    ) -> dict[str, Any]:
        """Publish an artifact to the registry.

        Args:
            manifest (ArtifactManifest): The artifact manifest containing metadata and file info

        Returns:
            dict[str, Any]: Server response containing artifact details.

        Raises:
            MurError: If connection fails or server returns an error.
        """
        url = f'{self.base_url}/artifacts'

        logger.debug(f'Publishing artifact: {manifest.to_dict()}')

        try:
            headers = self._get_headers()
            response = requests.post(url, headers=headers, json=manifest.to_dict(), timeout=60)

            if not response.ok:
                self._handle_error_response(response)

            return response.json()

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

    def _handle_error_response(self, response: requests.Response) -> None:
        """Handle error responses from the server.

        Args:
            response (requests.Response): Response object from the server.

        Raises:
            MurError: With appropriate error code and message based on the response.
        """
        # Parse error response
        try:
            error_data = response.json()
            detail = error_data.get('detail', '')
        except json.JSONDecodeError:
            detail = response.text

        # Handle specific error messages
        if 'Token has expired' in detail:
            raise MurError(
                code=504,
                message='Token has expired. Please log in again',
                detail='Please run `mur logout` and try again.',
            )
        if 'Could not validate credentials' in detail:
            raise MurError(502, 'Could not validate credentials')
        if 'The package or file already exists in the feed' in detail:
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
        error_code, error_message = STATUS_CODE_MAPPING.get(response.status_code, (800, 'Server error'))

        # Use provided detail if available
        if detail:
            error_message = detail

        raise MurError(error_code, error_message)

    def get_package_indexes(self) -> list[str]:
        """Get package indexes from .murmurrc configuration.

        Reads the primary index URL and any additional index URLs from the .murmurrc
        configuration file. Falls back to the default index if configuration cannot be read.

        Returns:
            list[str]: List of package index URLs with primary index first.
        """
        try:
            # Get index URLs from .murmurrc
            config = configparser.ConfigParser()
            config.read(MURMURRC_PATH)

            # Get primary index from config
            index_url = config.get('global', 'index-url', fallback=DEFAULT_MURMUR_INDEX_URL)
            indexes = [index_url]

            # Add extra index URLs from config if present
            if config.has_option('global', 'extra-index-url'):
                extra_urls = config.get('global', 'extra-index-url')
                indexes.extend(url.strip() for url in extra_urls.split('\n') if url.strip())

            return indexes

        except Exception as e:
            logger.warning(f'Failed to read .murmurrc config: {e}')
            # Fall back to just the primary index if config read fails
            return [f'{self.base_url}/simple/']
