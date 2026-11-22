import uuid

import pytest

pytestmark = pytest.mark.integration
CSRF = {"X-Requested-With": "incident-platform"}


def test_signup_creates_user_workspace_and_owner(client, make_user):
    u = make_user()
    me = client.get("/v1/auth/me", headers=u["headers"]).json()
    assert me["email"] == u["email"]
    assert me["workspaces"][0]["role"] == "owner"


def test_signup_rejects_weak_password_and_duplicate(client):
    email = f"dup-{uuid.uuid4().hex[:8]}@example.com"
    assert client.post("/v1/auth/signup", json={"email": email, "password": "short1"}).status_code == 422
    assert client.post("/v1/auth/signup", json={"email": email, "password": "alllettersnodigits"}).status_code == 422
    ok = client.post("/v1/auth/signup", json={"email": email, "password": "correct-horse-9"})
    assert ok.status_code == 201
    again = client.post("/v1/auth/signup", json={"email": email.upper(), "password": "correct-horse-9"})
    assert again.status_code == 409


def test_password_stored_hashed(client, make_user, db):
    u = make_user()
    h = db.execute("SELECT password_hash FROM users WHERE email=%s", (u["email"],)).fetchone()[0]
    assert h.startswith("$argon2") and "correct-horse" not in h


def test_login_success_and_failures(client, make_user):
    u = make_user()
    assert client.post("/v1/auth/login", json={"email": u["email"], "password": "correct-horse-9"}).status_code == 200
    assert client.post("/v1/auth/login", json={"email": u["email"], "password": "wrong-password-1"}).status_code == 401
    assert client.post("/v1/auth/login", json={"email": "nobody@example.com", "password": "wrong-password-1"}).status_code == 401


def test_protected_routes_require_valid_token(client):
    assert client.get("/v1/auth/me").status_code == 401
    assert client.get("/v1/auth/me", headers={"Authorization": "Bearer junk"}).status_code == 401
    assert client.get("/v1/workspaces").status_code == 401


def test_refresh_rotates_and_old_token_rejected(client, make_user):
    u = make_user()
    old = client.cookies.get("refresh_token")
    assert old
    assert client.post("/v1/auth/refresh").status_code == 403  # missing CSRF header
    r = client.post("/v1/auth/refresh", headers=CSRF)
    assert r.status_code == 200 and r.json()["access_token"]
    new = client.cookies.get("refresh_token")
    assert new != old
    client.cookies.clear()
    stale = client.post("/v1/auth/refresh", headers={**CSRF, "Cookie": f"refresh_token={old}"})
    assert stale.status_code == 401  # reuse of a rotated token is rejected


def test_logout_revokes_session(client, make_user):
    make_user()
    tok = client.cookies.get("refresh_token")
    assert client.post("/v1/auth/logout", headers=CSRF).status_code == 204
    client.cookies.clear()
    assert client.post("/v1/auth/refresh", headers={**CSRF, "Cookie": f"refresh_token={tok}"}).status_code == 401


def test_refresh_cookie_flags(client):
    email = f"c-{uuid.uuid4().hex[:8]}@example.com"
    r = client.post("/v1/auth/signup", json={"email": email, "password": "correct-horse-9"})
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie and "path=/v1/auth" in cookie


def test_password_reset_flow(client, make_user):
    u = make_user()
    r = client.post("/v1/auth/forgot-password", json={"email": u["email"]})
    assert r.status_code == 202
    token = r.json()["dev_reset_token"]
    # unknown email gives the same status and no token (no enumeration)
    unknown = client.post("/v1/auth/forgot-password", json={"email": "ghost@example.com"})
    assert unknown.status_code == 202 and "dev_reset_token" not in unknown.json()
    assert client.post("/v1/auth/reset-password", json={"token": token, "new_password": "brand-new-pass-7"}).status_code == 200
    assert client.post("/v1/auth/reset-password", json={"token": token, "new_password": "another-pass-77"}).status_code == 400  # single use
    assert client.post("/v1/auth/login", json={"email": u["email"], "password": "correct-horse-9"}).status_code == 401
    assert client.post("/v1/auth/login", json={"email": u["email"], "password": "brand-new-pass-7"}).status_code == 200


def test_error_responses_do_not_leak_internals(client, make_user):
    u = make_user()
    r = client.get(f"/v1/workspaces/not-a-uuid", headers=u["headers"])
    assert r.status_code == 422
    assert "Traceback" not in r.text
