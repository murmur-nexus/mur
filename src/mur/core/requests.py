import logging
from typing import Any, Dict, Optional, Type, TypeVar, Generic

import requests
from pydantic import BaseModel

from ..utils.constants import DEFAULT_TIMEOUT
from ..utils.error_handler import MurError

logger = logging.getLogger(__name__)

T = TypeVar('T', bound=BaseModel)


class ApiResponse(BaseModel, Generic[T]):
    """Model for standardized API responses.
    
    Generic type parameter T represents the expected data model for successful responses.
    """
    status_code: int
    data: Optional[T] = None
    raw_data: Dict[str, Any] = {}
    error: Optional[str] = None


class ApiClient:
    """Client for making API calls to the Murmur server.
    
    This class handles all HTTP communication with the Murmur server,
    providing a consistent interface for API requests.
    
    Attributes:
        base_url (str): Base URL for the Murmur API
        verbose (bool): Flag for enabling verbose logging
    """
    
    def __init__(self, base_url: str, verbose: bool = False) -> None:
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
    
    def post(
        self, 
        endpoint: str, 
        payload: BaseModel,
        response_model: Type[T],
        query_params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        content_type: str = 'application/json'
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
        try:
            url = f'{self.base_url}/{endpoint.lstrip("/")}'
            
            # Default headers
            request_headers = {'Content-Type': content_type}
            if headers:
                request_headers.update(headers)
                
            verify_ssl = self.base_url.startswith('https://')
            
            # Handle different content types
            if content_type == 'application/json':
                data = None
                json_data = payload.model_dump(exclude_none=True)
            elif content_type == 'application/x-www-form-urlencoded':
                data = payload.model_dump(exclude_none=True)
                json_data = None
            else:
                data = payload.model_dump(exclude_none=True)
                json_data = None
            
            response = requests.post(
                url, 
                params=query_params, 
                headers=request_headers, 
                data=data,
                json=json_data,
                timeout=DEFAULT_TIMEOUT, 
                verify=verify_ssl
            )
            
            if self.verbose:
                logger.debug(f"POST {endpoint} response status: {response.status_code}")
            
            # Parse response
            response_data = {}
            if response.status_code == 200:
                try:
                    response_data = response.json()
                    parsed_data = response_model(**response_data)
                    return ApiResponse(
                        status_code=response.status_code,
                        data=parsed_data,
                        raw_data=response_data,
                        error=None
                    )
                except Exception as e:
                    logger.debug(f"Failed to parse response data: {e}")
                    return ApiResponse(
                        status_code=response.status_code,
                        raw_data=response_data,
                        error=f"Failed to parse response: {str(e)}"
                    )
            
            return ApiResponse(
                status_code=response.status_code,
                raw_data=response.json() if response.content else {},
                error=response.text
            )
            
        except Exception as e:
            logger.debug(f"API request error: {e}")
            raise MurError(
                code=501,
                message=f"API request to {endpoint} failed",
                detail="Failed to communicate with server",
                original_error=e,
            )