import json
import pathlib
import shutil

import pytest

from incident_scanner import scan_directory, tools
from incident_scanner.models import RawFinding
from incident_scanner.sandbox import network_isolation_available, run

FIX = pathlib.Path(__file__).parent / "fixtures" / "vuln-repo"
PWNED = [pathlib.Path(f"/tmp/PWNED_{n}") for n in ("ESLINT_CONFIG", "POSTINSTALL", "TEST", "CONFTEST")]


def need(binary):
    return pytest.mark.skipif(tools.which(binary) is None, reason=f"{binary} not installed on this machine")


@pytest.fixture(scope="module")
def result(tmp_path_factory):
    for p in PWNED:
        p.unlink(missing_ok=True)
    work = tmp_path_factory.mktemp("repo") / "r"
    shutil.copytree(FIX, work)
    return scan_directory(str(work), ("semgrep", "bandit", "ruff", "eslint", "tsc", "gitleaks"))


def by_tool(result, tool):
    return [f for f in result.findings if f.tool == tool]


def status(result, tool):
    return next(r for r in result.reports if r.tool == tool)


def test_repository_code_is_never_executed(result):
    assert [p for p in PWNED if p.exists()] == []


@need("semgrep")
def test_semgrep_finds_injection_issues(result):
    ids = {f.rule_id for f in by_tool(result, "semgrep")}
    assert {"py-subprocess-shell-true", "py-sql-string-formatting", "py-requests-verify-false", "py-yaml-unsafe-load",
            "js-eval-use", "js-child-process-exec-dynamic", "js-innerhtml-assignment"} <= ids
    f = next(f for f in by_tool(result, "semgrep") if f.rule_id == "js-eval-use")
    assert f.file_path == "src/server.js" and f.start_line == 6 and f.cwe == "CWE-95" and f.severity == "high"


@need("bandit")
def test_bandit(result):
    assert {"B602", "B608"} <= {f.rule_id for f in by_tool(result, "bandit")}


@need("ruff")
def test_ruff_flags_undefined_name_as_medium(result):
    f = next(f for f in by_tool(result, "ruff") if f.rule_id == "F821")
    assert f.severity == "medium" and f.file_path == "src/app.py"


@need("eslint")
def test_eslint_uses_own_config_not_repos(result):
    assert status(result, "eslint").status == "ok"
    assert "no-eval" in {f.rule_id for f in by_tool(result, "eslint")}


@need("tsc")
def test_tsc_type_error(result):
    assert any(f.rule_id == "TS2322" and f.file_path == "web/page.ts" for f in by_tool(result, "tsc"))


@need("gitleaks")
def test_gitleaks_finds_secrets_and_never_stores_them(result):
    fs = by_tool(result, "gitleaks")
    assert fs and all(f.snippet == "[secret redacted]" for f in fs)
    assert "AKIAIOSFODNN7EXAMPLE1" not in json.dumps([f.__dict__ for f in result.findings])


def test_every_tool_reports_an_honest_status(result):
    assert {r.tool for r in result.reports} == {"semgrep", "bandit", "ruff", "eslint", "tsc", "gitleaks"}
    for r in result.reports:
        assert r.status in {"ok", "skipped", "unavailable", "failed"}
        if r.status != "ok":
            assert r.detail


@pytest.mark.skipif(tools.which("trivy") is not None, reason="trivy is installed here")
def test_unavailable_tool_is_reported_not_faked(tmp_path):
    (tmp_path / "a.py").write_text("x=1\n")
    r = scan_directory(str(tmp_path), ("trivy",))
    assert r.reports[0].status == "unavailable" and r.findings == []


def test_fingerprint_is_stable_when_lines_shift():
    a = RawFinding("semgrep", "r", "sast", "high", "t", "m", "a.py", 10, 10, "eval(x)")
    b = RawFinding("semgrep", "r", "sast", "high", "t", "m", "a.py", 55, 55, "   eval(x)  ")
    c = RawFinding("semgrep", "r", "sast", "high", "t", "m", "b.py", 10, 10, "eval(x)")
    assert a.fingerprint == b.fingerprint != c.fingerprint


def test_sandbox_blocks_network_and_scrubs_env(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "super-secret")
    monkeypatch.setenv("DATABASE_URL", "postgres://x")
    r = run(["python3", "-c", "import os;print(sorted(k for k in os.environ if 'KEY' in k or 'DATABASE' in k))"], str(tmp_path))
    assert r.stdout.strip() == "[]"
    if network_isolation_available():
        r = run(["python3", "-c", "import socket;socket.create_connection(('1.1.1.1',53),2)"], str(tmp_path))
        assert r.returncode != 0


def test_sandbox_timeout(tmp_path):
    assert run(["python3", "-c", "import time;time.sleep(30)"], str(tmp_path), timeout=1).timed_out


# Parsers for tools that need network access / are not installable in every environment are exercised on
# fixtures written to match each tool's documented JSON output format (NOT captured from a live run).
def test_parse_npm_audit_documented_format():
    data = {"vulnerabilities": {"lodash": {"severity": "high", "range": "<4.17.21", "fixAvailable": {"name": "lodash", "version": "4.17.21"},
            "via": [{"source": 1673, "name": "lodash", "title": "Prototype Pollution", "url": "https://github.com/advisories/GHSA-x", "severity": "high", "cwe": ["CWE-1321"]}]},
            "express": {"severity": "high", "via": ["lodash"], "fixAvailable": True}}}
    f = tools.parse_npm_audit(data, "package-lock.json")
    assert f[0].package_name == "lodash" and f[0].fixed_version == "4.17.21" and f[0].cwe == "CWE-1321" and f[0].severity == "high"
    assert len(f) == 2 and f[1].package_name == "express"


def test_parse_pip_audit_documented_format():
    data = {"dependencies": [{"name": "flask", "version": "0.12", "vulns": [{"id": "PYSEC-2018-66", "fix_versions": ["0.12.3"], "description": "DoS"}]},
                              {"name": "ok", "version": "1", "vulns": []}]}
    f = tools.parse_pip_audit(data, "requirements.txt")
    assert len(f) == 1 and f[0].fixed_version == "0.12.3" and f[0].category == "dependency"


def test_parse_trivy_documented_format():
    data = {"Results": [{"Target": "package-lock.json", "Vulnerabilities": [{"VulnerabilityID": "CVE-2021-23337", "PkgName": "lodash",
            "InstalledVersion": "4.17.20", "FixedVersion": "4.17.21", "Severity": "HIGH", "Title": "Command Injection", "CweIDs": ["CWE-77"]}]},
            {"Target": "Dockerfile", "Misconfigurations": [{"ID": "DS002", "Severity": "HIGH", "Title": "Image user should not be root", "Message": "Specify USER",
             "CauseMetadata": {"StartLine": 1, "EndLine": 1}}]}]}
    f = tools.parse_trivy(data, "/r")
    assert {x.category for x in f} == {"dependency", "iac"} and f[0].cwe == "CWE-77"
