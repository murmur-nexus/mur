import logging
from typing import Any, Generic, Optional, TypeVar, Union

import requests
from pydantic import BaseModel

from ..utils.constants import DEFAULT_TIMEOUT, MURMUR_SERVER_URL
from ..utils.error_handler import MurError

logger = logging.getLogger(__name__)

T = TypeVar('T', bound=Any)  # Changed from BaseModel to Any to support List[Model]


class ApiResponse(BaseModel, Generic[T]):
    """Model for standardized API responses.

    Generic type parameter T represents the expected data model for successful responses.
    """

    status_code: int
    data: Optional[T] = None
    raw_data: Union[dict[str, Any], list[dict[str, Any]]] = {}  # Updated to accept both dict and list
    error: Optional[str] = None


class ApiClient:
    """Client for making API calls to the Murmur server.

    This class handles all HTTP communication with the Murmur server,
    providing a consistent interface for API requests.

    Attributes:
        base_url (str): Base URL for the Murmur API
        verbose (bool): Flag for enabling verbose logging
    """

    def __init__(self, base_url: str = MURMUR_SERVER_URL.rstrip('/'), verbose: bool = False) -> None:
        """Initialize the API client.

        Args:
            base_url: Base URL for the Murmur API
            verbose: Whether to enable verbose logging

        Raises:
            MurError: If initialization fails
        """
        self.base_url = base_url
        self.verbose = verbose

        if verbose:
            logger.setLevel(logging.DEBUG)

    def request(
        self,
        method: str,
        endpoint: str,
        payload: Optional[BaseModel] = None,
        response_model: Optional[type[T]] = None,
        query_params: Optional[dict[str, Any]] = None,
        headers: Optional[dict[str, str]] = None,
        content_type: str = 'application/json',
    ) -> ApiResponse[T]:
        """Make an HTTP request to the API.

        Args:
            method: HTTP method (GET, POST, PUT, DELETE, etc.)
            endpoint: API endpoint path (without base URL)
            payload: Optional request payload as a Pydantic model
            response_model: Expected response data model
            query_params: Optional query parameters
            headers: Optional request headers
            content_type: Content type for the request

        Returns:
            ApiResponse: Standardized response with typed data

        Raises:
            MurError: If the API request fails
        """
        try:
            url = f'{self.base_url}/{endpoint.lstrip("/")}'
            request_headers = self._prepare_headers(headers, content_type)
            verify_ssl = self.base_url.startswith('https://')
            data, json_data = self._prepare_request_data(payload, content_type)

            if self.verbose:
                logger.debug(f'{method.upper()} request to {endpoint}')

            response = requests.request(
                method=method.lower(),
                url=url,
                params=query_params,
                headers=request_headers,
                data=data,
                json=json_data,
                timeout=DEFAULT_TIMEOUT,
                verify=verify_ssl,
            )

            if self.verbose:
                logger.debug(f'{method.upper()} {endpoint} response status: {response.status_code}')

            return self._process_response(response, response_model)

        except Exception as e:
            logger.debug(f'API request error: {e}')
            raise MurError(
                code=600,
                message=f'API request to {endpoint} failed',
                detail='Failed to communicate with server',
                original_error=e,
            )

    def _prepare_headers(self, headers: Optional[dict[str, str]], content_type: str) -> dict[str, str]:
        """Prepare request headers.

        Args:
            headers: Optional custom headers
            content_type: Content type for the request

        Returns:
            dict: Combined headers
        """
        request_headers = {'Content-Type': content_type}
        if headers:
            request_headers.update(headers)
        return request_headers

    def _prepare_request_data(
        self, payload: Optional[BaseModel], content_type: str
    ) -> tuple[Optional[dict], Optional[dict]]:
        """Prepare request data based on content type.

        Args:
            payload: Optional request payload
            content_type: Content type for the request

        Returns:
            tuple: (data, json_data) for the request
        """
        data = None
        json_data = None

        if payload:
            payload_dict = payload.model_dump(exclude_none=True)
            if content_type == 'application/json':
                json_data = payload_dict
            else:
                data = payload_dict

        return data, json_data

    def _process_response(self, response: requests.Response, response_model: Optional[type[T]]) -> ApiResponse[T]:
        """Process the API response.

        Args:
            response: HTTP response object
            response_model: Expected response data model

        Returns:
            ApiResponse: Standardized response with typed data
        """
        # Handle successful responses with content and a response model
        if response.status_code == 200 and response_model and response.content:
            return self._parse_successful_response(response, response_model)

        # Handle other responses
        return self._parse_other_response(response)

    def _parse_successful_response(self, response: requests.Response, response_model: type[T]) -> ApiResponse[T]:
        """Parse a successful (200) response with content.

        Args:
            response: HTTP response object
            response_model: Expected response data model

        Returns:
            ApiResponse: Standardized response with typed data
        """
        try:
            response_json = response.json()

            # Handle list responses
            if isinstance(response_json, list):
                return self._parse_list_response(response, response_json, response_model)

            # Handle dictionary responses
            parsed_data = response_model(**response_json)
            return ApiResponse(status_code=response.status_code, data=parsed_data, raw_data=response_json, error=None)
        except Exception as e:
            logger.debug(f'Failed to parse response data: {e}')
            raw_data = {} if not response.content else ({} if isinstance(response.json(), list) else response.json())
            return ApiResponse(
                status_code=response.status_code,
                raw_data=raw_data,
                error=f'Failed to parse response: {e!s}',
            )

    def _parse_list_response(
        self, response: requests.Response, response_json: list, response_model: type[T]
    ) -> ApiResponse[T]:
        """Parse a response containing a list.

        Args:
            response: HTTP response object
            response_json: Response data as JSON list
            response_model: Expected response data model

        Returns:
            ApiResponse: Standardized response with typed data
        """
        # For List[SomeModel] response types
        if hasattr(response_model, '__origin__') and response_model.__origin__ is list:
            item_model = response_model.__args__[0]
            parsed_data = [item_model(**item) for item in response_json]
            return ApiResponse(
                status_code=response.status_code,
                data=parsed_data,
                raw_data=response_json,
                error=None,
            )

        # Model is not a list type but response is a list
        logger.debug(f'Expected a list model but got {response_model}')
        return ApiResponse(
            status_code=response.status_code,
            raw_data=response_json,
            error='Response is a list but model is not List[T]',
        )

    def _parse_other_response(self, response: requests.Response) -> ApiResponse[T]:
        """Parse non-200 responses or responses without content.

        Args:
            response: HTTP response object

        Returns:
            ApiResponse: Standardized response with typed data
        """
        try:
            if response.content:
                response_data = response.json()
                return ApiResponse(
                    status_code=response.status_code,
                    raw_data=response_data,
                    error=response.text if response.status_code >= 400 else None,
                )

            return ApiResponse(
                status_code=response.status_code,
                raw_data={},
                error=response.text if response.status_code >= 400 else None,
            )
        except Exception:
            # If JSON parsing fails, return empty raw_data
            return ApiResponse(
                status_code=response.status_code,
                raw_data={},
                error=response.text if response.status_code >= 400 else None,
            )

    def post(
        self,
        endpoint: str,
        payload: BaseModel,
        response_model: type[T],
        query_params: Optional[dict[str, Any]] = None,
        headers: Optional[dict[str, str]] = None,
        content_type: str = 'application/json',
    ) -> ApiResponse[T]:
        """Make a POST request to the API.

        Args:
            endpoint: API endpoint path (without base URL)
            payload: Request payload as a Pydantic model
            response_model: Expected response data model
            query_params: Optional query parameters
            headers: Optional request headers
            content_type: Content type for the request

        Returns:
            ApiResponse: Standardized response with typed data

        Raises:
            MurError: If the API request fails
        """
        return self.request(
            method='post',
            endpoint=endpoint,
            payload=payload,
            response_model=response_model,
            query_params=query_params,
            headers=headers,
            content_type=content_type,
        )

    def get(
        self,
        endpoint: str,
        response_model: type[T],
        query_params: Optional[dict[str, Any]] = None,
        headers: Optional[dict[str, str]] = None,
    ) -> ApiResponse[T]:
        """Make a GET request to the API.

        Args:
            endpoint: API endpoint path (without base URL)
            response_model: Expected response data model
            query_params: Optional query parameters
            headers: Optional request headers

        Returns:
            ApiResponse: Standardized response with typed data

        Raises:
            MurError: If the API request fails
        """
        return self.request(
            method='get', endpoint=endpoint, response_model=response_model, query_params=query_params, headers=headers
        )

    def put(
        self,
        endpoint: str,
        payload: BaseModel,
        response_model: type[T],
        query_params: Optional[dict[str, Any]] = None,
        headers: Optional[dict[str, str]] = None,
        content_type: str = 'application/json',
    ) -> ApiResponse[T]:
        """Make a PUT request to the API.

        Args:
            endpoint: API endpoint path (without base URL)
            payload: Request payload as a Pydantic model
            response_model: Expected response data model
            query_params: Optional query parameters
            headers: Optional request headers
            content_type: Content type for the request

        Returns:
            ApiResponse: Standardized response with typed data

        Raises:
            MurError: If the API request fails
        """
        return self.request(
            method='put',
            endpoint=endpoint,
            payload=payload,
            response_model=response_model,
            query_params=query_params,
            headers=headers,
            content_type=content_type,
        )

    def delete(
        self,
        endpoint: str,
        response_model: Optional[type[T]] = None,
        query_params: Optional[dict[str, Any]] = None,
        headers: Optional[dict[str, str]] = None,
    ) -> ApiResponse[T]:
        """Make a DELETE request to the API.

        Args:
            endpoint: API endpoint path (without base URL)
            response_model: Expected response data model (optional)
            query_params: Optional query parameters
            headers: Optional request headers

        Returns:
            ApiResponse: Standardized response with typed data

        Raises:
            MurError: If the API request fails
        """
        return self.request(
            method='delete',
            endpoint=endpoint,
            response_model=response_model,
            query_params=query_params,
            headers=headers,
        )

    def patch(
        self,
        endpoint: str,
        payload: BaseModel,
        response_model: type[T],
        query_params: Optional[dict[str, Any]] = None,
        headers: Optional[dict[str, str]] = None,
        content_type: str = 'application/json',
    ) -> ApiResponse[T]:
        """Make a PATCH request to the API.

        Args:
            endpoint: API endpoint path (without base URL)
            payload: Request payload as a Pydantic model
            response_model: Expected response data model
            query_params: Optional query parameters
            headers: Optional request headers
            content_type: Content type for the request

        Returns:
            ApiResponse: Standardized response with typed data

        Raises:
            MurError: If the API request fails
        """
        return self.request(
            method='patch',
            endpoint=endpoint,
            payload=payload,
            response_model=response_model,
            query_params=query_params,
            headers=headers,
            content_type=content_type,
        )
