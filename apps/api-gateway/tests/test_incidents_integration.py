import json
import uuid

import httpx
import pytest

from app.config import get_settings
from app.rca import RcaOutput
from app.routes.incidents import process_application
from tests.chdb_support import ChdbExecutor, log, minutes_ago, span

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def store(client):
    ex = ChdbExecutor()
    client.app.state.telemetry = ex
    yield ex
    client.app.state.telemetry = None


class FakeLLM:
    """Stands in for the central LLM client. Records prompts; output is scripted."""

    def __init__(self, outputs, state="configured"):
        self.outputs, self.calls, self._state = list(outputs), [], state

    def status(self):
        return {"state": self._state, "provider": "gemini", "model": "gemini/test", "detail": None if self._state == "configured" else "LLM_API_KEY is not set."}

    async def generate_structured(self, system, user, schema):
        self.calls.append(user)
        return self.outputs.pop(0)(user) if callable(self.outputs[0]) else self.outputs.pop(0)


def mk_app(client, u, name="shop-api"):
    r = client.post(f"/v1/workspaces/{u['workspace_id']}/applications", headers=u["headers"], json={"name": name, "environment": "production"})
    assert r.status_code == 201, r.text
    return r.json()["id"] if "id" in r.json() else r.json()["application"]["id"], r.json()


def seed_outage(store, ws, app):
    for m in range(60, 5, -1):                                   # healthy baseline: 30 req/min, ~1 error in 30
        for i in range(30):
            store.insert([span(ws, app, minutes_ago(m) , "/api/foods", "GET", 500 if (m % 9 == 0 and i == 0) else 200, 80 + i)])
    for m in range(5, 0, -1):                                    # outage: 60% of orders fail
        for i in range(30):
            store.insert([span(ws, app, minutes_ago(m - 0.5), "/api/orders", "POST", 500 if i < 18 else 201, 95)])
    store.insert([log(ws, app, minutes_ago(2), "MongoNetworkError: connection closed password=hunter2", "error", trace="a" * 32)])


def app_row(client, u, app_id):
    return client.app.state.repo.get_application(uuid.UUID(u["workspace_id"]), uuid.UUID(app_id))


def one_hypothesis(user_prompt):
    ids = [l[1:37] for l in user_prompt.splitlines() if l.startswith("[") and "] (" in l]
    return RcaOutput(hypotheses=[{"hypothesis": "Database connections may be failing, consistent with the MongoNetworkError log.",
                                  "confidence": 0.7, "cited_evidence_ids": [ids[0]]}])


def test_detects_outage_dedupes_and_builds_redacted_evidence(client, store, make_user):
    u = make_user(); app_id, _ = mk_app(client, u); seed_outage(store, u["workspace_id"], app_id)
    settings = get_settings()
    repo = client.app.state.repo
    found = process_application(repo, store, app_row(client, u, app_id), settings, FakeLLM([], "not_configured"))
    assert [i["detector"] for i in found] == ["error_rate_zscore"] and found[0]["severity"] == "critical"
    again = process_application(repo, store, app_row(client, u, app_id), settings, FakeLLM([], "not_configured"))
    assert again[0]["id"] == found[0]["id"]                      # deduped, not duplicated
    lst = client.get(f"/v1/workspaces/{u['workspace_id']}/incidents", headers=u["headers"]).json()
    assert len(lst) == 1
    d = client.get(f"/v1/workspaces/{u['workspace_id']}/incidents/{found[0]['id']}", headers=u["headers"]).json()
    kinds = {e["source_type"] for e in d["evidence"]}
    assert {"metric", "log", "trace"} <= kinds
    assert "hunter2" not in json.dumps(d)                        # secrets redacted in evidence
    assert d["hypotheses"] == [] and d["incident"]["details"]["rca"]["state"] == "not_configured"   # no fake AI
    assert d["incident"]["details"]["recent_error_rate"] == pytest.approx(0.6, abs=0.01)


def test_healthy_app_creates_no_incident(client, store, make_user):
    u = make_user(); app_id, _ = mk_app(client, u)
    for m in range(40, 0, -1):
        for i in range(25):
            store.insert([span(u["workspace_id"], app_id, minutes_ago(m), "/api/foods", "GET", 200, 90)])
    assert process_application(client.app.state.repo, store, app_row(client, u, app_id), get_settings(), FakeLLM([], "not_configured")) == []


def test_rca_is_grounded_review_flow_and_audit(client, store, make_user):
    u = make_user(); app_id, _ = mk_app(client, u); seed_outage(store, u["workspace_id"], app_id)
    bogus = RcaOutput(hypotheses=[{"hypothesis": "A made-up cause with an invented citation here.", "confidence": 0.9,
                                   "cited_evidence_ids": [str(uuid.uuid4())]}])
    llm = FakeLLM([bogus, one_hypothesis])                       # first answer ungrounded -> retry once -> grounded
    found = process_application(client.app.state.repo, store, app_row(client, u, app_id), get_settings(), llm)
    assert len(llm.calls) == 2 and "rejected" in llm.calls[1]
    ws, iid = u["workspace_id"], found[0]["id"]
    d = client.get(f"/v1/workspaces/{ws}/incidents/{iid}", headers=u["headers"]).json()
    assert d["incident"]["status"] == "pending_review" and len(d["hypotheses"]) == 1
    h = d["hypotheses"][0]
    assert h["kind"] == "hypothesis_not_proof" and h["ai_generated"] and set(h["cited_evidence_ids"]) <= {e["id"] for e in d["evidence"]}
    base = f"/v1/workspaces/{ws}/incidents/{iid}"
    assert client.post(f"{base}/hypotheses/{h['id']}/review", headers=u["headers"], json={"verdict": "edited"}).status_code == 422
    r = client.post(f"{base}/hypotheses/{h['id']}/review", headers=u["headers"], json={"verdict": "edited", "edited_text": "Mongo pool exhausted after deploy", "notes": "checked"})
    assert r.status_code == 200 and r.json()["human_verdict"] == "edited" and r.json()["reviewed_by"] == u["email"]
    assert client.post(f"{base}/notes", headers=u["headers"], json={"body": "Rolled back at 10:42"}).status_code == 201
    assert client.post(f"{base}/status", headers=u["headers"], json={"status": "resolved"}).json()["status"] == "resolved"
    d = client.get(base, headers=u["headers"]).json()
    assert d["incident"]["status"] == "resolved" and d["incident"]["resolved_at"] and d["notes"][0]["author"] == u["email"]
    actions = [a["action"] for a in client.get(f"/v1/workspaces/{ws}/audit-logs", headers=u["headers"]).json()]
    assert {"incident.detected", "hypothesis.edited", "incident.note_added", "incident.resolved"} <= set(actions)


def test_rca_drops_hypotheses_that_stay_ungrounded(client, store, make_user):
    u = make_user(); app_id, _ = mk_app(client, u); seed_outage(store, u["workspace_id"], app_id)
    bogus = RcaOutput(hypotheses=[{"hypothesis": "Another invented explanation with no support at all.", "confidence": 0.9,
                                   "cited_evidence_ids": [str(uuid.uuid4())]}])
    found = process_application(client.app.state.repo, store, app_row(client, u, app_id), get_settings(), FakeLLM([bogus, bogus]))
    d = client.get(f"/v1/workspaces/{u['workspace_id']}/incidents/{found[0]['id']}", headers=u["headers"]).json()
    assert d["hypotheses"] == []                                 # never shown as fact


def test_deployment_correlation_appears_as_evidence_and_related(client, store, make_user):
    u = make_user(); app_id, created = mk_app(client, u); seed_outage(store, u["workspace_id"], app_id)
    ws = u["workspace_id"]
    r = client.post(f"/v1/workspaces/{ws}/applications/{app_id}/deployments", headers=u["headers"],
                    json={"version": "1.4.2", "commit_sha": "a1b2c3d4e5f6", "branch": "main", "repository": "acme/shop",
                          "deployed_at": minutes_ago(8).isoformat()})
    assert r.status_code == 201
    assert client.post(f"/v1/workspaces/{ws}/applications/{app_id}/deployments", headers=u["headers"], json={"commit_sha": "zzz"}).status_code == 422
    found = process_application(client.app.state.repo, store, app_row(client, u, app_id), get_settings(), FakeLLM([], "not_configured"))
    d = client.get(f"/v1/workspaces/{ws}/incidents/{found[0]['id']}", headers=u["headers"]).json()
    assert any(e["source_type"] == "deploy" and "a1b2c3d4e5f6" in e["snippet"] for e in d["evidence"])
    assert d["related_deployments"][0]["commit_sha"] == "a1b2c3d4e5f6"


def test_deployment_via_ingestion_key_binds_to_key_not_payload(client, make_user):
    a, b = make_user("a"), make_user("b")
    _, created = mk_app(client, a)
    key = created["ingestion_key"]
    r = client.post("/v1/deployments", headers={"X-Ingestion-Key": key}, json={"version": "2.0.0", "commit_sha": "abcdef1234567"})
    assert r.status_code == 201 and r.json()["source"] == "sdk"
    assert client.post("/v1/deployments", headers={"X-Ingestion-Key": key + "x"}, json={"version": "1"}).status_code == 401
    assert client.post("/v1/deployments", json={"version": "1"}).status_code == 401
    assert client.post("/v1/deployments", headers={"X-Ingestion-Key": key}, json={"workspace_id": b["workspace_id"]}).status_code == 422
    assert len(client.get(f"/v1/workspaces/{a['workspace_id']}/deployments", headers=a["headers"]).json()) == 1
    assert client.get(f"/v1/workspaces/{b['workspace_id']}/deployments", headers=b["headers"]).json() == []


def test_incident_tenant_isolation_and_roles(client, store, make_user):
    a, b = make_user("a"), make_user("b")
    app_id, _ = mk_app(client, a); seed_outage(store, a["workspace_id"], app_id)
    found = process_application(client.app.state.repo, store, app_row(client, a, app_id), get_settings(), FakeLLM([], "not_configured"))
    iid = found[0]["id"]
    # B cannot read A's incident through A's workspace or through B's own workspace
    assert client.get(f"/v1/workspaces/{a['workspace_id']}/incidents/{iid}", headers=b["headers"]).status_code == 404
    assert client.get(f"/v1/workspaces/{b['workspace_id']}/incidents/{iid}", headers=b["headers"]).status_code == 404
    assert client.post(f"/v1/workspaces/{b['workspace_id']}/incidents/{iid}/status", headers=b["headers"], json={"status": "dismissed"}).status_code == 404
    assert client.post(f"/v1/workspaces/{b['workspace_id']}/incidents/{iid}/notes", headers=b["headers"], json={"body": "x"}).status_code == 404
    assert client.get(f"/v1/workspaces/{b['workspace_id']}/incidents", headers=b["headers"]).json() == []
    # viewers read but cannot change
    v = make_user("v")
    client.post(f"/v1/workspaces/{a['workspace_id']}/members", headers=a["headers"], json={"email": v["email"], "role": "viewer"})
    base = f"/v1/workspaces/{a['workspace_id']}/incidents/{iid}"
    assert client.get(base, headers=v["headers"]).status_code == 200
    assert client.post(f"{base}/status", headers=v["headers"], json={"status": "resolved"}).status_code == 403
    assert client.get(f"/v1/workspaces/{a['workspace_id']}/incidents?status=bogus", headers=a["headers"]).status_code == 422


def test_notifications_only_when_configured_and_failures_recorded(client, store, make_user):
    u = make_user(); app_id, _ = mk_app(client, u); seed_outage(store, u["workspace_id"], app_id)
    sent = []

    def handler(req: httpx.Request):
        sent.append(str(req.url))
        return httpx.Response(500 if "pagerduty" in str(req.url) else 200)

    s = get_settings().model_copy(update={"slack_webhook_url": "https://hooks.slack.test/T/secret", "pagerduty_routing_key": "rk"})
    found = process_application(client.app.state.repo, store, app_row(client, u, app_id), s, FakeLLM([], "not_configured"),
                                transport=httpx.MockTransport(handler))
    d = client.get(f"/v1/workspaces/{u['workspace_id']}/incidents/{found[0]['id']}", headers=u["headers"]).json()
    assert {(n["channel"], n["status"]) for n in d["notifications"]} == {("slack", "sent"), ("pagerduty", "failed")}
    assert "secret" not in json.dumps(d)
    # unconfigured -> nothing attempted
    u2 = make_user(); a2, _ = mk_app(client, u2); seed_outage(store, u2["workspace_id"], a2)
    found2 = process_application(client.app.state.repo, store, app_row(client, u2, a2), get_settings(), FakeLLM([], "not_configured"),
                                 transport=httpx.MockTransport(lambda r: pytest.fail("no request expected")))
    assert client.get(f"/v1/workspaces/{u2['workspace_id']}/incidents/{found2[0]['id']}", headers=u2["headers"]).json()["notifications"] == []
    st = client.get(f"/v1/workspaces/{u['workspace_id']}/integrations/status", headers=u["headers"]).json()
    assert st["notifications"] == {"slack": "not_configured", "pagerduty": "not_configured"}


def test_analyze_endpoint_reports_not_configured_honestly(client, store, make_user, monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    u = make_user(); app_id, _ = mk_app(client, u); seed_outage(store, u["workspace_id"], app_id)
    found = process_application(client.app.state.repo, store, app_row(client, u, app_id), get_settings(), FakeLLM([], "not_configured"))
    r = client.post(f"/v1/workspaces/{u['workspace_id']}/incidents/{found[0]['id']}/analyze", headers=u["headers"])
    assert r.status_code == 503 and r.json()["detail"]["code"] == "llm_not_configured"


def test_detection_loop_isolates_failures(monkeypatch):
    """One application raising must not stop detection for the others."""
    from app import detection_loop
    import app.routes.incidents as inc

    class R:
        def monitored_applications(self): return [{"id": "a"}, {"id": "b"}, {"id": "c"}]
    seen = []

    def fake(repo, ex, app, settings, llm=None):
        seen.append(app["id"])
        if app["id"] == "b": raise RuntimeError("boom")
    monkeypatch.setattr(inc, "process_application", fake)
    assert detection_loop.run_once(R(), object(), object()) == 2
    assert seen == ["a", "b", "c"]
