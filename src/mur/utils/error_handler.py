import sys
from typing import ClassVar


class CodeError(Exception):
    """Custom exception class for handling application error codes.

    Maps numeric error codes to human-readable messages across different categories:
    - 0xx: Success
    - 1xx: CLI Input/Usage
    - 2xx: Local Filesystem
    - 3xx: Local Package State
    - 5xx: Authentication/Authorization
    - 6xx: Remote Package Resolution
    - 8xx: Network Operations
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
        204: 'Lock File Error',
        205: 'Config File Error',
        206: 'Package Installation Path Error',
        # Category 3: Local Package State
        300: 'General Package Error',
        301: 'Package Already Installed',
        302: 'Package Not Installed',
        303: 'Package Corrupted',
        304: 'Local Version Conflict',
        305: 'Package Verification Failed',
        306: 'Local Package Metadata Invalid',
        307: 'Package Lock Error',
        # Category 5: Authentication/Authorization
        500: 'General Auth Error',
        501: 'Authentication Error',
        502: 'Authorization Error',
        503: 'Invalid Credentials',
        504: 'Token Expired',
        505: 'Insufficient Permissions',
        506: 'Rate Limit Exceeded',
        # Category 6: Remote Package Resolution
        600: 'General Package Resolution Error',
        601: 'Package Not Found',
        602: 'Version Not Found',
        603: 'Invalid Package Name',
        604: 'Invalid Version Specification',
        605: 'Unsupported Package Format',
        606: 'Invalid Remote Metadata',
        # Category 8: Network Operations
        800: 'General Connection Error',
        801: 'Connection Unavailable',
        802: 'Download Failed',
        803: 'Invalid Registry Response',
        804: 'Connection Timeout',
        805: 'Package Upload Failed',
        806: 'Network Connection Failed',
        807: 'SSL/TLS Error',
    }

    def __init__(self, code, custom_message=None):
        self.code = code
        self.message = custom_message or self.ERROR_MAP.get(code, 'Unknown Error')
        super().__init__(self.message)

    def handle(self):
        """Prints the error and exits the program with the appropriate code."""
        print(f'Error {self.code}: {self.message}')
        sys.exit(self.code)
