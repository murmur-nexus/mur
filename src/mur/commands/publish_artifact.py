import logging
from pathlib import Path

import click

from ..core.packaging import normalize_package_name
from ..utils.error_handler import MurError
from .base import ArtifactCommand

logger = logging.getLogger(__name__)


class PublishCommand(ArtifactCommand):
    """Handles artifact publishing operations.

    This class manages the process of building and publishing artifacts to the Murmur registry.
    Supports both agent and tool artifact types.
    """

    def __init__(self, verbose: bool = False, index_url: str | None = None) -> None:
        """Initialize publish command.

        Args:
            verbose (bool): Whether to enable verbose output. Defaults to False.
            index_url (str | None): The index URL to use for publishing. Defaults to None.

        Raises:
            MurError: If the artifact type in murmur.yaml is invalid.
        """
        try:
            super().__init__('publish', verbose)

            self.scope: str | None = None

            if not self.is_private_registry:
                self._ensure_authenticated()

            # Load manifest and determine artifact type
            try:
                self.manifest = self._load_murmur_yaml_from_artifact()
                self.artifact_type = self.manifest.type
            except MurError as e:
                e.handle()

            if self.artifact_type not in ['agent', 'tool']:
                raise MurError(
                    code=207,
                    message=f"Invalid artifact type '{self.artifact_type}' in murmur.yaml",
                    detail="Must be either 'agent' or 'tool'.",
                )
        except Exception as e:
            if not isinstance(e, MurError):
                raise MurError(code=100, message=str(e))
            raise

    def _publish_files(self, dist_dir: Path, artifact_files: list[str]) -> None:
        """Publish built artifact files to registry.

        Args:
            dist_dir (Path): Directory containing built files
            artifact_files (list[str]): List of artifact files to publish

        Raises:
            MurError: If package names don't match normalized format
        """
        try:
            if self.verbose:
                logger.info('Publishing artifact...')

            # Validate artifact names in build files
            normalized_name = normalize_package_name(self.manifest.name)
            for file_name in artifact_files:
                # Extract artifact name from file (everything before first dash)
                artifact_name = file_name.split('-')[0]
                # Remove scope if present before comparing
                unscoped_artifact_name = self._remove_scope(artifact_name)
                if normalize_package_name(unscoped_artifact_name) != normalized_name:
                    raise MurError(
                        code=603,
                        message='Invalid artifact name in build files',
                        detail=f'Expected normalized name "{normalized_name}" but found "{unscoped_artifact_name}".',
                    )

            self.manifest.type = self.artifact_type
            registered_artifact = self.registry_adapter.publish_artifact(self.manifest, self.scope)

            # Match and upload files using signed URLs
            for signed_url_info in registered_artifact.get('signed_upload_urls', []):
                file_type = signed_url_info.get('file_type')
                signed_url = signed_url_info.get('signed_url')

                # Find matching artifact file
                matching_file = None
                if file_type == 'source':
                    matching_file = next((f for f in artifact_files if f.endswith('.tar.gz')), None)
                elif file_type == 'wheel':
                    matching_file = next((f for f in artifact_files if f.endswith('.whl')), None)

                if matching_file:
                    file_path = dist_dir / matching_file
                    if self.verbose:
                        logger.info(f'Uploading {matching_file}...')
                    self.registry_adapter.upload_file(file_path, signed_url)
                else:
                    logger.warning(f'No matching file found for type: {file_type}')

        except MurError as e:
            e.handle()

    def _find_artifact_files(self) -> tuple[Path, list[str]]:
        """Find artifact distribution files for publishing.

        Looks for .whl and .tar.gz files in the dist directory, first checking
        the current directory and then the artifact directory.

        Returns:
            tuple[Path, list[str]]: A tuple containing the dist directory path and list of artifact filenames

        Raises:
            MurError: If no dist directory or artifact files are found
        """
        # Look for dist directory in current directory first
        dist_dir = self.current_dir / 'dist'
        if not dist_dir.exists() or (not any(dist_dir.glob('*.whl')) and not any(dist_dir.glob('*.tar.gz'))):
            # Try artifact directory
            normalized_artifact_name = normalize_package_name(self.manifest.name)
            artifact_dir = self.current_dir / normalized_artifact_name / 'dist'
            if not artifact_dir.exists():
                raise MurError(
                    code=201,
                    message='No dist directory found',
                    detail='Please run "mur build" first to build the artifact.',
                )
            dist_dir = artifact_dir

        artifact_files = [f.name for f in dist_dir.glob('*') if f.name.endswith(('.whl', '.tar.gz'))]
        if not artifact_files:
            raise MurError(
                code=211,
                message='No artifact files found in dist directory',
                detail='Please run "mur build" first to build the artifact.',
            )

        return dist_dir, artifact_files

    def execute(self) -> None:
        """Execute the publish command.

        This method orchestrates the publishing process including:
        1. Determining the appropriate registry
        2. Finding the previously built package files
        3. Publishing the files

        Raises:
            Exception: If any step of the publishing process fails
        """
        try:
            # Find artifact files
            dist_dir, artifact_files = self._find_artifact_files()
            self.scope = artifact_files[0].split('_')[0]

            # Publish package files
            self._publish_files(dist_dir, artifact_files)

            normalized_artifact_name = normalize_package_name(self.manifest.name)
            if self.is_private_registry:
                artifact_name = normalized_artifact_name
            else:
                artifact_name = f'{self.scope}_{normalized_artifact_name}'

            self.log_success(
                f'Successfully published {self.artifact_type} ' f'{artifact_name}=={self.manifest.version}'
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
        try:
            cmd = PublishCommand(verbose)
            cmd.execute()
        except MurError as e:
            e.handle()

    return publish
