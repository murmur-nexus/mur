import configparser
import logging
from typing import Optional, TypedDict

import click

from ..core.capsule_client import CapsuleClient
from ..utils.error_handler import MurError
from .base import ArtifactCommand

logger = logging.getLogger(__name__)

# Config section constants
PUBLIC_CONFIG_SECTION = 'murmur-nexus'
PRIVATE_CONFIG_SECTION = 'murmur-private'


class ToolInfo(TypedDict):
    """TypedDict for tool information."""

    name: str
    version: str
    description: str


class ListArtifactCommand(ArtifactCommand):
    """Lists artifacts installed on a host via CapsuleClient.

    This command connects to a specified host and retrieves a list of
    all installed artifacts (agents and tools).
    """

    def __init__(self, verbose: bool = False, host: Optional[str] = None) -> None:
        """Initialize list command.

        Args:
            verbose: Whether to enable verbose output
            host: Optional host URL for using CapsuleClient
        """
        super().__init__('list', verbose)
        self.host = host or self._get_host_from_config()
        self.capsule_client = CapsuleClient(base_url=self.host, verbose=verbose) if self.host else None

    def _get_host_from_config(self) -> Optional[str]:
        """Get host URL from configuration file.

        Returns:
            Optional[str]: Host URL if found in config, None otherwise
        """
        try:
            # Determine which config section to use based on registry type
            section = PRIVATE_CONFIG_SECTION if self.is_private_registry else PUBLIC_CONFIG_SECTION

            config = configparser.ConfigParser()
            config.read(self.murmurrc_path)

            # Only look in the appropriate section
            if section in config and 'host' in config[section]:
                return config[section]['host']

            return None
        except Exception as e:
            logger.debug(f'Failed to read host from config: {e}')
            return None

    def _display_artifacts(self, data: dict) -> None:
        """Display the list of artifacts to the console.

        Args:
            data: Response data containing the artifacts list
        """
        tools_dict = data.get('tools', {})

        if not tools_dict:
            click.echo('No artifacts installed on the host.')
            return

        tool_count = data.get('count', len(tools_dict))
        click.echo(click.style(f'Found {tool_count} installed artifact(s):', bold=True))

        # Group tools by their source/package
        source_groups = self._group_tools_by_source(tools_dict)
        self._display_grouped_tools(source_groups)

    def _group_tools_by_source(self, tools_dict: dict) -> dict[str, list[ToolInfo]]:
        """Group tools by their source.

        Args:
            tools_dict: Dictionary of tools

        Returns:
            Dictionary mapping source to list of tool info
        """
        source_groups: dict[str, list[ToolInfo]] = {}

        for tool_name, tool_info in tools_dict.items():
            source = tool_info.get('source', '').split(':')[0]

            if source not in source_groups:
                source_groups[source] = []

            # Extract version from wheel path if available
            version = 'Unknown'
            wheel_path = tool_info.get('wheel', '')
            if wheel_path:
                wheel_filename = wheel_path.split('/')[-1]
                version_part = wheel_filename.split('-')
                if len(version_part) > 1:
                    version = version_part[1]

            source_groups[source].append(
                {'name': tool_name, 'version': version, 'description': tool_info.get('description', '')}
            )

        return source_groups

    def _display_grouped_tools(self, source_groups: dict[str, list[ToolInfo]]) -> None:
        """Display tools grouped by source.

        Args:
            source_groups: Dictionary mapping source to list of tool info
        """
        for source, tools in source_groups.items():
            # If source has multiple tools, display as a toolkit
            if len(tools) > 1:
                self._display_toolkit(source, tools)
            else:
                # Single tool
                self._display_single_tool(tools[0])

    def _display_toolkit(self, source: str, tools: list[ToolInfo]) -> None:
        """Display a toolkit (multiple tools from same source).

        Args:
            source: Source/package name
            tools: List of tools in the toolkit
        """
        # Extract toolkit version from first tool
        toolkit_version = tools[0]['version']
        click.echo(f'🧰 {source} (v{toolkit_version}):')

        for tool in tools:
            click.echo(f"  🔧 {tool['name']}")

            # Optionally show short description (first line)
            description = tool.get('description', '').split('\n')[0].strip()
            if description and self.verbose:
                click.echo(f'     {description}')

    def _display_single_tool(self, tool: ToolInfo) -> None:
        """Display a single tool.

        Args:
            tool: Tool information dictionary
        """
        click.echo(f"🔧 {tool['name']} (v{tool['version']})")

        # Optionally show short description (first line)
        description = tool.get('description', '').split('\n')[0].strip()
        if description and self.verbose:
            click.echo(f'   {description}')

    def execute(self) -> None:
        """Execute the list command.

        Connects to the host and retrieves a list of installed artifacts.

        Raises:
            MurError: If no host is specified or if the listing fails
        """
        if not self.host or not self.capsule_client:
            raise MurError(
                code=609,
                message='No host specified for artifact listing',
                detail='The list command requires a host to be specified via --host or configuration.',
            )

        try:
            response = self.capsule_client.list_tools()

            if response.status_code >= 400:
                raise MurError(
                    code=610,
                    message='Failed to list artifacts',
                    detail=f"The host returned an error: {response.error or 'Unknown error'}",
                )

            self._display_artifacts(response.raw_data)

        except Exception as e:
            self.handle_error(e, 'Failed to list artifacts')


def list_command() -> click.Command:
    """Create the list command for Click."""

    @click.command()
    @click.option('--verbose', '-v', is_flag=True, help='Enable verbose output')
    @click.option('--host', is_flag=False, flag_value='from_config', help='Host URL to use for listing artifacts')
    def list_cmd(verbose: bool, host: str | None) -> None:
        """List artifacts installed on a host.

        Connects to the specified host via CapsuleClient and
        displays all installed artifacts.

        Usage:
          mur list --host URL      # Connect to specific host URL
          mur list --host          # Connect to host from config
        """
        # Convert flag_value to None to trigger config lookup
        if host == 'from_config':
            host = None

        cmd = ListArtifactCommand(verbose=verbose, host=host)

        try:
            cmd.execute()
        except MurError as e:
            e.handle()

    return list_cmd
