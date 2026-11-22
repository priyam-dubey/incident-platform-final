"""Authentication and workspace-authorization dependencies."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException, Request, status

from app.config import Settings, get_settings
from app.repository import ROLE_RANK, Repository
from app.security import decode_access_token


def get_repo(request: Request) -> Repository:
    return request.app.state.repo


def current_user(
    authorization: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
    repo: Repository = Depends(get_repo),
) -> dict:
    unauth = HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated", headers={"WWW-Authenticate": "Bearer"})
    if not authorization or not authorization.lower().startswith("bearer "):
        raise unauth
    user_id = decode_access_token(authorization[7:].strip(), settings.auth_secret_key)
    if user_id is None:
        raise unauth
    user = repo.get_user(user_id)
    if user is None:
        raise unauth
    return user


@dataclass
class WorkspaceContext:
    workspace_id: uuid.UUID
    user: dict
    role: str
    is_demo: bool


def workspace_access(min_role: str = "viewer"):
    """Dependency factory: requires membership with at least `min_role`.

    Non-members get 404 (not 403) so workspace existence is not disclosed.
    """

    def dep(workspace_id: uuid.UUID, user: dict = Depends(current_user), repo: Repository = Depends(get_repo)) -> WorkspaceContext:
        m = repo.get_membership(workspace_id, user["id"])
        if m is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Workspace not found")
        if ROLE_RANK[m["role"]] < ROLE_RANK[min_role]:
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Requires {min_role} role or higher")
        return WorkspaceContext(workspace_id, user, m["role"], m["is_demo"])

    return dep
