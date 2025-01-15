import logging
import re
import subprocess
import sys
from dataclasses import dataclass, field
from importlib.util import find_spec
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from packaging.specifiers import SpecifierSet
from packaging.utils import is_normalized_name
from packaging.version import InvalidVersion, Version
from ruamel.yaml import YAML

from ..utils.error_handler import MurError

logger = logging.getLogger(__name__)

REQUIRED_MANIFEST_FIELDS = {'name', 'version'}  # Basic fields for installation manifest
REQUIRED_BUILD_MANIFEST_FIELDS = REQUIRED_MANIFEST_FIELDS | {
    'type',
    'description',
    'metadata',
}


@dataclass
class ArtifactManifest:
    """Handles artifact manifest loading and validation.

    This class manages loading and validating murmur artifact manifest files,
    supporting both build manifests (murmur-build.yaml) and installation manifests
    (murmur.yaml).

    Args:
        manifest_file_path: Path to murmur.yaml manifest file
        is_build_manifest: Whether this is a build manifest (murmur-build.yaml)
                         or an installation manifest (murmur.yaml)

    Attributes:
        name: Artifact name (required)
        version: Artifact version string (required)
        type: Artifact type (required for build manifest)
        description: Artifact description (required for build manifest)
        dependencies: List of artifact dependencies (defaults to empty list)

        The following metadata fields are available as direct attributes when set:
            - metadata_version
            - dynamic
            - platform
            - supported_platform
            - summary
            - description_content_type
            - keywords
            - author
            - author_email
            - maintainer
            - maintainer_email
            - license_expression
            - license_file
            - classifier
            - requires_dist
            - requires_python
            - requires_external
            - project_url
            - provides_extra

    Note:
        Only metadata fields that are explicitly set in the manifest file will be
        present as attributes. Accessing non-existent metadata fields will raise
        an MurError.
    """

    manifest_file_path: Path | str
    is_build_manifest: bool = True

    # Core (mandatory) fields
    name: str = field(init=False)
    type: str = field(init=False)
    version: str = field(init=False)
    description: str = field(init=False)
    dependencies: list[str] = field(default_factory=list, init=False)

    # Hidden fields to store data internally
    _metadata: dict = field(default_factory=dict, init=False, repr=False)
    _manifest_data: dict = field(default_factory=dict, init=False, repr=False)  # Store raw manifest data

    def __post_init__(self):
        """Initialize the manifest data after dataclass initialization."""
        try:
            manifest_data = self._load_and_validate(Path(self.manifest_file_path))
        except MurError as e:
            e.handle()
        self._manifest_data = manifest_data  # Store the raw manifest data

        # Set core fields
        self.name = manifest_data['name']
        self.version = manifest_data['version']

        if self.is_build_manifest:
            self.type = manifest_data['type']
            self.description = manifest_data.get('description', '')
            self.dependencies = manifest_data.get('dependencies', [])

            # Validate and store metadata fields
            if 'metadata' in manifest_data:
                if self.dependencies:
                    manifest_data['metadata']['requires_dist'] = self.dependencies

                for key, value in manifest_data['metadata'].items():
                    if value is not None and value != [] and value != '':
                        try:
                            MetadataValidator.validate_field(key, value)
                            self._metadata[key] = value
                        except MurError as e:
                            e.context.debug_messages.append(f'field: {key}')
                            raise

    def __getattr__(self, name):
        """Enable access to metadata fields and raw manifest data."""
        if name in self._metadata:
            return self._metadata[name]
        if name in self._manifest_data:
            return self._manifest_data[name]
        raise MurError(
            code=207,
            message=f"'{self.__class__.__name__}' object has no attribute '{name}'",
            detail='The requested field is not present in the manifest.',
        )

    def get(self, key: str, default: Any = None) -> Any:
        """Get a value from the manifest data with a default fallback.

        Args:
            key: The key to look up
            default: Value to return if key is not found

        Returns:
            The value if found, otherwise the default value
        """
        return self._manifest_data.get(key, default)

    def _load_and_validate(self, manifest_file_path: Path) -> dict:
        """Load and validate the murmur manifest file.

        Raises:
            MurError: If the manifest file is not found, is empty, has invalid YAML format,
                      or is missing required fields.

        Returns:
            dict: The loaded and validated manifest data.
        """
        if not manifest_file_path.exists():
            raise MurError(
                code=201,
                message=f'Manifest file not found: {manifest_file_path}',
            )

        try:
            yaml = YAML()
            with open(manifest_file_path) as f:
                manifest_data = yaml.load(f)
        except Exception as e:
            raise MurError(
                code=204,
                message='Invalid YAML format',
                original_error=e,
            )

        if not manifest_data:
            raise MurError(
                code=204,
                message='Manifest file is empty',
            )

        # Choose validation rules based on manifest type
        if self.is_build_manifest:
            required_fields = REQUIRED_BUILD_MANIFEST_FIELDS
        else:
            required_fields = REQUIRED_MANIFEST_FIELDS

        missing_fields = required_fields - set(manifest_data.keys())

        if missing_fields:
            raise MurError(
                code=204,
                message='Missing required fields',
                detail=f"Missing fields: {', '.join(missing_fields)}.",
            )

        return manifest_data

    def to_dict(self) -> dict[str, Any]:
        """Convert manifest to a dictionary format suitable for serialization.

        Returns a flattened dictionary containing all manifest fields including metadata.
        Metadata fields are included at the root level rather than nested.

        Returns:
            dict[str, Any]: Flattened dictionary representation of the manifest.
        """
        data: dict[str, Any] = {
            'name': self.name,
            'version': self.version,
        }

        if self.is_build_manifest:
            data.update(
                {
                    'type': self.type,
                    'description': self.description,
                }
            )
            data['dependencies'] = self.dependencies

            # Flatten metadata fields into root level
            if self._metadata:
                data.update(self._metadata)

        return data


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


class ArtifactBuilder:
    """Handles Python artifact building operations.

    This class manages the building of Python artifacts, including validation
    of project structure and execution of build commands.
    """

    def __init__(self, project_dir: Path | str, verbose: bool = False) -> None:
        """Initialize artifact builder.

        Args:
            project_dir: Directory containing the Python project
            verbose: Whether to output verbose logging

        Raises:
            MurError: If project directory doesn't exist
        """
        self.project_dir = Path(project_dir)
        self.verbose = verbose

        if not self.project_dir.exists():
            raise MurError(code=206, message=f'Project directory not found: {self.project_dir}')

    def _validate_project_structure(self) -> None:
        """Validate the project structure before building.

        Raises:
            MurError: If the project structure is invalid
        """
        pyproject_file = self.project_dir / 'pyproject.toml'
        if not pyproject_file.exists():
            raise MurError(code=201, message='pyproject.toml not found in project directory')

        # Validate murmur namespace structure
        src_dir = self.project_dir / 'src' / 'murmur'
        if not src_dir.exists():
            raise MurError(code=206, message='Invalid project structure: missing src/murmur directory')

        # Check for build dependencies
        if not find_spec('build'):
            raise MurError(
                code=300, message="Required 'build' module not found", detail='Install it with: pip install build.'
            )

    def build(self, artifact_type: str) -> BuildResult:
        """Build the artifact.

        Args:
            artifact_type: Type of artifact to build

        Returns:
            BuildResult: Results from the build operation

        Raises:
            MurError: If the build process fails
        """
        self._validate_project_structure()
        if self.verbose:
            logger.info(f'Building {artifact_type} artifact...')
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
                raise MurError(
                    code=307,
                    message=f'Build command failed with exit code {result.returncode}',
                    debug_messages=[f'stdout: {result.stdout}', f'stderr: {result.stderr}'],
                )

            logger.debug(f'Build stdout:\n{result.stdout}')
            logger.debug(f'Successfully built {artifact_type}')

        except subprocess.CalledProcessError as e:
            error_msg = 'Build process error'
            detail = {}
            debug_messages = []
            if e.stdout:
                detail['stdout'] = e.stdout.decode()
                debug_messages.append(f'stdout: {e.stdout}')
            if e.stderr:
                detail['stderr'] = e.stderr.decode()
                debug_messages.append(f'stderr: {e.stderr}')
            raise MurError(code=307, message=error_msg, detail=detail, debug_messages=debug_messages)

        dist_dir, package_files = self._get_build_artifacts()
        if self.verbose:
            logger.info(f"Built package files: {', '.join(package_files)}")

        return BuildResult(dist_dir=dist_dir, package_files=package_files, build_output=result.stdout)

    def _is_package_file(self, file: Path) -> bool:
        # Check for wheel files
        if file.suffix == '.whl':
            return True
        # Check for source distributions
        return file.name.endswith(('.tar.gz', '.tar'))

    def _get_build_artifacts(self) -> tuple[Path, list[str]]:
        """Get the built package files from the dist directory.

        Returns:
            tuple: A tuple containing:
                - Path: The dist directory path
                - list[str]: List of package filenames

        Raises:
            MurError: If no build artifacts are found or dist directory is missing
        """
        dist_dir = self.project_dir / 'dist'
        if not dist_dir.exists():
            raise MurError(code=307, message="Directory 'dist' not found")

        package_files = [f.name for f in dist_dir.iterdir() if self._is_package_file(f)]

        if self.verbose and package_files:
            logger.info(f'Found {len(package_files)} package file(s).')

        if not package_files:
            raise MurError(code=307, message="No package files found in 'dist' directory")

        return dist_dir, package_files


class MetadataValidator:
    """Validates metadata fields according to their specific requirements.

    Each validation method should:
    - Return None if validation passes
    - Raise MurError with descriptive message if validation fails
    - Use 'pass' if no validation is currently implemented
    """

    @staticmethod
    def validate_author_email(value: str) -> None:
        """Validate email format."""
        email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not re.match(email_pattern, value):
            raise MurError(
                code=207,
                message='Invalid email format',
                detail=f'Got value: {value}.',
                debug_messages=[f'email_pattern: {email_pattern}'],
            )

    @staticmethod
    def validate_project_url(value: list[str]) -> None:
        """Validate list of URLs."""
        if not isinstance(value, list):
            raise MurError(
                code=207, message='Project URL must be a list of strings', detail=f'Got type: {type(value)}.'
            )

        for url in value:
            try:
                result = urlparse(url)
                if not all([result.scheme, result.netloc]):
                    raise MurError(code=207, message='Invalid URL format', detail=f'Got value: {url}.')
            except Exception as e:
                raise MurError(code=207, message='Invalid URL', detail=f'Got value: {url}.', original_error=e)

    @staticmethod
    def validate_requires_python(value: str) -> None:
        """Validate Python version specifier."""
        try:
            SpecifierSet(value)
        except Exception as e:
            raise MurError(
                code=207,
                message='Invalid Python version specifier',
                detail=f'Got value: {value}.',
                original_error=e,
            )

    @staticmethod
    def validate_metadata_version(value: str) -> None:
        """Validate metadata version format."""
        pass

    @staticmethod
    def validate_dynamic(value: list[str]) -> None:
        """Validate dynamic field values."""
        pass

    @staticmethod
    def validate_platform(value: list[str]) -> None:
        """Validate platform specifications."""
        pass

    @staticmethod
    def validate_supported_platform(value: list[str]) -> None:
        """Validate supported platform specifications."""
        pass

    @staticmethod
    def validate_summary(value: str) -> None:
        """Validate summary text."""
        pass

    @staticmethod
    def validate_description_content_type(value: str) -> None:
        """Validate content type format."""
        pass

    @staticmethod
    def validate_keywords(value: list[str]) -> None:
        """Validate keyword list."""
        pass

    @staticmethod
    def validate_author(value: str) -> None:
        """Validate author name."""
        pass

    @staticmethod
    def validate_maintainer(value: str) -> None:
        """Validate maintainer name."""
        pass

    @staticmethod
    def validate_maintainer_email(value: str) -> None:
        """Validate maintainer email format."""
        # Use same validation as author_email
        MetadataValidator.validate_author_email(value)

    @staticmethod
    def validate_license_expression(value: str) -> None:
        """Validate license expression format."""
        pass

    @staticmethod
    def validate_license_file(value: list[str]) -> None:
        """Validate license file paths."""
        pass

    @staticmethod
    def validate_classifier(value: list[str]) -> None:
        """Validate classifier strings."""
        pass

    @staticmethod
    def validate_requires_dist(value: list[str]) -> None:
        """Validate distribution requirements."""
        if not isinstance(value, list):
            raise MurError(
                code=207, message="Key 'requires_dist' must be a list of strings", detail=f'Got type: {type(value)}.'
            )

        for requirement in value:
            MetadataValidator._validate_single_requirement(requirement)

    @staticmethod
    def _validate_single_requirement(requirement: str) -> None:
        """Validate a single distribution requirement."""
        if not isinstance(requirement, str):
            raise MurError(
                code=207, message='Each requirement must be a string', detail=f'Invalid value: {requirement}.'
            )

        # Split requirement into package spec and environment marker
        parts = requirement.split(';')
        package_spec = parts[0].strip()

        try:
            MetadataValidator._validate_package_spec(package_spec)
            if len(parts) > 1:
                MetadataValidator._validate_environment_marker(parts[1].strip())
        except Exception as e:
            raise MurError(
                code=207,
                message='Invalid package specification',
                detail=f'Got value: {requirement}.',
                original_error=e,
            )

    @staticmethod
    def _validate_package_spec(package_spec: str) -> None:
        """Validate package specification part."""
        version_start = -1
        for operator in ['>=', '<=', '!=', '==', '~=', '>', '<']:
            pos = package_spec.find(operator)
            if pos != -1 and (version_start == -1 or pos < version_start):
                version_start = pos

        if version_start != -1:
            package_name = package_spec[:version_start].strip()
            version_part = package_spec[version_start:].strip()
        else:
            package_name = package_spec
            version_part = ''

        if not re.match(r'^[A-Za-z0-9][-A-Za-z0-9_.]*$', package_name):
            raise ValueError('Invalid package name format')

        if version_part:
            SpecifierSet(version_part)

    @staticmethod
    def _validate_environment_marker(marker: str) -> None:
        """Validate environment marker part."""
        if not re.match(r'^[\w\s]+ *(?:==|!=) *["\'][^"\']+["\']$', marker):
            raise MurError(code=207, message='Invalid environment marker', detail=f'Got value: {marker}')

    @staticmethod
    def validate_requires_external(value: list[str]) -> None:
        """Validate external requirements."""
        pass

    @staticmethod
    def validate_provides_extra(value: list[str]) -> None:
        """Validate provided extras."""
        pass

    @classmethod
    def validate_field(cls, field_name: str, value: Any) -> None:
        """Validate a specific metadata field.

        Args:
            field_name: Name of the metadata field
            value: Value to validate

        Raises:
            MurError: If validation fails
        """
        validator_name = f'validate_{field_name}'
        validator = getattr(cls, validator_name, None)

        if validator is None:
            raise MurError(
                code=207,
                message=f"No validator defined for field: '{field_name}'",
                detail=f'Got value: {value}.',
                debug_messages=[f'validator_name: {validator_name}'],
            )

        validator(value)


def normalize_package_name(project_name: str) -> str:
    """Normalize a project name to a valid Python package name according to PEP 8.

    Args:
        project_name: Original project/package name

    Returns:
        str: Normalized package name following PEP 8 conventions
    """
    # Replace invalid characters (including dots) with '_'
    name = re.sub(r'[^a-zA-Z0-9_]', '_', project_name.replace('-', '_').replace('.', '_'))
    # Remove any leading underscores or invalid characters
    name = re.sub(r'^_+', '', name)  # Remove leading underscores
    # Replace multiple consecutive underscores with a single one
    name = re.sub(r'__+', '_', name)
    # Ensure it starts with a valid character
    if not name or not name[0].isalpha():
        name = f'default_{name}'  # Default fallback if name becomes empty or starts with a digit
    name = name.lower()

    return name


def is_valid_artifact_name_version(name: str, version: str) -> None:
    """Validate the artifact name and version.

    Args:
        name: The artifact name to validate.
        version: The version string to validate.

    Raises:
        MurError: If the artifact name or version is invalid.
    """
    # Validate artifact name
    if not is_normalized_name(name):
        raise MurError(
            code=305,
            message=f"Invalid artifact name '{name}'",
            detail='Name must be lowercase, alphanumeric, and can include dashes or underscores but no spaces or special characters. No leading/trailing non-alphanumeric characters.',
            debug_messages=['PEP 423: https://peps.python.org/pep-0423/'],
        )

    # Validate version
    try:
        Version(version)
    except InvalidVersion:
        raise MurError(
            code=305,
            message=f"Invalid version '{version}'",
            detail="Version must follow semantic versioning (e.g., '1.0.0'). More info: https://www.semver.org",
        )
