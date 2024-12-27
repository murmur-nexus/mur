import logging
from pathlib import Path

import click

from ..adapters import PrivateRegistryAdapter, PublicRegistryAdapter
from ..core.packaging import BuildError, PackageBuilder, PackageConfig
from ..utils.constants import MURMUR_INDEX_URL, MURMURRC_PATH
from ..utils.error_handler import CodeError
from .base import ArtifactCommand

logger = logging.getLogger(__name__)


class PublishCommand(ArtifactCommand):
    """Handles artifact publishing operations.

    This class manages the process of building and publishing artifacts to the Murmur registry.
    Supports both agent and tool artifact types.
    """

    def __init__(self, verbose: bool = False) -> None:
        """Initialize publish command.

        Args:
            verbose (bool): Whether to enable verbose output. Defaults to False.

        Raises:
            click.ClickException: If the artifact type in murmur.yaml is invalid.
        """
        # Fix Deprioritize to end of __init__??
        super().__init__('publish', verbose)

        # Load config and determine artifact type
        self.config = self._load_murmur_yaml_from_package()
        self.artifact_type = self.config.type

        if self.artifact_type not in ['agent', 'tool']:
            raise click.ClickException(
                f"Invalid artifact type '{self.artifact_type}' in murmur.yaml. " "Must be either 'agent' or 'tool'."
            )

    def _build_package(self) -> tuple[Path, list[str]]:
        """Build the package for publishing.

        Returns:
            tuple[Path, list[str]]: A tuple containing:
                - dist_directory (Path): Directory containing the built files
                - package_files (list[str]): List of built package filenames

        Raises:
            click.ClickException: If the package build process fails.
        """
        try:
            builder = PackageBuilder(self.current_dir, self.verbose)
            result = builder.build(self.artifact_type)
            logger.debug(f'Built package files: {result.package_files}')
            return result.dist_dir, result.package_files
        except BuildError as e:
            raise click.ClickException(f'Package build failed: {e}')

    def _publish_files(self, config: PackageConfig, dist_dir: Path, package_files: list[str]) -> None:
        """Publish built package files to registry.

        Args:
            config (PackageConfig): Package configuration containing metadata
            dist_dir (Path): Directory containing built files
            package_files (list[str]): List of package files to publish

        Raises:
            click.ClickException: If the publishing process fails
            CodeError: If there's an error during the publishing process
        """
        try:
            for package_file in package_files:
                file_path = dist_dir / package_file
                if self.verbose:
                    logger.info(f'Publishing {package_file}...')

                self.registry.publish_artifact(
                    artifact_type=self.artifact_type,
                    name=config.name,
                    version=config.version,
                    description=config.description,
                    metadata=config.metadata,
                    file_path=file_path,
                )
        except CodeError as e:
            e.handle()

    def execute(self) -> None:
        """Execute the publish command.

        This method orchestrates the entire publishing process including:
        1. Determining the appropriate registry
        2. Building the package
        3. Publishing the files

        Raises:
            Exception: If any step of the publishing process fails
        """
        try:
            # Get primary publish URL from .murmurrc
            index_url, _ = self._get_index_urls_from_murmurrc(MURMURRC_PATH)

            # Create appropriate adapter based on index URL
            if index_url == MURMUR_INDEX_URL:
                self.registry = PrivateRegistryAdapter(verbose=self.verbose)
            else:
                self.registry = PublicRegistryAdapter(verbose=self.verbose)

            dist_dir, package_files = self._build_package()
            self._publish_files(self.config, dist_dir, package_files)

            self.log_success(
                f'Successfully published {self.artifact_type} ' f'{self.config.name} {self.config.version}'
            )

        except Exception as e:
            self.handle_error(e, f'Failed to publish {self.artifact_type}')


def publish_command() -> click.Command:
    """Create the publish command for Click.

    Returns:
        click.Command: Configured Click command for publishing artifacts to the Murmur registry.
    """

    @click.command()
    @click.option('--verbose', '-v', is_flag=True, help='Enable verbose output')
    def publish(verbose: bool) -> None:
        """Publish an artifact to the Murmur registry."""
        cmd = PublishCommand(verbose)
        cmd.execute()

    return publish
