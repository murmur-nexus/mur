import logging
import shutil
from pathlib import Path

import click
from ruamel.yaml import YAML

from .base import ArtifactCommand

logger = logging.getLogger(__name__)


class BuildCommand(ArtifactCommand):
    """Handles artifact building.

    This class manages the process of building Murmur artifacts (agents or tools)
    by creating the necessary directory structure and configuration files.

    Attributes:
        verbose (bool): Whether to enable verbose output.
        current_dir (Path): The current working directory.
        yaml (YAML): Configured YAML parser instance.
        build_manifest (dict): The loaded build manifest configuration.
        artifact_type (str): Type of artifact ('agent' or 'tool').
        config (dict): The build configuration (alias for build_manifest).
    """

    def __init__(self, verbose: bool = False) -> None:
        """Initialize build command.

        Args:
            verbose: Whether to enable verbose output
        """
        self.verbose = verbose
        self.current_dir = self.get_current_dir()
        self.yaml = self._configure_yaml()

        # Load config and determine artifact type
        self.build_manifest = self._load_build_manifest()
        self.artifact_type = self.build_manifest.get('type')
        if self.artifact_type not in ['agent', 'tool']:
            raise click.ClickException(
                f"Invalid artifact type '{self.artifact_type}' in murmur-build.yaml. "
                "Must be either 'agent' or 'tool'."
            )
        super().__init__(self.artifact_type, verbose)
        self.config = self.build_manifest

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

    def _load_build_manifest(self) -> dict:
        """Load manifest from murmur-build.yaml.

        Returns:
            dict: Manifest configuration dictionary.

        Raises:
            click.ClickException: If manifest file is missing or invalid YAML.
        """
        manifest_file = self.current_dir / 'murmur-build.yaml'
        if not manifest_file.exists():
            raise click.ClickException('murmur-build.yaml not found in current directory')

        try:
            with open(manifest_file) as f:
                return self.yaml.load(f)
        except Exception as e:
            raise click.ClickException(f'Failed to load murmur-build.yaml: {e}')

    def _create_directory_structure(self, artifact_path: Path) -> None:
        """Create the artifact directory structure.

        Creates the necessary package directories and files for the artifact,
        including the murmur namespace package structure and source files.
        If source files exist in the current directory, they will be copied over.
        If no source files exist, a default main.py will be created.

        Args:
            artifact_path (Path): Root path for new artifact.

        Raises:
            click.ClickException: If directory creation fails, required files are missing,
                or source file copying fails.
        """
        try:
            # Create murmur namespace package structure
            src_path = artifact_path / 'src' / 'murmur' / f'{self.artifact_type}s'
            src_path.mkdir(parents=True, exist_ok=True)

            package_path = src_path / artifact_path.name
            package_path.mkdir(parents=True, exist_ok=True)

            # Create an empty __init__.py
            with open(package_path / '__init__.py', 'w') as f:
                pass

            logger.debug(f'Created directory structure at {artifact_path}')

            # Handle source files
            if (self.current_dir / 'src').exists():
                src_files = list((self.current_dir / 'src').glob('*.py'))
                if src_files and not (self.current_dir / 'src' / 'main.py').exists():
                    raise click.ClickException(
                        'Source files found but main.py is missing. ' 'main.py is required as the default entry point.'
                    )
                elif (main_file := self.current_dir / 'src' / 'main.py').exists():
                    shutil.copy(main_file, package_path)
                    if self.verbose:
                        logger.info('Copying source files...')
                    logger.debug(f'Copied main.py to {package_path}')
            else:
                # Create default main.py if no source files exist
                with open(package_path / 'main.py', 'w') as f:
                    f.write(f'def {artifact_path.name}():\n')
                    f.write('    pass\n')
                logger.debug(f'Created default main.py with {artifact_path.name} function')

        except Exception as e:
            raise click.ClickException(f'Failed to create directory structure: {e}')

    def _create_project_files(self, artifact_path: Path) -> None:
        """Create all necessary project files.

        Creates README.md and pyproject.toml files for the artifact with appropriate
        content based on the build configuration.

        Args:
            artifact_path (Path): Root path for new artifact.

        Raises:
            click.ClickException: If file creation fails.
        """
        try:
            # Create README.md
            with open(artifact_path / 'README.md', 'w') as f:
                f.write(f"# {self.config['name']}\n\n{self.config.get('description', '')}")

            # Create pyproject.toml
            with open(artifact_path / 'pyproject.toml', 'w') as f:
                f.write(self._generate_pyproject_toml())

            logger.debug('Created project files')
            if self.verbose:
                logger.info('Created project configuration files')

        except Exception as e:
            raise click.ClickException(f'Failed to create project files: {e}')

    def _generate_pyproject_toml(self) -> str:
        """Generate pyproject.toml content.

        Combines all project configuration sections into a complete pyproject.toml file.

        Returns:
            str: Complete content for pyproject.toml file.
        """
        content = []
        content.extend(self._generate_build_system())
        content.extend(self._generate_project_section())
        content.extend(self._generate_project_urls())
        content.extend(self._generate_build_targets())
        return '\n'.join(content)

    def _generate_build_system(self) -> list[str]:
        """Generate build-system section.

        Returns:
            list[str]: Lines for the build-system section of pyproject.toml.
        """
        return [
            '[build-system]',
            'requires = ["hatchling<=1.26.3"]  # pypiserver 2.3.2 requires hatchling metadata version up to version 2.3',
            'build-backend = "hatchling.build"',
            '',
        ]

    def _generate_project_section(self) -> list[str]:
        """Generate project section including metadata.

        Returns:
            list[str]: Lines for the project section of pyproject.toml, including
                name, version, description, and other metadata.
        """
        content = ['[project]', f'name = "{self.config["name"].lower()}"', f'version = "{self.config["version"]}"']

        metadata = self.config.get('metadata', {})

        # Add optional fields
        if description := self.config.get('description'):
            content.append(f'description = "{description}"')

        if requires_python := metadata.get('requires_python'):
            content.append(f'requires-python = "{requires_python}"')

        # Add author information
        content.extend(self._generate_authors(metadata))

        # Add license
        if license_type := metadata.get('license'):
            content.append(f'license = {{text = "{license_type}"}}')

        # Add classifiers
        content.extend(self._generate_classifiers(license_type))
        content.append('readme = "README.md"')

        # Add dependencies
        content.extend(self._generate_dependencies())

        return content

    def _generate_authors(self, metadata: dict) -> list[str]:
        """Generate authors section if author info exists.

        Creates the authors section of pyproject.toml based on provided metadata.

        Args:
            metadata (dict): Dictionary containing author metadata including 'author'
                and optional 'email' fields.

        Returns:
            list[str]: Lines for the authors section of pyproject.toml.
        """
        if author := metadata.get('author'):
            email = metadata.get('email', '')
            author_line = '{name = "' + author + '"'
            if email:
                author_line += f', email = "{email}"'
            author_line += '}'
            return ['authors = [', f'    {author_line}', ']']
        return []

    def _generate_classifiers(self, license_type: str | None) -> list[str]:
        """Generate classifiers section.

        Args:
            license_type: Type of license for the project, if any.

        Returns:
            list[str]: Lines for the classifiers section of pyproject.toml.
        """
        classifiers = [
            'classifiers = [',
            '    "Programming Language :: Python",',
            '    "Programming Language :: Python :: 3",',
            '    "Programming Language :: Python :: 3 :: Only",',
            '    "Intended Audience :: Developers",',
            '    "Intended Audience :: Information Technology",',
            '    "Intended Audience :: System Administrators",',
        ]

        if license_type:
            classifiers.append(f'    "License :: OSI Approved :: {license_type} License",')

        classifiers.extend(
            [
                '    "Topic :: Software Development :: Libraries :: Python Modules",',
                '    "Topic :: Scientific/Engineering :: Artificial Intelligence",',
                ']',
            ]
        )
        return classifiers

    def _generate_dependencies(self) -> list[str]:
        """Generate dependencies section.

        Returns:
            list[str]: Lines for the dependencies section of pyproject.toml.
        """
        if dependencies := self.config.get('dependencies', []):
            return ['dependencies = [', *[f'    "{dep}",' for dep in dependencies], ']']
        return ['dependencies = []']

    def _generate_project_urls(self) -> list[str]:
        """Generate project.urls section.

        Returns:
            list[str]: Lines for the project.urls section of pyproject.toml.
        """
        valid_url_types = {'repository', 'documentation', 'project'}
        urls = self.config.get('metadata', {}).get('urls', {})
        valid_urls = {
            url_type: url_list[0] for url_type, url_list in urls.items() if url_type in valid_url_types and url_list
        }

        if not valid_urls:
            return []

        content = ['', '[project.urls]']
        for url_type, url in valid_urls.items():
            title = url_type.capitalize()
            content.append(f'{title} = "{url}"')
        return content

    def _generate_build_targets(self) -> list[str]:
        """Generate build targets section.

        Returns:
            list[str]: Lines for the build targets section of pyproject.toml.
        """
        return ['', '[tool.hatch.build.targets.wheel]', 'packages = ["src/murmur"]']

    def _write_filtered_build_manifest(self, artifact_path: Path) -> None:
        """Filter and write configuration to murmur-build.yaml.

        Writes a filtered version of the configuration to the artifact's
        murmur-build.yaml file, including only the relevant keys for the
        artifact type. For agents, this includes the 'instructions' key.

        Args:
            artifact_path (Path): Path to new artifact.

        Raises:
            click.ClickException: If writing config fails.
        """
        # Base allowed keys for all artifact types
        allowed_keys = {'name', 'version', 'type', 'description', 'dependencies', 'metadata'}

        # Add instructions key only for agent type
        if self.artifact_type == 'agent':
            allowed_keys.add('instructions')

        filtered_config = {k: v for k, v in self.config.items() if k in allowed_keys}

        package_entry_path = artifact_path / 'src' / 'murmur' / f'{self.artifact_type}s' / artifact_path.name

        try:
            with open(package_entry_path / 'murmur-build.yaml', 'w') as f:
                f.write('# This file is automatically generated based on murmur-build.yaml in the parent directory\n')
                self.yaml.dump(filtered_config, f)

            logger.debug(f'Written config keys to murmur-build.yaml: {list(filtered_config.keys())}')
        except Exception as e:
            raise click.ClickException(f'Failed to write murmur-build.yaml: {e}')

    def execute(self) -> None:
        """Execute the build command.

        Creates a new artifact project with the specified configuration,
        including directory structure, project files, and filtered config.
        If the artifact directory already exists, the build will be skipped.

        Raises:
            click.ClickException: If build process fails at any stage.
        """
        try:
            # Determine artifact path
            artifact_name = self.build_manifest['name'].lower().replace('-', '_')

            artifact_path = self.current_dir / artifact_name

            if artifact_path.exists():
                logger.info(
                    f"The {self.artifact_type} '{artifact_name}' has already been built in this directory. "
                    f'To rebuild, please remove the existing {artifact_name} directory first.'
                )
                return

            # Build artifact
            self._create_directory_structure(artifact_path)
            self._create_project_files(artifact_path)

            # Write filtered version of build manifest
            self._write_filtered_build_manifest(artifact_path)

            self.log_success(
                f"Successfully built {self.artifact_type} "
                f"{self.build_manifest['name']} {self.build_manifest['version']}"
            )

        except Exception as e:
            self.handle_error(e, f'Failed to build {self.artifact_type}')


def build_command() -> click.Command:
    """Create the build command for Click.

    Returns:
        Click command for building artifacts
    """

    @click.command()
    @click.option('--verbose', '-v', is_flag=True, help='Enable verbose output')
    def build(verbose: bool) -> None:
        """Build a new artifact project."""
        cmd = BuildCommand(verbose)
        cmd.execute()

    return build
