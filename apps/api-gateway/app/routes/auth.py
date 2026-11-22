from __future__ import annotations

import logging

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Request, Response, status

from app.config import Settings, get_settings
from app.deps import current_user, get_repo
from app.repository import DuplicateError, Repository
from app.schemas import (
    ForgotPasswordRequest, LoginRequest, ProfileUpdate, ResetPasswordRequest, SignupRequest,
)
from app.security import (
    create_access_token, hash_password, new_opaque_token, sha256_hex, verify_password,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/auth", tags=["auth"])
REFRESH_COOKIE = "refresh_token"
# Precomputed hash so login timing does not reveal whether an email exists.
_DUMMY_HASH = hash_password("not-a-real-password-0")


def _user_out(u: dict) -> dict:
    return {"id": str(u["id"]), "email": u["email"], "display_name": u["display_name"], "email_verified": u["email_verified"]}


def _limit(request: Request, settings: Settings) -> None:
    ip = request.client.host if request.client else "unknown"
    if not request.app.state.auth_limiter.allow(ip):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many attempts; try again shortly")


def _issue_session(response: Response, request: Request, repo: Repository, settings: Settings, user: dict) -> dict:
    raw, hashed = new_opaque_token()
    repo.create_session(user["id"], hashed, settings.refresh_token_ttl_seconds, request.headers.get("user-agent"))
    _set_cookie(response, raw, settings)
    return {
        "access_token": create_access_token(user["id"], settings.auth_secret_key, settings.access_token_ttl_seconds),
        "token_type": "bearer", "expires_in": settings.access_token_ttl_seconds, "user": _user_out(user),
    }


def _set_cookie(response: Response, raw: str, settings: Settings) -> None:
    response.set_cookie(
        REFRESH_COOKIE, raw, max_age=settings.refresh_token_ttl_seconds, httponly=True,
        secure=settings.cookie_secure, samesite=settings.cookie_samesite, path="/v1/auth",
    )


@router.post("/signup", status_code=201)
def signup(body: SignupRequest, request: Request, response: Response,
           repo: Repository = Depends(get_repo), settings: Settings = Depends(get_settings)):
    _limit(request, settings)
    try:
        user = repo.create_user(body.email, hash_password(body.password), body.display_name)
    except DuplicateError:
        raise HTTPException(status.HTTP_409_CONFLICT, "An account with this email already exists") from None
    ws = repo.create_workspace(user["id"], body.workspace_name)
    repo.audit(ws["id"], user["id"], "user.signup", "user", str(user["id"]))
    result = _issue_session(response, request, repo, settings, user)
    result["workspace"] = {"id": str(ws["id"]), "name": ws["name"], "role": "owner"}
    return result


@router.post("/login")
def login(body: LoginRequest, request: Request, response: Response,
          repo: Repository = Depends(get_repo), settings: Settings = Depends(get_settings)):
    _limit(request, settings)
    user = repo.get_user_by_email(body.email)
    ok = verify_password(body.password, user["password_hash"] if user else _DUMMY_HASH)
    if not user or not ok:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")
    return _issue_session(response, request, repo, settings, user)


def _require_csrf_header(x_requested_with: str | None) -> None:
    # Cookie-authenticated endpoints require a custom header, which cross-site
    # forms cannot send; combined with SameSite and a CORS allow-list this blocks CSRF.
    if x_requested_with != "incident-platform":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Missing CSRF header")


@router.post("/refresh")
def refresh(request: Request, response: Response,
            refresh_token: str | None = Cookie(default=None, alias=REFRESH_COOKIE),
            x_requested_with: str | None = Header(default=None),
            repo: Repository = Depends(get_repo), settings: Settings = Depends(get_settings)):
    _require_csrf_header(x_requested_with)
    if not refresh_token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "No session")
    raw, hashed = new_opaque_token()
    user_id = repo.rotate_session(sha256_hex(refresh_token), hashed, settings.refresh_token_ttl_seconds)
    if user_id is None:
        response.delete_cookie(REFRESH_COOKIE, path="/v1/auth")
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired")
    user = repo.get_user(user_id)
    _set_cookie(response, raw, settings)
    return {
        "access_token": create_access_token(user_id, settings.auth_secret_key, settings.access_token_ttl_seconds),
        "token_type": "bearer", "expires_in": settings.access_token_ttl_seconds, "user": _user_out(user),
    }


@router.post("/logout", status_code=204)
def logout(response: Response, refresh_token: str | None = Cookie(default=None, alias=REFRESH_COOKIE),
           x_requested_with: str | None = Header(default=None), repo: Repository = Depends(get_repo)):
    _require_csrf_header(x_requested_with)
    if refresh_token:
        repo.revoke_session(sha256_hex(refresh_token))
    response.delete_cookie(REFRESH_COOKIE, path="/v1/auth")
    response.status_code = 204


@router.get("/me")
def me(user: dict = Depends(current_user), repo: Repository = Depends(get_repo)):
    return {**_user_out(user), "workspaces": [
        {"id": str(w["id"]), "name": w["name"], "role": w["role"], "is_demo": w["is_demo"]}
        for w in repo.list_workspaces_for_user(user["id"])
    ]}


@router.patch("/me")
def update_me(body: ProfileUpdate, user: dict = Depends(current_user), repo: Repository = Depends(get_repo)):
    return _user_out(repo.update_user_profile(user["id"], body.display_name))


@router.post("/forgot-password", status_code=202)
def forgot_password(body: ForgotPasswordRequest, request: Request,
                    repo: Repository = Depends(get_repo), settings: Settings = Depends(get_settings)):
    """Always 202 (no account enumeration). No email provider is wired yet, so in
    non-development environments the token is not delivered anywhere."""
    _limit(request, settings)
    user = repo.get_user_by_email(body.email)
    result: dict = {"detail": "If the account exists, reset instructions have been issued."}
    if user:
        raw, hashed = new_opaque_token()
        repo.create_reset_token(user["id"], hashed, settings.password_reset_ttl_seconds)
        if settings.environment == "development":
            result["dev_reset_token"] = raw  # development convenience only
        else:
            logger.warning("password_reset_requested_but_no_email_provider_configured")
    return result


@router.post("/reset-password")
def reset_password(body: ResetPasswordRequest, request: Request,
                   repo: Repository = Depends(get_repo), settings: Settings = Depends(get_settings)):
    _limit(request, settings)
    user_id = repo.consume_reset_token(sha256_hex(body.token))
    if user_id is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid or expired reset token")
    repo.set_password(user_id, hash_password(body.new_password))
    repo.revoke_all_sessions(user_id)
    return {"detail": "Password updated. Please log in."}
