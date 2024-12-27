import logging
import subprocess
import sys
from dataclasses import dataclass
from importlib.util import find_spec
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

from ..utils.constants import REQUIRED_BASE_FIELDS, REQUIRED_TOOL_FIELDS

logger = logging.getLogger(__name__)


@dataclass
class PackageMetadata:
    """Package metadata from murmur.yaml.

    Args:
        name: Package name
        version: Package version string
        description: Package description
        metadata: Additional package metadata dictionary
        dependencies: Optional list of package dependencies
    """

    name: str
    version: str
    description: str
    metadata: dict[str, Any]
    dependencies: list[str] | None = None


class ConfigurationError(Exception):
    """Raised when configuration validation fails.

    This exception is raised when package configuration validation fails,
    such as missing required fields or invalid YAML format.
    """

    pass


# Add new constants at the top
REQUIRED_MANIFEST_FIELDS = {'name', 'version'}  # Basic fields for installation manifest
REQUIRED_BUILD_FIELDS = REQUIRED_BASE_FIELDS  # Keep existing build manifest requirements


class PackageConfig:
    """Handles package configuration loading and validation.

    This class manages loading and validating murmur package configuration files,
    supporting both build manifests (murmur-build.yaml) and installation manifests
    (murmur.yaml).
    """

    def __init__(self, config_path: Path | str, is_build_manifest: bool = True) -> None:
        """Initialize package configuration.

        Args:
            config_path: Path to murmur.yaml configuration file
            is_build_manifest: Whether this is a build manifest (murmur-build.yaml)
                             or an installation manifest (murmur.yaml)
        """
        self.config_path = Path(config_path)
        self.is_build_manifest = is_build_manifest

    @property
    def name(self):
        """str: The package name from configuration."""
        return self._create_metadata().name

    @property
    def version(self):
        """str: The package version from configuration."""
        return self._create_metadata().version

    @property
    def description(self):
        """str: The package description from configuration."""
        return self._create_metadata().description

    @property
    def metadata(self):
        """dict: Additional package metadata from configuration."""
        return self._create_metadata().metadata

    @property
    def type(self):
        """Get the artifact type from configuration data."""
        return self._load_and_validate()['type']

    @property
    def package_metadata(self):
        return self._create_metadata().metadata

    def _create_metadata(self):
        """Create package metadata from configuration data."""
        config = self._load_and_validate()
        if self.is_build_manifest:
            return PackageMetadata(
                name=config['name'],
                version=config['version'],
                description=config.get('description', ''),
                metadata=config.get('metadata', {}),
                dependencies=config.get('dependencies', []) if self._is_tool() else None,
            )
        else:
            return PackageMetadata(
                name=config['name'],
                version=config['version'],
                description='',  # Optional for installation manifest
                metadata={},  # Optional for installation manifest
            )

    def _is_tool(self, config: dict | None = None):
        """Check if the configuration is for a tool.

        Args:
            config: Optional configuration dictionary. If None, loads from file.

        Returns:
            bool: True if configuration is for a tool package.
        """
        data = config if config is not None else self._load_and_validate()
        return 'dependencies' in data

    def _load_and_validate(self) -> dict:
        """Load and validate the murmur configuration file."""
        if not self.config_path.exists():
            raise ConfigurationError(f'Configuration file not found: {self.config_path}')

        try:
            yaml = YAML()
            with open(self.config_path) as f:
                config_data = yaml.load(f)
        except Exception as e:
            raise ConfigurationError(f'Invalid YAML format: {e}')

        if not config_data:
            raise ConfigurationError('Configuration file is empty')

        # Choose validation rules based on manifest type
        if self.is_build_manifest:
            required_fields = REQUIRED_TOOL_FIELDS if self._is_tool(config_data) else REQUIRED_BASE_FIELDS
        else:
            required_fields = REQUIRED_MANIFEST_FIELDS

        missing_fields = required_fields - set(config_data.keys())

        if missing_fields:
            raise ConfigurationError(f"Missing required fields: {', '.join(missing_fields)}")

        return config_data


class BuildError(Exception):
    """Raised when package building fails.

    This exception is raised for build-related errors such as missing dependencies,
    invalid project structure, or build command failures.
    """

    pass


@dataclass
class BuildResult:
    """Results from a package build operation.

    Args:
        dist_dir: Path to the distribution directory containing built packages
        package_files: List of built package filenames
        build_output: String output from the build process
    """

    dist_dir: Path
    package_files: list[str]
    build_output: str


class PackageBuilder:
    """Handles Python package building operations.

    This class manages the building of Python packages, including validation
    of project structure and execution of build commands.
    """

    def __init__(self, project_dir: Path | str, verbose: bool = False) -> None:
        """Initialize package builder.

        Args:
            project_dir: Directory containing the Python project
            verbose: Whether to output verbose logging

        Raises:
            BuildError: If project directory doesn't exist
        """
        self.project_dir = Path(project_dir)
        self.verbose = verbose

        if not self.project_dir.exists():
            raise BuildError(f'Project directory not found: {self.project_dir}')

        if verbose:
            logger.setLevel(logging.DEBUG)

    def _validate_project_structure(self) -> None:
        """Validate the project structure before building.

        Raises:
            BuildError: If the project structure is invalid
        """
        pyproject_file = self.project_dir / 'pyproject.toml'
        if not pyproject_file.exists():
            raise BuildError('pyproject.toml not found in project directory')

        # Validate murmur namespace structure
        src_dir = self.project_dir / 'src' / 'murmur'
        if not src_dir.exists():
            raise BuildError('Invalid project structure: missing src/murmur directory')

        # Check for build dependencies
        if not find_spec('build'):
            raise BuildError("Required 'build' module not found. " 'Install it with: pip install build')

    def build(self, artifact_type: str) -> BuildResult:
        """Build the package.

        Args:
            artifact_type: Type of artifact to build

        Returns:
            BuildResult: Results from the build operation

        Raises:
            BuildError: If the build process fails
        """
        self._validate_project_structure()
        if self.verbose:
            logger.info(f'Building {artifact_type} package...')
        logger.debug('Starting build process...')

        try:
            result = subprocess.run(
                [sys.executable, '-m', 'build'],
                cwd=self.project_dir,
                capture_output=True,
                text=True,
                check=False,
            )  # nosec B603

            if result.returncode != 0:
                error_msg = f'Build command failed with exit code {result.returncode}:\n'
                if result.stdout:
                    error_msg += f'\nStdout:\n{result.stdout}'
                if result.stderr:
                    error_msg += f'\nStderr:\n{result.stderr}'
                raise BuildError(error_msg)

            logger.debug(f'Build stdout:\n{result.stdout}')
            logger.debug(f'Successfully built {artifact_type}')

        except subprocess.CalledProcessError as e:
            error_msg = 'Build process error:\n'
            if e.stdout:
                error_msg += f'\nStdout:\n{e.stdout.decode()}'
            if e.stderr:
                error_msg += f'\nStderr:\n{e.stderr.decode()}'
            raise BuildError(error_msg)
        except Exception as e:
            raise BuildError(f'Unexpected build error: {e!s}')

        dist_dir, package_files = self._get_build_artifacts()
        if self.verbose:
            logger.info(f"Built package files: {', '.join(package_files)}")

        return BuildResult(dist_dir=dist_dir, package_files=package_files, build_output=result.stdout)

    def _get_build_artifacts(self) -> tuple[Path, list[str]]:
        """Get the built package files from the dist directory.

        Returns:
            tuple: A tuple containing:
                - Path: The dist directory path
                - list[str]: List of package filenames

        Raises:
            BuildError: If no build artifacts are found or dist directory is missing
        """
        dist_dir = self.project_dir / 'dist'
        if not dist_dir.exists():
            raise BuildError("Build failed: 'dist' directory not found")

        package_files = [f.name for f in dist_dir.iterdir() if f.suffix in ('.whl', '.tar.gz', '.tar')]

        if self.verbose and package_files:
            logger.debug(f'Found package files: {package_files}')

        if not package_files:
            raise BuildError("Build failed: No package files found in 'dist' directory")

        return dist_dir, package_files
