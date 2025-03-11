"""Data models for API requests and responses."""

from typing import Optional, Dict, Any
from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    """Login request payload."""
    username: str
    password: str
    grant_type: str = "password"


class UserConfig(BaseModel):
    """User configuration model."""
    id: str | None = None
    username: str | None = None 
    email: str | None = None
    last_sign_in_at: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class LoginResponse(BaseModel):
    """Login response data."""
    access_token: str
    refresh_token: Optional[str] = None
    token_type: str = "bearer"
    user: Optional[UserConfig] = None
