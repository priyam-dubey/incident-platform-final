"""Drives the real dashboard (Next.js production build) in Chromium against the real gateway.

Run: python tests/e2e/ui/run_ui_e2e.py   (needs Postgres via TEST_DATABASE_URL, a built dashboard, playwright)
Writes screenshots to $UI_E2E_OUT (default ./ui-e2e-out). Exits non-zero on any failed check.
"""
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
import uuid
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(os.environ.get("UI_E2E_OUT", "ui-e2e-out")); OUT.mkdir(exist_ok=True, parents=True)
DB = os.environ["TEST_DATABASE_URL"]
GW, UI = "http://127.0.0.1:8005", "http://127.0.0.1:3100"
results: list[tuple[str, bool, str]] = []


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail)); print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail and not cond else ""))


def wait(url, tries=60):
    for _ in range(tries):
        try:
            urllib.request.urlopen(url, timeout=2); return
        except Exception:
            time.sleep(1)
    raise RuntimeError(f"{url} did not start")


def main() -> int:
    env = {**os.environ, "DATABASE_URL": DB, "AUTH_SECRET_KEY": "e2e-secret-" + "x" * 40, "ENVIRONMENT": "development", "COOKIE_SECURE": "false",
           "DASHBOARD_URL": UI, "CORS_ALLOWED_ORIGINS": UI, "PYTHONPATH": str(ROOT / "apps" / "api-gateway")}
    env.pop("LLM_API_KEY", None)
    skip = bool(os.environ.get("SKIP_SERVERS"))   # servers already running (debugging)
    gw = None if skip else subprocess.Popen([os.environ.get("GATEWAY_PYTHON", sys.executable), str(ROOT / "tests/e2e/ui/gateway_harness.py")], env=env)
    ui = None if skip else subprocess.Popen(["npx", "next", "start", "-p", "3100"], cwd=ROOT / "apps/dashboard", env={**os.environ, "GATEWAY_URL": GW, "NEXT_TELEMETRY_DISABLED": "1"})
    try:
        wait(GW + "/healthz"); wait(UI + "/")
        email = f"e2e-{uuid.uuid4().hex[:8]}@example.com"
        with sync_playwright() as p:
            b = p.chromium.launch(); ctx = b.new_context(viewport={"width": 1280, "height": 860}); page = ctx.new_page()
            errors: list[str] = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            # A signed-out visit probes /auth/refresh and gets a 401 by design; the browser logs that as a console error. Anything else is a failure.
            page.on("console", lambda m: errors.append(m.text) if m.type == "error" and "favicon" not in m.text and "401 (Unauthorized)" not in m.text else None)

            page.goto(UI + "/"); check("landing renders", page.get_by_role("heading", name=re.compile("Find the bug")).is_visible())
            page.goto(UI + "/overview"); page.wait_for_url(re.compile("/login")); check("protected route redirects to login", "/login" in page.url)

            page.goto(UI + "/signup")
            page.get_by_label("Your name").fill("E2E User"); page.get_by_label("Email").fill(email)
            page.get_by_label("Password").fill("correct-horse-battery-9"); page.get_by_label("Workspace name").fill("E2E Workspace")
            page.get_by_role("button", name="Create account").click(); page.wait_for_url(re.compile("/overview"))
            check("signup lands on overview", True)
            expect(page.get_by_text("Get set up")).to_be_visible()
            expect(page.get_by_text("No incidents")).to_be_visible(); check("empty overview offers onboarding (no fake data)", True)
            page.screenshot(path=OUT / "01-overview-empty.png")

            page.reload(); page.wait_for_url(re.compile("/overview")); expect(page.get_by_role("button", name="Sign out")).to_be_visible(); check("session survives reload (refresh cookie via proxy)", True)

            page.get_by_role("link", name="Applications").first.click()
            page.get_by_role("button", name="Add application").click()
            page.get_by_label("Name", exact=True).fill("shop-api"); page.get_by_role("button", name="Create and get key").click()
            expect(page.get_by_text("shown once")).to_be_visible()
            setup = page.locator("pre").first.inner_text()
            check("setup snippet has real SDK names and one-time key", "INCIDENT_PLATFORM_KEY=ipk_" in setup and "@incident-platform/node" in setup)
            key = re.search(r"INCIDENT_PLATFORM_KEY=(ipk_\S+)", setup).group(1)
            page.screenshot(path=OUT / "02-app-created.png")
            page.get_by_role("link", name="Open application").click()
            expect(page.get_by_text("Waiting for the first telemetry")).to_be_visible()
            check("new application honestly waits for telemetry", True)
            app_id = page.url.rstrip("/").split("/")[-1]
            ws_id = json.loads(urllib.request.urlopen(urllib.request.Request(GW + "/v1/auth/me", headers={"Authorization": "Bearer " + page.evaluate("() => null") if False else ""}), timeout=5).read()) if False else None
            token = ctx.request.post(UI + "/gw/v1/auth/refresh", headers={"X-Requested-With": "incident-platform"}).json()["access_token"]
            ws_id = ctx.request.get(UI + "/gw/v1/auth/me", headers={"Authorization": f"Bearer {token}"}).json()["workspaces"][0]["id"]

            seeded = ctx.request.post(f"{GW}/__test/seed/{ws_id}/{app_id}").json()
            check("detector opened an incident from seeded outage traffic", len(seeded["incidents"]) == 1)
            page.reload()
            expect(page.get_by_text("Error rate (5xx)").first).to_be_visible()
            page.wait_for_timeout(600)
            check("overview shows measured request count", page.get_by_text("Requests", exact=True).first.is_visible())
            check("charts render", page.locator("svg[role=img]").count() >= 3)
            page.screenshot(path=OUT / "03-monitoring-overview.png", full_page=True)
            for tab in ("Endpoints", "Runtime", "Logs", "Traces"):
                page.get_by_role("tab", name=tab).click(); page.wait_for_timeout(500)
            page.get_by_role("tab", name="Endpoints").click(); expect(page.get_by_text("/api/orders")).to_be_visible()
            page.get_by_role("tab", name="Runtime").click(); expect(page.get_by_text("not host")).to_be_visible()
            check("runtime tab states process scope", True)
            page.get_by_role("tab", name="Logs").click(); expect(page.get_by_text("MongoNetworkError")).to_be_visible()
            check("log secret is redacted in UI", "hunter2" not in page.content())
            page.get_by_role("tab", name="Setup & keys").click()
            page.on("dialog", lambda d: d.accept()); page.get_by_role("button", name="Rotate key").click()
            expect(page.get_by_text("New key (shown once")).to_be_visible(); check("key rotation reveals new key once", True)

            page.get_by_role("link", name="Incidents").first.click()
            expect(page.get_by_text("5xx error rate")).to_be_visible(); page.screenshot(path=OUT / "04-incidents.png")
            page.get_by_role("link", name=re.compile("5xx error rate")).first.click()
            expect(page.get_by_text("Measured facts")).to_be_visible()
            check("AI honestly unavailable without LLM key", page.get_by_text("AI analysis is not available").is_visible())
            check("evidence list is populated", page.locator("[id^=ev-]").count() >= 3)
            check("incident page redacts secrets", "hunter2" not in page.content())
            page.get_by_label("Add a note").fill("Rolled back deploy"); page.get_by_role("button", name="Add note").click(); expect(page.get_by_text("Rolled back deploy")).to_be_visible()
            page.screenshot(path=OUT / "05-incident-detail.png", full_page=True)
            page.get_by_role("button", name="Mark resolved").click(); expect(page.get_by_text("resolved").first).to_be_visible(); check("resolve flow works", True)

            page.get_by_role("link", name="Repositories").first.click(); expect(page.get_by_text("GitHub App: Not configured")).to_be_visible()
            check("repositories shows GitHub Not configured", True); page.screenshot(path=OUT / "06-repositories-not-configured.png")
            page.get_by_role("link", name="Integrations").first.click(); expect(page.get_by_text("AI provider")).to_be_visible()
            check("integrations show Not configured states", page.get_by_text("Not configured").count() >= 3); page.screenshot(path=OUT / "07-integrations.png", full_page=True)
            page.get_by_role("link", name="Settings").first.click(); expect(page.get_by_text("Audit log")).to_be_visible()
            expect(page.get_by_text("incident.detected").first).to_be_visible(); check("audit log lists incident activity", True); page.screenshot(path=OUT / "08-settings.png", full_page=True)

            page.set_viewport_size({"width": 390, "height": 800}); page.goto(UI + "/overview"); expect(page.get_by_role("button", name="Sign out")).to_be_visible(); page.wait_for_timeout(500)
            sw = page.evaluate("[document.documentElement.scrollWidth, window.innerWidth]"); bad = page.evaluate("[...document.querySelectorAll('body *')].filter(e=>e.getBoundingClientRect().right>window.innerWidth+1).slice(0,8).map(e=>e.tagName+'.'+String(e.className).slice(0,70)+' r='+Math.round(e.getBoundingClientRect().right))"); check("mobile: no horizontal page scroll", sw[0] <= sw[1] + 1, f"scrollWidth={sw[0]} innerWidth={sw[1]} offenders={bad}"); page.screenshot(path=OUT / "09-mobile.png")
            page.set_viewport_size({"width": 1280, "height": 860})
            page.get_by_role("button", name="Sign out").click(); page.wait_for_url(re.compile("/login")); check("sign out returns to login", True)
            page.goto(UI + "/overview"); page.wait_for_url(re.compile("/login")); check("signed-out session cannot reopen app", "/login" in page.url)
            check("no browser console/page errors", not errors, "; ".join(errors[:3]))
            b.close()
    finally:
        for pr in (gw, ui):
            if pr is None: continue
            pr.terminate()
            try: pr.wait(10)
            except Exception: pr.kill()
    bad = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(bad)}/{len(results)} UI checks passed"); return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
