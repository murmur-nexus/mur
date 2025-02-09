import logging
import sys
from dataclasses import dataclass, field
from enum import Enum
from typing import ClassVar, Optional

import click

logger = logging.getLogger(__name__)


class MessageType(Enum):
    """Enumeration of message types for error handling.

    Defines the different severity levels for messages:
    - ERROR: Critical issues requiring immediate attention
    - WARNING: Potential problems that don't stop execution
    - INFO: Informational messages
    """

    ERROR = 'error'
    WARNING = 'warning'
    INFO = 'info'


@dataclass
class ErrorContext:
    """Context information for error handling."""

    message: str
    code: int
    type: MessageType = MessageType.ERROR
    detail: Optional[str] = None
    debug_messages: list[str] = field(default_factory=list)
    original_error: Optional[Exception] = None
    field_name: Optional[str] = None


class MurError(Exception):
    """Base exception class for all Mur errors.

    Maps numeric error codes to human-readable messages across different categories:
    - 0xx: Success
    - 1xx: CLI Input/Usage
    - 2xx: Local Filesystem
    - 3xx: Local Artifact State
    - 5xx: Authentication/Authorization
    - 6xx: Remote Artifact Resolution
    - 8xx: Network Operations

    Usage:
        raise MurError(
            code=201,
            message="Artifact file not found",
            detail="Check if the file exists and you have correct permissions.",
            debug_message="Attempted to access file at /path/to/file",
            original_error=original_exception
        )
    """

    ERROR_MAP: ClassVar[dict[int, str]] = {
        # Category 0: Success
        000: 'Success',
        # Category 1: CLI Input/Usage (User Interface)
        100: 'General Command-Line Error',
        101: 'Invalid Command',
        102: 'Missing Required Argument',
        103: 'Invalid Option Format',
        104: 'Invalid Argument Value',
        105: 'Conflicting Options',
        # Category 2: Local Filesystem
        200: 'General Filesystem Error',
        201: 'File Not Found',
        202: 'Insufficient Disk Space',
        203: 'Permission Denied',
        204: 'Invalid File Format',
        205: 'Manifest File Error',
        206: 'Artifact Path Error',
        207: 'Invalid Manifest Value',
        208: 'Failed Local Storage',
        209: 'Failed Creating Directory',
        210: 'Failed Creating File',
        211: 'Directory Not Found',
        212: 'File already exists',
        # Category 3: Local Artifact State
        300: 'General Artifact Error',
        301: 'Artifact Already Installed',
        302: 'Artifact Not Installed',
        303: 'Artifact Corrupted',
        304: 'Local Version Conflict',
        305: 'Artifact Verification Failed',
        306: 'Local Artifact Metadata Invalid',
        307: 'Artifact Build Failed',
        308: 'Missing Dependencies',
        309: 'Failed to Uninstall Artifact',
        # Category 5: Authentication/Authorization
        500: 'General Auth Error',
        501: 'Authentication Error',
        502: 'Authorization Error',
        503: 'Invalid Credentials',
        504: 'Token Expired',
        505: 'Insufficient Permissions',
        506: 'Rate Limit Exceeded',
        # Category 6: Remote Artifact Resolution
        600: 'General Resolution Error',
        601: 'Artifact Not Found',
        602: 'Version Not Found',
        603: 'Invalid Artifact Name',
        604: 'Invalid Version Specification',
        605: 'Unsupported Artifact Format',
        606: 'Invalid Remote Metadata',
        # Category 8: Network Operations
        800: 'General Connection Error',
        801: 'Connection Unavailable',
        802: 'Download Failed',
        803: 'Invalid Registry Response',
        804: 'Connection Timeout',
        805: 'Artifact Upload Failed',
        806: 'Network Connection Failed',
        807: 'SSL/TLS Error',
    }

    def __init__(
        self,
        code: int,
        message: Optional[str] = None,
        type: MessageType = MessageType.ERROR,
        detail: Optional[str] = None,
        debug_messages: Optional[list[str]] = None,
        original_error: Optional[Exception] = None,
        field_name: Optional[str] = None,
    ) -> None:
        self.context = ErrorContext(
            message=message or 'Unknown Error',
            code=code,
            type=type,
            detail=detail,
            debug_messages=debug_messages or [],
            original_error=original_error,
            field_name=field_name,
        )
        super().__init__(str(code))

    def log(self) -> None:
        """Log the error with appropriate level and formatting."""
        # Define color mapping for different message types
        color_map = {
            MessageType.ERROR: 'red',
            MessageType.WARNING: 'yellow',
            MessageType.INFO: 'blue',
        }

        # Build the message
        error_description = self.ERROR_MAP.get(self.context.code, 'Unknown Error')
        message = f'[{self.context.code}] {error_description}'
        if self.context.message:  # Only add message if it was set
            message = f'{message} - {self.context.message}'
        if self.context.field_name:
            message = f'{self.context.field_name}: {message}'

        # Log main message
        prefix = self.context.type.value.upper()
        click.secho(f'{prefix}: {message}', fg=color_map[self.context.type])

        # Log detail if present
        if self.context.detail:
            click.echo(self.context.detail)

        # Log debug information if in debug mode
        if logger.isEnabledFor(logging.DEBUG):
            for debug_msg in self.context.debug_messages:
                click.echo(f'DEBUG: {debug_msg}')
            if self.context.original_error:
                click.echo(f'DEBUG: Original error: {self.context.original_error!s}')

    def handle(self) -> None:
        """Log the error and exit if it's an error type."""
        self.log()  # Log the message

        # Only exit for errors, continue execution for warnings and info
        if self.context.type == MessageType.ERROR:
            sys.exit(self.context.code)
