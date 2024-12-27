import logging
from typing import Literal

import click
from ruamel.yaml import YAML

from .base import ArtifactCommand

logger = logging.getLogger(__name__)


class NewArtifactCommand(ArtifactCommand):
    """Handles creation of new artifacts.

    This class manages the creation of new agent or tool artifacts by generating
    the necessary configuration files and directory structure.
    """

    def __init__(self, artifact_type: Literal['agent', 'tool'], name: str | None = None, verbose: bool = False) -> None:
        """Initialize new artifact command.

        Args:
            artifact_type: Type of artifact to create ('agent' or 'tool').
            name: Optional name for the artifact.
            verbose: Whether to enable verbose output.
        """
        self.verbose = verbose
        self.current_dir = self.get_current_dir()
        self.yaml = self._configure_yaml()
        self.artifact_type = artifact_type
        self.name = name
        super().__init__(self.artifact_type, verbose)

    def _configure_yaml(self) -> YAML:
        """Configure YAML parser settings.

        Returns:
            YAML: Configured YAML parser with specific formatting settings.
        """
        yaml = YAML()
        yaml.default_flow_style = False
        yaml.explicit_start = False
        yaml.explicit_end = False
        yaml.preserve_quotes = True
        return yaml

    def _create_build_manifest(self) -> None:
        """Create the murmur-build.yaml file with template structure.

        Raises:
            click.ClickException: If the configuration file already exists or creation fails.
        """
        config_file = self.current_dir / 'murmur-build.yaml'

        if config_file.exists():
            raise click.ClickException('murmur-build.yaml already exists in current directory')

        template = {
            'name': self.name if self.name else '',
            'type': self.artifact_type,
            'version': '0.1.0',
            'description': '',
            'metadata': {
                'author': '',
                'license': '',
                'tags': [],
            },
            'instructions': ['You are a friendly assistant.'],
        }

        try:
            with open(config_file, 'w') as f:
                self.yaml.dump(template, f)
            if self.verbose:
                logger.info(f'Created murmur-build.yaml with {self.artifact_type} template')
            logger.debug(f'Created build configuration at {config_file}')
        except Exception as e:
            raise click.ClickException(f'Failed to create murmur-build.yaml: {e}')

    def execute(self) -> None:
        """Execute the new artifact command.

        Creates a new artifact by generating the necessary configuration files.

        Raises:
            click.ClickException: If artifact creation fails.
        """
        try:
            self._create_build_manifest()
            self.log_success(
                f'Successfully created new {self.artifact_type} template\n'
                f'Please edit murmur-build.yaml to configure your {self.artifact_type}'
            )
        except Exception as e:
            self.handle_error(e, f'Failed to create new {self.artifact_type}')


def new_command() -> click.Command:
    """Create the new command for Click.

    Creates and configures a Click command for generating new artifacts with
    proper argument validation and handling.

    Returns:
        click.Command: Configured Click command for creating new artifacts.
    """

    def validate_name(ctx, param, value):
        """Validate and normalize the artifact name.

        Args:
            ctx: Click context
            param: Click parameter
            value: Input name value

        Returns:
            str | None: Normalized name or None if no name provided

        Raises:
            click.BadParameter: If name contains invalid characters or format
        """
        if value is None:
            return None

        # Convert to lowercase and replace underscores with hyphens
        value = value.lower().replace('_', '-')

        # Check for invalid characters
        if not all(c.isalnum() or c == '-' for c in value):
            raise click.BadParameter('Name must contain only letters, numbers, and hyphens')

        # Check for double hyphens
        if '--' in value:
            raise click.BadParameter('Name cannot contain double hyphens')

        # Check if starts or ends with hyphen
        if value.startswith('-') or value.endswith('-'):
            raise click.BadParameter('Name cannot start or end with a hyphen')

        return value

    @click.command()
    @click.argument('type', type=click.Choice(['agent', 'tool']))
    @click.argument('name', required=False, callback=validate_name)
    @click.option('--verbose', '-v', is_flag=True, help='Enable verbose output')
    def new(type: str, name: str | None, verbose: bool) -> None:
        """Create a new artifact project.

        Args:
            type: The type of artifact to create ('agent' or 'tool').
            name: Optional name for the artifact. Must contain only lowercase letters,
                numbers, and single hyphens.
            verbose: Whether to enable verbose output.

        Raises:
            click.BadParameter: If the provided name contains invalid characters or format.
        """
        artifact_type: Literal['agent', 'tool'] = 'agent' if type == 'agent' else 'tool'
        cmd = NewArtifactCommand(artifact_type, name, verbose)
        cmd.execute()

    return new
