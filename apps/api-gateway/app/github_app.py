"""GitHub App integration: app auth, installation tokens, webhook verification, safe archive download.

Nothing here runs repository code. Archives are downloaded as tarballs and extracted defensively
(no absolute paths, no `..`, no links or device files, bounded size and file count).
"""

from __future__ import annotations

import hashlib
import hmac
import io
import os
import shutil
import tarfile
import time
from pathlib import Path

import httpx
import jwt

from app.config import Settings


class GitHubNotConfigured(Exception):
    pass


class GitHubError(Exception):
    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class UnsafeArchive(Exception):
    pass


def _private_key(settings: Settings) -> str:
    if settings.github_app_private_key:
        return settings.github_app_private_key.replace("\\n", "\n")
    if settings.github_app_private_key_path and os.path.isfile(settings.github_app_private_key_path):
        return Path(settings.github_app_private_key_path).read_text()
    return ""


def missing(settings: Settings) -> list[str]:
    out = []
    if not settings.github_app_id:
        out.append("GITHUB_APP_ID")
    if not settings.github_app_slug:
        out.append("GITHUB_APP_SLUG")
    if not _private_key(settings):
        out.append("GITHUB_APP_PRIVATE_KEY or GITHUB_APP_PRIVATE_KEY_PATH")
    if not settings.github_webhook_secret:
        out.append("GITHUB_WEBHOOK_SECRET")
    return out


def status(settings: Settings) -> dict:
    m = missing(settings)
    return {"state": "configured" if not m else "not_configured", "missing": m, "app_slug": settings.github_app_slug or None}


def verify_webhook(secret: str, body: bytes, signature_header: str | None) -> bool:
    if not secret or not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header)


def install_url(settings: Settings, state: str) -> str:
    return f"https://github.com/apps/{settings.github_app_slug}/installations/new?state={state}"


class GitHubClient:
    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None) -> None:
        if missing(settings):
            raise GitHubNotConfigured("GitHub App is not configured")
        self.s = settings
        self.http = httpx.Client(base_url=settings.github_api_url, timeout=30, transport=transport,
                                 headers={"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "incident-platform"})
        self._tokens: dict[int, tuple[str, float]] = {}

    def close(self) -> None:
        self.http.close()

    def app_jwt(self) -> str:
        now = int(time.time())
        return jwt.encode({"iat": now - 60, "exp": now + 540, "iss": self.s.github_app_id}, _private_key(self.s), algorithm="RS256")

    def _req(self, method: str, url: str, token: str, headers: dict | None = None, **kw) -> httpx.Response:
        r = self.http.request(method, url, headers={**(headers or {}), "Authorization": f"Bearer {token}"}, **kw)
        if r.status_code >= 400:
            raise GitHubError(f"GitHub API returned {r.status_code}", r.status_code)      # body never echoed (may contain details)
        return r

    def installation(self, installation_id: int) -> dict:
        return self._req("GET", f"/app/installations/{installation_id}", self.app_jwt()).json()

    def token(self, installation_id: int) -> str:
        cached = self._tokens.get(installation_id)
        if cached and cached[1] > time.time() + 60:
            return cached[0]
        data = self._req("POST", f"/app/installations/{installation_id}/access_tokens", self.app_jwt()).json()
        self._tokens[installation_id] = (data["token"], time.time() + 3000)
        return data["token"]

    def list_repositories(self, installation_id: int) -> list[dict]:
        tok, out, page = self.token(installation_id), [], 1
        while page <= 20:
            data = self._req("GET", "/installation/repositories", tok, params={"per_page": 100, "page": page}).json()
            out += data.get("repositories", [])
            if len(data.get("repositories", [])) < 100:
                break
            page += 1
        return out

    def head_sha(self, installation_id: int, full_name: str, ref: str) -> str:
        return self._req("GET", f"/repos/{full_name}/commits/{ref}", self.token(installation_id), headers={"Accept": "application/vnd.github.sha"}).text.strip()

    def download_snapshot(self, installation_id: int, full_name: str, sha: str, dest: str) -> int:
        """Download the tarball of one commit and extract it into `dest`. Returns the number of files."""
        tok = self.token(installation_id)
        limit = self.s.scan_max_archive_mb * 1024 * 1024
        buf = io.BytesIO()
        with self.http.stream("GET", f"/repos/{full_name}/tarball/{sha}", headers={"Authorization": f"Bearer {tok}"}, follow_redirects=True) as r:
            if r.status_code >= 400:
                raise GitHubError(f"GitHub archive download failed ({r.status_code})", r.status_code)
            for chunk in r.iter_bytes():
                buf.write(chunk)
                if buf.tell() > limit:
                    raise UnsafeArchive(f"Archive exceeds the {self.s.scan_max_archive_mb} MB limit")
        buf.seek(0)
        return safe_extract_tar(buf, dest, limit * 3, self.s.scan_max_files)


def safe_extract_tar(fileobj, dest: str, max_total_bytes: int, max_files: int) -> int:
    """Extract a gzip tarball, stripping the single top-level directory GitHub adds. Rejects anything suspicious."""
    root = os.path.realpath(dest)
    total = count = 0
    with tarfile.open(fileobj=fileobj, mode="r:gz") as tar:
        for m in tar:
            parts = Path(m.name).parts[1:]                    # drop "owner-repo-sha/"
            if not parts:
                continue
            if m.name.startswith("/") or ".." in Path(m.name).parts:
                raise UnsafeArchive("Archive contains an unsafe path")
            if m.issym() or m.islnk() or m.isdev() or m.isfifo():
                continue                                       # links/devices are skipped, never followed
            target = os.path.realpath(os.path.join(root, *parts))
            if target != root and not target.startswith(root + os.sep):
                raise UnsafeArchive("Archive entry escapes the extraction directory")
            if m.isdir():
                os.makedirs(target, exist_ok=True)
                continue
            if not m.isfile():
                continue
            count += 1
            total += m.size
            if count > max_files or total > max_total_bytes:
                raise UnsafeArchive("Archive is too large to scan")
            os.makedirs(os.path.dirname(target), exist_ok=True)
            src = tar.extractfile(m)
            if src is None:
                continue
            with open(target, "wb") as out:
                shutil.copyfileobj(src, out, 1024 * 1024)
            os.chmod(target, 0o644)                           # never keep an executable bit
    return count
