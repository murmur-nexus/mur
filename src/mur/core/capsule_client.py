import logging
from pathlib import Path
from typing import Any, Optional, Union

import requests
from pydantic import BaseModel, Field

from ..utils.constants import DEFAULT_TIMEOUT
from ..utils.error_handler import MurError
from .api_client import ApiClient, ApiResponse

logger = logging.getLogger(__name__)


class ToolInstallRequest(BaseModel):
    """Request model for tool installation.

    Attributes:
        tool_name: Name of the tool to install
        artifact_url: URL to the tool artifact (e.g., distribution file)
        metadata: Additional metadata for the tool
    """

    # tool_name: str
    artifact_url: str
    # metadata: Dict[str, Any] = Field(default_factory=dict)


class ToolUninstallRequest(BaseModel):
    """Request model for tool uninstallation.

    Attributes:
        tool_name: Name of the tool to uninstall
    """

    tool_name: str


class ToolCallRequest(BaseModel):
    """Request model for tool execution.

    Attributes:
        tool_name: Name of the tool to call
        args: Positional arguments to pass to the tool
        kwargs: Keyword arguments to pass to the tool
    """

    tool_name: str
    args: list[Any] = Field(default_factory=list)
    kwargs: dict[str, Any] = Field(default_factory=dict)


class ToolResponse(BaseModel):
    """Response model for tool operations.

    Attributes:
        status: Status of the operation
        result: Result of the operation, if successful
        error: Error message, if operation failed
    """

    status: str
    result: Optional[Any] = None
    error: Optional[str] = None


class CapsuleClient:
    """Client for interacting with capsule operations.

    This client provides methods for installing, uninstalling, and calling tools
    through the Murmur API.

    Attributes:
        api_client: Underlying API client for making HTTP requests
        base_url: Base URL for the Murmur API
    """

    def __init__(self, base_url: str, api_client: Optional[ApiClient] = None, verbose: bool = False) -> None:
        """Initialize the capsule client.

        Args:
            base_url: Base URL for the Murmur API
            api_client: Optional existing API client to use
            verbose: Whether to enable verbose logging

        Raises:
            MurError: If initialization fails
        """
        self.api_client = api_client or ApiClient(base_url=base_url, verbose=verbose)
        self.base_url = base_url
        self.verbose = verbose

    def install_tool(
        self,
        tool_name: Optional[str] = None,
        artifact_url: Optional[str] = None,
        package_path: Optional[Union[str, Path]] = None,
    ) -> ApiResponse[ToolResponse]:
        """Install a tool from a distribution file or artifact URL.

        Args:
            tool_name: Name of the tool to install (when using artifact_url)
            artifact_url: URL to the artifact package
            package_path: Path to the distribution file to install

        Returns:
            ApiResponse: Standardized response with tool installation result

        Raises:
            MurError: If the installation fails
        """
        # If package_path is provided, use push approach
        if package_path:
            return self._install_tool_from_path(package_path)
        # If artifact_url is provided, use pull approach
        elif artifact_url:
            return self._install_tool_from_url(artifact_url, tool_name)
        else:
            raise MurError(
                code=401,
                message='Missing installation source',
                detail='Either package_path or artifact_url must be provided',
            )

    def _install_tool_from_path(self, package_path: Union[str, Path]) -> ApiResponse[ToolResponse]:
        """Install a tool by uploading a local package file (push approach).

        Args:
            package_path: Path to the distribution file to install

        Returns:
            ApiResponse: Standardized response with tool installation result

        Raises:
            MurError: If the installation fails
        """
        package_path = Path(package_path)
        if not package_path.exists():
            raise MurError(
                code=201,
                message=f'Artifact file not found: {package_path}',
                detail='The specified distribution file does not exist',
            )

        try:
            url = f'{self.base_url}/api/tools/install'

            with open(package_path, 'rb') as f:
                files = {'file': (package_path.name, f)}
                response = requests.post(url, files=files, timeout=DEFAULT_TIMEOUT)

            # Process the response similar to ApiClient
            if response.status_code == 200 and response.content:
                try:
                    response_json = response.json()
                    parsed_data = ToolResponse(**response_json)
                    return ApiResponse(
                        status_code=response.status_code, data=parsed_data, raw_data=response_json, error=None
                    )
                except Exception as e:
                    logger.debug(f'Failed to parse response data: {e}')
                    return ApiResponse(
                        status_code=response.status_code,
                        raw_data={} if not response.content else response.json(),
                        error=f'Failed to parse response: {e}',
                    )
            else:
                return ApiResponse(
                    status_code=response.status_code,
                    raw_data={} if not response.content else response.json(),
                    error=response.text if response.status_code >= 400 else None,
                )

        except Exception as e:
            logger.debug(f'Install tool request error: {e}')
            raise MurError(
                code=600,
                message='Tool installation failed',
                detail=f'Failed to upload distribution file: {e}',
                original_error=e,
            )

    def _install_tool_from_url(self, artifact_url: str, tool_name: Optional[str] = None) -> ApiResponse[ToolResponse]:
        """Install a tool from a remote artifact URL (pull approach).

        Args:
            artifact_url: URL to the artifact package
            tool_name: Optional name of the tool to install

        Returns:
            ApiResponse: Standardized response with tool installation result

        Raises:
            MurError: If the installation fails
        """
        payload = ToolInstallRequest(artifact_url=artifact_url)
        return self.api_client.post(endpoint='/api/tools/install', payload=payload, response_model=ToolResponse)

    def uninstall_tool(self, tool_name: str) -> ApiResponse[ToolResponse]:
        """Uninstall a tool.

        Args:
            tool_name: Name of the tool to uninstall

        Returns:
            ApiResponse: Standardized response with tool uninstallation result

        Raises:
            MurError: If the uninstallation fails
        """
        payload = ToolUninstallRequest(tool_name=tool_name)
        return self.api_client.post(endpoint='/api/tools/uninstall', payload=payload, response_model=ToolResponse)

    def call_tool(
        self, tool_name: str, args: Optional[list[Any]] = None, kwargs: Optional[dict[str, Any]] = None
    ) -> ApiResponse[ToolResponse]:
        """Call a tool with arguments.

        Args:
            tool_name: Name of the tool to call
            args: Positional arguments to pass to the tool
            kwargs: Keyword arguments to pass to the tool

        Returns:
            ApiResponse: Standardized response with tool execution result

        Raises:
            MurError: If the tool call fails
        """
        payload = ToolCallRequest(tool_name=tool_name, args=args or [], kwargs=kwargs or {})
        return self.api_client.post(endpoint='/api/tools/call', payload=payload, response_model=ToolResponse)

    def list_tools(self) -> ApiResponse[ToolResponse]:
        """List all installed tools on the host.

        Returns:
            ApiResponse: Standardized response with the list of installed tools

        Raises:
            MurError: If the list request fails
        """
        try:
            return self.api_client.get(endpoint='/api/tools/list', response_model=ToolResponse)
        except MurError as e:
            logger.debug(f'List tools request error: {e}')
            raise MurError(
                code=610,
                message='Failed to list tools',
                detail=f'Error occurred while requesting tools list: {e}',
                original_error=e.context.original_error,
            )
        except Exception as e:
            logger.debug(f'List tools request error: {e}')
            raise MurError(
                code=610,
                message='Failed to list tools',
                detail=f'Error occurred while requesting tools list: {e!s}',
                original_error=e,
            )
