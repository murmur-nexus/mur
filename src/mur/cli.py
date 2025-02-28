import logging
import os

import click

from .commands.build_artifact import build_command
from .commands.install_artifacts import install_command
from .commands.new_artifact import new_command
from .commands.publish_artifact import publish_command
from .commands.uninstall_artifacts import uninstall_command
from .core.auth import AuthenticationManager
from .utils.error_handler import MurError

# Configure logging
logging.basicConfig(
    level=logging.DEBUG if os.getenv('MURMUR_DEBUG_MODE', 'false').lower() in ['1', 'true'] else logging.INFO,
    format='%(levelname)s: %(message)s',
)
logger = logging.getLogger(__name__)


class MurCLI(click.Group):
    """Custom command group for better error handling.

    This class extends click.Group to provide enhanced error handling for the Mur CLI.
    It catches exceptions and logs them appropriately before raising click.Abort.
    """

    def __call__(self, *args, **kwargs):
        """Override the call method to handle exceptions.

        Args:
            *args: Variable length argument list.
            **kwargs: Arbitrary keyword arguments.

        Returns:
            The result of self.main(*args, **kwargs).

        Raises:
            click.Abort: If any exception occurs during command execution.
        """
        try:
            return self.main(*args, **kwargs)
        except MurError as e:
            e.log()  # handles all the logging
            raise click.Abort()
        except Exception as e:
            # Unexpected errors
            logger.error(str(e))
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug('Unexpected error:', exc_info=e)
            raise click.Abort()


@click.group(cls=MurCLI)
def main() -> None:
    """Mur CLI: Package, share, manage AI agents and tools.

    A command-line interface for managing Mur artifacts, including creation,
    building, installation, and publishing of AI agents and tools.
    """


@main.command()
@click.option('--verbose', '-v', is_flag=True, help='Enable verbose output')
def login(verbose: bool) -> None:
    """Authenticate with the Murmur service.

    Initiates the authentication flow to obtain and store credentials.

    Args:
        verbose (bool): If True, enables detailed output logging.

    Raises:
        click.Abort: If authentication fails.
    """
    try:
        auth_manager = AuthenticationManager.create(verbose)
        username = auth_manager.authenticate()
        click.echo(f'Login successful for {username}')
    except MurError as e:
        e.handle()


@main.command()
@click.option('--verbose', '-v', is_flag=True, help='Enable verbose output')
def logout(verbose: bool) -> None:
    """Clear stored credentials and tokens.

    Removes all stored authentication credentials and tokens from the system.

    Args:
        verbose (bool): If True, enables detailed output logging.

    Raises:
        click.Abort: If clearing credentials fails.
    """
    try:
        auth_manager = AuthenticationManager.create(verbose)
        auth_manager.clear_credentials()
        click.echo('Logged out successfully')
    except MurError as e:
        e.handle()


# Add commands directly
main.add_command(install_command())
main.add_command(uninstall_command())
main.add_command(new_command())
main.add_command(build_command())
main.add_command(publish_command())

if __name__ == '__main__':
    main()
