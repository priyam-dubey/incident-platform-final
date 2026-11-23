import uuid

import pytest

pytestmark = pytest.mark.integration
INTERNAL = {"X-Internal-Token": "test-internal-token"}


def new_app(client, u, name="shop-api", env="production", **extra):
    return client.post(f"/v1/workspaces/{u['workspace_id']}/applications", headers=u["headers"],
                       json={"name": name, "environment": env, **extra})


def add_member(client, owner, member, role):
    r = client.post(f"/v1/workspaces/{owner['workspace_id']}/members", headers=owner["headers"],
                    json={"email": member["email"], "role": role})
    assert r.status_code == 201, r.text


# ---------------- cross-tenant isolation ----------------
def test_user_cannot_see_other_workspace(client, make_user):
    a, b = make_user("a"), make_user("b")
    assert client.get(f"/v1/workspaces/{a['workspace_id']}", headers=b["headers"]).status_code == 404
    assert client.get(f"/v1/workspaces/{a['workspace_id']}/members", headers=b["headers"]).status_code == 404
    assert client.get(f"/v1/workspaces/{a['workspace_id']}/applications", headers=b["headers"]).status_code == 404
    assert client.get(f"/v1/workspaces/{a['workspace_id']}/audit-logs", headers=b["headers"]).status_code == 404
    listed = {w["id"] for w in client.get("/v1/workspaces", headers=b["headers"]).json()}
    assert a["workspace_id"] not in listed


def test_uuid_swapping_cannot_reach_other_tenants_application(client, make_user):
    a, b = make_user("a"), make_user("b")
    app_a = new_app(client, a).json()["application"]["id"]
    # B uses their own workspace path but A's application id
    base = f"/v1/workspaces/{b['workspace_id']}/applications/{app_a}"
    assert client.get(base, headers=b["headers"]).status_code == 404
    assert client.post(base + "/rotate-key", headers=b["headers"]).status_code == 404
    assert client.delete(base, headers=b["headers"]).status_code == 404
    # ...and A's app is untouched
    assert client.get(f"/v1/workspaces/{a['workspace_id']}/applications/{app_a}", headers=a["headers"]).status_code == 200


def test_cannot_write_into_other_workspace(client, make_user):
    a, b = make_user("a"), make_user("b")
    r = new_app(client, {**a, "headers": b["headers"]})  # B's token against A's workspace
    assert r.status_code == 404
    assert client.get(f"/v1/workspaces/{a['workspace_id']}/applications", headers=a["headers"]).json() == []


def test_application_lists_are_per_workspace(client, make_user):
    a, b = make_user("a"), make_user("b")
    new_app(client, a, "only-a")
    new_app(client, b, "only-b")
    names_a = [x["name"] for x in client.get(f"/v1/workspaces/{a['workspace_id']}/applications", headers=a["headers"]).json()]
    assert names_a == ["only-a"]


# ---------------- roles ----------------
def test_role_permissions(client, make_user):
    owner, viewer, dev, admin = make_user("o"), make_user("v"), make_user("d"), make_user("ad")
    add_member(client, owner, viewer, "viewer")
    add_member(client, owner, dev, "developer")
    add_member(client, owner, admin, "admin")
    ws = owner["workspace_id"]

    def as_(u):  # same workspace, other user's token
        return {**owner, "headers": u["headers"]}

    assert new_app(client, as_(viewer)).status_code == 403     # viewer cannot create
    assert new_app(client, as_(dev), "dev-app").status_code == 201
    app_id = client.get(f"/v1/workspaces/{ws}/applications", headers=viewer["headers"]).json()[0]["id"]  # viewer can read
    assert client.post(f"/v1/workspaces/{ws}/applications/{app_id}/rotate-key", headers=dev["headers"]).status_code == 403
    assert client.post(f"/v1/workspaces/{ws}/applications/{app_id}/rotate-key", headers=admin["headers"]).status_code == 200
    assert client.get(f"/v1/workspaces/{ws}/audit-logs", headers=dev["headers"]).status_code == 403
    assert client.get(f"/v1/workspaces/{ws}/audit-logs", headers=admin["headers"]).status_code == 200


def test_admin_cannot_grant_or_touch_owner(client, make_user):
    owner, admin, other = make_user("o"), make_user("ad"), make_user("x")
    add_member(client, owner, admin, "admin")
    ws = owner["workspace_id"]
    r = client.post(f"/v1/workspaces/{ws}/members", headers=admin["headers"], json={"email": other["email"], "role": "owner"})
    assert r.status_code == 403
    r = client.patch(f"/v1/workspaces/{ws}/members/{owner['user_id']}", headers=admin["headers"], json={"role": "viewer"})
    assert r.status_code == 403


def test_last_owner_cannot_be_demoted_or_removed(client, make_user):
    owner = make_user("o")
    ws = owner["workspace_id"]
    assert client.patch(f"/v1/workspaces/{ws}/members/{owner['user_id']}", headers=owner["headers"], json={"role": "viewer"}).status_code == 409
    assert client.delete(f"/v1/workspaces/{ws}/members/{owner['user_id']}", headers=owner["headers"]).status_code == 409


def test_sensitive_actions_are_audited(client, make_user):
    u = make_user()
    app = new_app(client, u).json()["application"]["id"]
    client.post(f"/v1/workspaces/{u['workspace_id']}/applications/{app}/rotate-key", headers=u["headers"])
    actions = [a["action"] for a in client.get(f"/v1/workspaces/{u['workspace_id']}/audit-logs", headers=u["headers"]).json()]
    assert "application.create" in actions and "application.rotate_key" in actions


# ---------------- applications / ingestion keys ----------------
def test_create_application_returns_key_once_and_stores_only_hash(client, make_user, db):
    u = make_user()
    r = new_app(client, u).json()
    key = r["ingestion_key"]
    assert key.startswith("ipk_")
    assert r["application"]["connection_status"] == "waiting_for_telemetry"
    got = client.get(f"/v1/workspaces/{u['workspace_id']}/applications/{r['application']['id']}", headers=u["headers"])
    assert key not in got.text
    stored = db.execute("SELECT key_hash, key_prefix FROM ingestion_keys WHERE application_id=%s", (r["application"]["id"],)).fetchone()
    assert key not in stored and stored[0] != key


def test_duplicate_application_name_conflict_and_validation(client, make_user):
    u = make_user()
    assert new_app(client, u, "dup").status_code == 201
    assert new_app(client, u, "dup").status_code == 409
    assert new_app(client, u, "dup", env="staging").status_code == 201
    assert new_app(client, u, "x", env="qa").status_code == 422
    assert new_app(client, u, "y", backend_url="javascript:alert(1)").status_code == 422


def test_verify_key_resolves_to_correct_tenant(client, make_user):
    a, b = make_user("a"), make_user("b")
    ka = new_app(client, a, "app-a").json()
    kb = new_app(client, b, "app-b").json()
    ra = client.post("/internal/v1/ingestion-keys/verify", headers=INTERNAL, json={"key": ka["ingestion_key"]}).json()
    rb = client.post("/internal/v1/ingestion-keys/verify", headers=INTERNAL, json={"key": kb["ingestion_key"]}).json()
    assert ra["workspace_id"] == a["workspace_id"] and ra["application_id"] == ka["application"]["id"]
    assert rb["workspace_id"] == b["workspace_id"] != ra["workspace_id"]


def test_verify_key_rejects_bad_tampered_and_unauthenticated(client, make_user):
    u = make_user()
    key = new_app(client, u).json()["ingestion_key"]
    post = lambda k, h=INTERNAL: client.post("/internal/v1/ingestion-keys/verify", headers=h, json={"key": k})
    assert post("ipk_aaaaaaaaaa_notarealsecret").status_code == 401
    assert post(key[:-1] + ("A" if key[-1] != "A" else "B")).status_code == 401
    assert post("garbage-key-value").status_code == 401
    assert post(key, h={}).status_code == 401                       # no internal token
    assert post(key, h={"X-Internal-Token": "wrong"}).status_code == 401
    assert post(key).status_code == 200


def test_rotation_invalidates_old_key(client, make_user):
    u = make_user()
    created = new_app(client, u).json()
    old, app_id = created["ingestion_key"], created["application"]["id"]
    new = client.post(f"/v1/workspaces/{u['workspace_id']}/applications/{app_id}/rotate-key", headers=u["headers"]).json()["ingestion_key"]
    v = lambda k: client.post("/internal/v1/ingestion-keys/verify", headers=INTERNAL, json={"key": k}).status_code
    assert v(old) == 401 and v(new) == 200


def test_revoked_application_key_stops_working_and_hides_app(client, make_user):
    u = make_user()
    created = new_app(client, u).json()
    app_id = created["application"]["id"]
    assert client.delete(f"/v1/workspaces/{u['workspace_id']}/applications/{app_id}", headers=u["headers"]).status_code == 204
    assert client.post("/internal/v1/ingestion-keys/verify", headers=INTERNAL, json={"key": created["ingestion_key"]}).status_code == 401
    assert client.get(f"/v1/workspaces/{u['workspace_id']}/applications", headers=u["headers"]).json() == []


def test_telemetry_seen_flips_connection_status(client, make_user):
    u = make_user()
    created = new_app(client, u).json()
    app_id = created["application"]["id"]
    assert client.post("/internal/v1/applications/telemetry-seen", headers=INTERNAL, json={"application_id": app_id}).status_code == 204
    got = client.get(f"/v1/workspaces/{u['workspace_id']}/applications/{app_id}", headers=u["headers"]).json()["application"]
    assert got["connection_status"] == "connected" and got["last_telemetry_at"]


def test_synthetic_apps_only_in_demo_workspaces(client, make_user, db):
    u = make_user()
    assert new_app(client, u, "fake", is_synthetic=True).status_code == 422      # real workspace rejects synthetic
    db.execute("UPDATE workspaces SET is_demo=true WHERE id=%s", (u["workspace_id"],))
    assert new_app(client, u, "real-looking").status_code == 422                  # demo workspace rejects real
    assert new_app(client, u, "synthetic-shop", is_synthetic=True).status_code == 201


def test_internal_api_disabled_without_token_config(client, monkeypatch):
    from app.config import get_settings
    monkeypatch.setattr(get_settings(), "internal_api_token", "")
    r = client.post("/internal/v1/ingestion-keys/verify", headers=INTERNAL, json={"key": "ipk_aaaaaaaaaa_x" + "y" * 10})
    assert r.status_code == 503


def test_health_and_system_status_expose_no_secrets(client, monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "leak-canary-123456")
    assert client.get("/healthz").json() == {"status": "ok"}
    assert client.get("/readyz").json()["database"] == "up"
    body = client.get("/v1/system/status").text
    assert "leak-canary-123456" not in body and "configured" in body
