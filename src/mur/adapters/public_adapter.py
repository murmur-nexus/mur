import configparser
import json
import logging
from pathlib import Path
from typing import Any

import requests
from requests.exceptions import RequestException

from ..core.auth import AuthenticationError, AuthenticationManager
from ..utils.constants import DEFAULT_MURMUR_INDEX_URL, MURMUR_SERVER_URL, MURMURRC_PATH
from ..utils.error_handler import CodeError
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

    def get_headers(self) -> dict[str, str]:
        """Get authentication headers for API requests.

        Returns:
            dict[str, str]: Headers dictionary containing Bearer token.

        Raises:
            CodeError: If authentication fails.
        """
        try:
            access_token = self.auth_manager.authenticate()
            return {'Authorization': f'Bearer {access_token}'}
        except AuthenticationError as e:
            raise CodeError(501, f'Authentication failed: {e}')

    def publish_artifact(
        self,
        artifact_type: str,
        name: str,
        version: str,
        description: str,
        metadata: dict[str, Any],
        file_path: Path | str,
    ) -> dict[str, Any]:
        """Publish an artifact to the registry.

        Args:
            artifact_type (str): Type of the artifact.
            name (str): Name of the artifact.
            version (str): Version of the artifact.
            description (str): Description of the artifact.
            metadata (dict[str, Any]): Additional metadata for the artifact.
            file_path (Path | str): Path to the artifact file.

        Returns:
            dict[str, Any]: Server response containing artifact details.

        Raises:
            CodeError: If file not found, connection fails, or server returns an error.
        """
        url = f'{self.base_url}/artifacts/'
        file_path = Path(file_path)

        if not file_path.exists():
            raise CodeError(201, f'Artifact file not found: {file_path}')

        data = {
            'name': name,
            'type': artifact_type,
            'version': version,
            'description': description,
            'metadata': json.dumps(metadata),
        }

        try:
            headers = self.get_headers()
            with open(file_path, 'rb') as f:
                response = requests.post(url, headers=headers, data=data, files={'file': f}, timeout=60)

            if not response.ok:
                self._handle_error_response(response)

            return response.json()

        except RequestException as e:
            if 'Connection refused' in str(e):
                raise CodeError(
                    804, f'Failed to connect to server: Connection refused. Is the server running at {self.base_url}?'
                )
            raise CodeError(200, str(e))

    def _handle_error_response(self, response: requests.Response) -> None:
        """Handle error responses from the server.

        Args:
            response (requests.Response): Response object from the server.

        Raises:
            CodeError: With appropriate error code and message based on the response.
        """
        try:
            error_data = response.json()
        except json.JSONDecodeError:
            error_data = {}

        detail = error_data.get('detail', '')

        if response.status_code == 400 and detail == 'Conflict error: The package or file already exists in the feed.':
            raise CodeError(302, 'Package with version already exists')

        error_mapping = {
            800: (300, detail if detail else 'Bad request'),
            804: (502 if detail == 'Could not validate credentials' else 300, detail if detail else 'Unauthorized'),
            807: (502, 'Permission denied'),
            502: (801, 'Resource not found'),
        }

        error_code, error_message = error_mapping.get(response.status_code, (800, 'Server error'))

        raise CodeError(error_code, error_message)

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
