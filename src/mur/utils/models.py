"""Data models for API requests and responses."""

from typing import Any, Optional

from pydantic import BaseModel, Field

from ..core.packaging import ArtifactManifest


class LoginRequest(BaseModel):
    """Login request payload."""

    username: str
    password: str
    grant_type: str = 'password'


class UserConfig(BaseModel):
    """User configuration model."""

    id: str | None = None
    username: str | None = None
    email: str | None = None
    last_sign_in_at: str | None = None
    created_at: str | None = None


class LoginResponse(BaseModel):
    """Login response data."""

    access_token: str
    refresh_token: Optional[str] = None
    token_type: str = Field(default='bearer', description='OAuth token type')
    user: Optional[UserConfig] = None


class ArtifactPublishRequest(BaseModel):
    """Request model for publishing an artifact."""

    name: str
    version: str
    type: str
    description: Optional[str] = None
    author: Optional[str] = None
    metadata_version: Optional[str] = '2.1'
    summary: Optional[str] = None
    description_content_type: Optional[str] = None
    keywords: Optional[list[str]] = None
    author_email: Optional[str] = None
    maintainer: Optional[str] = None
    maintainer_email: Optional[str] = None
    license_expression: Optional[str] = None
    license_file: Optional[list[str]] = None
    classifier: Optional[list[str]] = None
    requires_dist: Optional[list[str]] = None
    requires_python: Optional[str] = None
    requires_external: Optional[list[str]] = None
    project_url: Optional[list[str]] = None
    provides_extra: Optional[list[str]] = None
    dependencies: Optional[list[str]] = None
    platform: Optional[list[str]] = None
    supported_platform: Optional[list[str]] = None
    dynamic: Optional[list[str]] = None
    metadata: Optional[dict[str, Any]] = None

    @classmethod
    def from_manifest(cls, manifest: ArtifactManifest) -> 'ArtifactPublishRequest':
        """Create a request model from an artifact manifest."""
        manifest_dict = manifest.to_dict()

        # Ensure required fields are present
        if 'type' not in manifest_dict:
            manifest_dict['type'] = manifest.type

        # Convert dependencies to requires_dist if present
        if 'dependencies' in manifest_dict and isinstance(manifest_dict['dependencies'], list):
            manifest_dict['requires_dist'] = manifest_dict.get('dependencies', [])

        return cls(**manifest_dict)


class SignedUrlInfo(BaseModel):
    """Information about a signed URL for file upload."""

    name: str
    normalized_name: str
    distribution_name: str
    version: str
    tags: str = ''
    file_type: str
    signed_url: str


class ArtifactPublishResponse(BaseModel):
    """Response model for artifact publishing."""

    name: str
    normalized_name: str
    version: str
    signed_upload_urls: list[SignedUrlInfo]


class Account(BaseModel):
    """Model representing a user account."""

    id: str
    updated_at: str
    created_at: str
    name: str


# Update this model to be a list type alias instead of a wrapper
AccountListResponse = list[Account]

# Resolve forward references
ArtifactPublishRequest.update_forward_refs()
