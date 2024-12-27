import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class RegistryAdapter(ABC):
    """Base adapter for registry interactions.

    This abstract class defines the interface for registry adapters that handle
    artifact publishing and package index management.

    Args:
        verbose (bool, optional): Enable verbose logging output. Defaults to False.
    """

    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        if verbose:
            logger.setLevel(logging.DEBUG)

    @abstractmethod
    def publish_artifact(
        self,
        artifact_type: str,
        name: str,
        version: str,
        description: str,
        metadata: dict[str, Any],
        file_path: Path | str,
    ) -> dict[str, Any]:
        """Publish an artifact to the registry.

        Args:
            artifact_type (str): Type of artifact being published
            name (str): Name of the artifact
            version (str): Version string of the artifact
            description (str): Description of the artifact
            metadata (dict[str, Any]): Additional metadata for the artifact
            file_path (Path | str): Path to the artifact file to publish

        Returns:
            dict[str, Any]: Response data from the registry after publishing

        Raises:
            NotImplementedError: This is an abstract method that must be implemented
        """
        pass

    @abstractmethod
    def get_package_indexes(self) -> list[str]:
        """Get list of package index URLs for installation.

        Returns:
            list[str]: List of PyPI-compatible index URLs in priority order

        Raises:
            NotImplementedError: This is an abstract method that must be implemented
        """
        pass
