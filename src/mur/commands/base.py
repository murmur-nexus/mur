import configparser
import logging
import os
import sys
from pathlib import Path

import click
from ruamel.yaml import YAML

from ..adapters.adapter_factory import get_index_url_from_config, get_registry_adapter
from ..adapters.private_adapter import PrivateRegistryAdapter
from ..core.auth import AuthenticationManager
from ..core.packaging import ArtifactManifest, normalize_package_name
from ..utils.constants import DEFAULT_MURMUR_EXTRA_INDEX_URLS, DEFAULT_MURMUR_INDEX_URL, GLOBAL_MURMURRC_PATH
from ..utils.error_handler import MurError

logger = logging.getLogger(__name__)


class ArtifactCommand:
    """Base class for artifact-related commands.

    This class provides common functionality for commands that interact with artifacts,
    including manifest management, authentication, and registry operations.
    """

    def __init__(self, command_name: str, verbose: bool = False) -> None:
        """Initialize artifact command.

        Args:
            command_name: Name of the command
            verbose: Whether to enable verbose output
        """
        # Add debug logging to track initialization
        logger.debug(f"Initializing ArtifactCommand for '{command_name}' (id: {id(self)})")

        # Mark as initialized to prevent double initialization
        self._initialized = True

        self.command_name = command_name
        self.verbose = verbose
        self.scope: str | None = None

        # Initialize yaml and paths
        self.current_dir = self.get_current_dir()
        self.yaml = self._configure_yaml()
        self.murmurrc_path = self._get_murmurrc_path()

        # Follow the registry adapter flow
        self.registry_adapter = get_registry_adapter(self.murmurrc_path, self.command_name, self.verbose)
        self.is_private_registry = isinstance(self.registry_adapter, PrivateRegistryAdapter)
        self.index_url = get_index_url_from_config(self.murmurrc_path, self.verbose)

    def _get_murmurrc_path(self) -> Path:
        """Get the path to the .murmurrc file to use.

        Checks for a local .murmurrc in the current directory first,
        then falls back to the global one in the user's home directory.

        Args:
            verbose: Whether to enable verbose logging

        Returns:
            Path: Path to the .murmurrc file to use
        """
        current_dir = Path.cwd()
        local_murmurrc = current_dir / '.murmurrc'

        if local_murmurrc.exists():
            if self.verbose:
                logger.info(f'Using local configuration from {local_murmurrc}')
            return local_murmurrc

        if self.verbose:
            logger.info(f'Using global configuration from {GLOBAL_MURMURRC_PATH}')

        if not GLOBAL_MURMURRC_PATH.exists():
            if self.verbose:
                logger.info('Global .murmurrc not found, you must be new around here!')
                logger.info("Running 'mur config init --global' with default settings")
            self._init_default_global_murmurrc()

        return GLOBAL_MURMURRC_PATH

    def _init_default_global_murmurrc(self) -> None:
        """Initialize a default global .murmurrc file.

        This method is used to create a default configuration when none exists.
        It's a simplified version of ConfigCommand.init_config to avoid circular imports.
        """
        try:
            config_path = GLOBAL_MURMURRC_PATH

            # Create parent directories if they don't exist
            config_path.parent.mkdir(parents=True, exist_ok=True)

            # Create new config with default settings
            config = configparser.ConfigParser()
            config['murmur-nexus'] = {
                'index-url': DEFAULT_MURMUR_INDEX_URL,
                'extra-index-url': ' '.join(DEFAULT_MURMUR_EXTRA_INDEX_URLS),
            }

            with open(config_path, 'w') as f:
                config.write(f)

            if self.verbose:
                logger.info(f'Created global .murmurrc at: {config_path}')

        except Exception as e:
            raise MurError(code=405, message='Failed to create global .murmurrc', original_error=e)

    def _get_index_urls_from_murmurrc(self, murmurrc_path: str | Path) -> tuple[str, list[str]]:
        """Get index URLs from .murmurrc file.

        Args:
            murmurrc_path: Path to .murmurrc file.

        Returns:
            tuple: A tuple containing:
                - str: The primary index URL
                - list[str]: List of extra index URLs

        Raises:
            FileNotFoundError: If .murmurrc file does not exist.
            ValueError: If index-url is not found in config.
        """
        config = configparser.ConfigParser()
        if not os.path.exists(murmurrc_path):
            raise FileNotFoundError(f'{murmurrc_path} not found.')
        config.read(murmurrc_path)

        index_url = config.get('murmur-nexus', 'index-url', fallback=None)
        if not index_url:
            raise ValueError("No 'index-url' found in .murmurrc under [murmur-nexus].")

        # Get all extra-index-url values
        extra_index_urls: list[str] = []
        if config.has_option('murmur-nexus', 'extra-index-url'):
            # Handle both single and multiple extra-index-url entries
            extra_urls = config.get('murmur-nexus', 'extra-index-url')
            extra_index_urls.extend(url.strip() for url in extra_urls.split('\n') if url.strip())

        return index_url, extra_index_urls

    def get_current_dir(self) -> Path:
        """Get current working directory.

        Returns:
            Path to current directory

        Raises:
            MurError: If current directory cannot be accessed
        """
        try:
            return Path.cwd()
        except Exception:
            raise MurError(
                code=200,
                message='Cannot access the current directory',
                detail="This usually happens when the current directory has been deleted or you don't have permissions. "
                "Please ensure you're in a valid directory and try again.",
            )

    def handle_error(self, error: Exception, message: str) -> None:
        """Handle command errors consistently.

        Args:
            error: The exception that occurred.
            message: Error message prefix to display before the error details.
        """
        if isinstance(error, MurError):
            error.handle()
            sys.exit(error.context.code)
        else:
            error_msg = f'{message}: {error!s}'
            logger.error(error_msg, exc_info=True)
            wrapped_error = MurError(code=300, message=message, detail=error_msg, original_error=error)
            wrapped_error.handle()
            sys.exit(wrapped_error.context.code)

    def log_success(self, message: str) -> None:
        """Log success message in green color.

        Args:
            message: Success message to display.
        """
        click.echo(click.style(message, fg='green'))

    def _remove_scope(self, artifact_name: str) -> str:
        """Remove scope from artifact name if present.

        Args:
            artifact_name (str): artifact name that might include scope

        Returns:
            str: artifact name with scope removed if it was present
        """
        if self.is_private_registry:
            return artifact_name

        scope_prefix = f'{self.scope}_'
        if artifact_name.startswith(scope_prefix):
            return artifact_name[len(scope_prefix) :]
        return artifact_name

    def _configure_yaml(self) -> YAML:
        """Configure YAML parser settings.

        Configures a YAML parser with specific formatting settings for consistent
        file generation and parsing.

        Returns:
            YAML: Configured YAML parser with specific formatting settings.
        """
        yaml = YAML()
        yaml.default_flow_style = False
        yaml.explicit_start = False
        yaml.explicit_end = False
        yaml.preserve_quotes = True
        yaml.indent(mapping=2, sequence=4, offset=2)
        yaml.allow_duplicate_keys = True  # Prep for graph feature 🚀
        return yaml

    def _load_murmur_yaml_from_current_dir(self) -> ArtifactManifest:
        """Load installation manifest from murmur.yaml in current directory.

        Returns:
            ArtifactManifest: Artifact manifest from the installation manifest.

        Raises:
            MurError: If murmur.yaml is not found or cannot be loaded.
        """
        manifest_path = self.current_dir / 'murmur.yaml'

        if manifest_path.exists():
            try:
                # Load artifact manifest for installation
                return ArtifactManifest(manifest_path, is_build_manifest=False)
            except Exception as e:
                logger.debug(f'Error loading manifest {manifest_path}: {e!s}')
                raise MurError(code=205, message='Failed to load murmur.yaml manifest', original_error=e)

        raise MurError(
            code=209,
            message='murmur.yaml manifest not found',
            detail='The murmur.yaml manifest file was not found in the current directory',
        )

    def _ensure_authenticated(self) -> None:
        """Ensure the user is authenticated before proceeding.

        Raises:
            MurError: If authentication fails
        """
        # Get the auth manager from the registry adapter
        auth_manager = AuthenticationManager.create(verbose=self.verbose)

        if not auth_manager.is_authenticated():
            raise MurError(
                code=508,
                message='Authentication Required',
                detail="You must be logged in to publish artifacts. Run 'mur login' first.",
            )

    def _load_murmur_yaml_from_artifact(self) -> ArtifactManifest:
        """Load build manifest from murmur-build.yaml.

        For build command: Looks in current directory
        For publish command: Looks in artifact entry folder

        Returns:
            ArtifactManifest: Artifact manifest from the build manifest.

        Raises:
            MurError: If murmur-build.yaml is not found or if manifest validation fails.
        """
        if self.command_name == 'build':
            # For build command, look in current directory
            manifest_file_path = self.current_dir / 'murmur-build.yaml'

            if manifest_file_path.exists():
                try:
                    logger.debug(f'Loading manifest from {manifest_file_path}')
                    manifest = ArtifactManifest(manifest_file_path, is_build_manifest=True)
                    logger.debug('Successfully loaded manifest')
                    return manifest
                except MurError as e:
                    logger.debug(f'{e}')
                    raise

            raise MurError(
                code=201,
                message='murmur-build.yaml not found',
                detail='The murmur-build.yaml manifest file was not found in the current directory',
            )

        else:
            # For other commands, look in both possible artifact directory structures
            for artifact_type in ['agent', 'tool']:
                # Get normalized name from manifest from pre-build manifest
                pre_build_manifest_path = self.current_dir / 'murmur-build.yaml'
                if not pre_build_manifest_path.exists():
                    raise

                pre_build_manifest = ArtifactManifest(pre_build_manifest_path, is_build_manifest=True)
                normalized_artifact_name = normalize_package_name(pre_build_manifest.name)

                # Try path with artifact name directory
                artifact_path1 = (
                    self.current_dir
                    / normalized_artifact_name
                    / 'src'
                    / 'murmur'
                    / f'{artifact_type}s'
                    / normalized_artifact_name
                )
                # Try direct path
                artifact_path2 = self.current_dir / 'src' / 'murmur' / f'{artifact_type}s' / normalized_artifact_name
                for artifact_entry_path in [artifact_path1, artifact_path2]:
                    manifest_file_path = artifact_entry_path / 'murmur-build.yaml'
                    if manifest_file_path.exists():
                        try:
                            logger.debug(f'Loading manifest from {manifest_file_path}')
                            manifest = ArtifactManifest(manifest_file_path, is_build_manifest=True)
                            logger.debug('Successfully loaded manifest')
                            return manifest
                        except MurError:
                            raise

            raise MurError(
                code=201,
                message='murmur-build.yaml not found',
                detail='The murmur-build.yaml manifest file was not found in the artifact directory',
            )
