"""One adapter per analysis tool: how to run it (statically) and how to parse its output into RawFinding."""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import tempfile
from importlib import resources
from pathlib import Path
from typing import Callable

from incident_scanner import sandbox
from incident_scanner.models import RawFinding, norm_path

RULES = Path(str(resources.files("incident_scanner") / "rules"))
TOOL_DIRS = [d for d in os.environ.get("SCANNER_TOOL_PATH", "").split(os.pathsep) if d]


def which(name: str) -> str | None:
    return shutil.which(name, path=os.pathsep.join([*TOOL_DIRS, os.path.dirname(sys.executable), os.environ.get("PATH", "")]))


class ToolUnavailable(Exception):
    pass


class ToolFailed(Exception):
    pass


SEV_SEMGREP = {"ERROR": "high", "WARNING": "medium", "INFO": "low"}
SEV_BANDIT = {"HIGH": "high", "MEDIUM": "medium", "LOW": "low"}
SEV_ESLINT = {2: "medium", 1: "low"}
SEV_NPM = {"critical": "critical", "high": "high", "moderate": "medium", "low": "low", "info": "info"}
SEV_TRIVY = {"CRITICAL": "critical", "HIGH": "high", "MEDIUM": "medium", "LOW": "low", "UNKNOWN": "info"}


def _json(text: str, what: str):
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        raise ToolFailed(f"{what} produced unparseable output") from None


def _need(binary: str) -> str:
    p = which(binary)
    if not p:
        raise ToolUnavailable(f"{binary} is not installed on the scanner host")
    return p


def _cwe(v) -> str | None:
    if isinstance(v, list):
        v = v[0] if v else None
    if isinstance(v, int):
        return f"CWE-{v}"
    m = re.search(r"CWE-\d+", str(v or ""))
    return m.group(0) if m else None


# ---------------------------------------------------------------- semgrep
def parse_semgrep(data: dict, root: str) -> list[RawFinding]:
    out = []
    for r in data.get("results", []):
        e = r.get("extra", {})
        lines = e.get("lines", "")
        out.append(RawFinding("semgrep", r["check_id"].split(".")[-1], "sast", SEV_SEMGREP.get(e.get("severity", "INFO"), "low"),
                              r["check_id"].split(".")[-1].replace("-", " "), e.get("message", ""), norm_path(r["path"], root),
                              r["start"]["line"], r["end"]["line"], None if "requires login" in lines else lines,
                              _cwe(e.get("metadata", {}).get("cwe"))))
    return out


def run_semgrep(root: str, ctx: dict) -> list[RawFinding]:
    exe = _need("semgrep")
    cfg = os.environ.get("SEMGREP_CONFIG") or str(RULES / "semgrep-rules.yml")
    r = sandbox.run([exe, "scan", "--json", "--quiet", "--metrics", "off", "--disable-version-check", "--timeout", "20",
                     "--max-target-bytes", "1000000", "--config", cfg, root], root, timeout=300, mem_mb=0, network=cfg.startswith(("p/", "r/", "http")))
    if r.timed_out:
        raise ToolFailed("semgrep timed out")
    if r.returncode not in (0, 1):
        raise ToolFailed(f"semgrep exited with {r.returncode}")
    return parse_semgrep(_json(r.stdout, "semgrep"), root)


# ----------------------------------------------------------------- bandit
def parse_bandit(data: dict, root: str) -> list[RawFinding]:
    return [RawFinding("bandit", i["test_id"], "sast", SEV_BANDIT.get(i["issue_severity"], "low"), i["test_name"].replace("_", " "),
                       i["issue_text"], norm_path(i["filename"], root), i["line_number"], (i.get("line_range") or [i["line_number"]])[-1],
                       i.get("code"), _cwe((i.get("issue_cwe") or {}).get("id"))) for i in data.get("results", [])]


def run_bandit(root: str, ctx: dict) -> list[RawFinding]:
    if "python" not in ctx["languages"]:
        raise ToolUnavailable("no Python files")
    r = sandbox.run([_need("bandit"), "-r", root, "-f", "json", "-q", "--exclude", "node_modules,.git,venv,.venv"], root, timeout=180)
    if r.timed_out:
        raise ToolFailed("bandit timed out")
    return parse_bandit(_json(r.stdout, "bandit"), root)


# ------------------------------------------------------------------- ruff
RUFF_MEDIUM = ("F821", "F822", "F823", "F811", "F63", "F7", "E9", "B006", "B008", "B023", "B012")


def parse_ruff(data: list, root: str) -> list[RawFinding]:
    out = []
    for i in data:
        code = i.get("code") or "ruff"
        sev = "medium" if code.startswith(RUFF_MEDIUM) else "low"
        out.append(RawFinding("ruff", code, "lint", sev, i["message"][:120], i["message"], norm_path(i["filename"], root),
                              i["location"]["row"], i["end_location"]["row"], None))
    return out


def run_ruff(root: str, ctx: dict) -> list[RawFinding]:
    if "python" not in ctx["languages"]:
        raise ToolUnavailable("no Python files")
    r = sandbox.run([_need("ruff"), "check", "--isolated", "--no-cache", "--output-format", "json", "--select", "E9,F,B", "--exit-zero",
                     "--exclude", "node_modules,.git,venv,.venv", root], root, timeout=120)
    if r.timed_out:
        raise ToolFailed("ruff timed out")
    return parse_ruff(_json(r.stdout or "[]", "ruff"), root)


# ----------------------------------------------------------------- eslint
def parse_eslint(data: list, root: str) -> list[RawFinding]:
    out = []
    for f in data:
        for m in f.get("messages", []):
            if m.get("ruleId") is None and not m.get("fatal"):
                continue
            rule = m.get("ruleId") or "parse-error"
            sev = "high" if rule in ("no-eval", "no-implied-eval", "no-new-func") else SEV_ESLINT.get(m.get("severity", 1), "low")
            out.append(RawFinding("eslint", rule, "lint", sev, rule, m["message"], norm_path(f["filePath"], root), m.get("line"), m.get("endLine"), None))
    return out


def run_eslint(root: str, ctx: dict) -> list[RawFinding]:
    if "javascript" not in ctx["languages"]:
        raise ToolUnavailable("no JavaScript files")
    exe = _need("eslint")
    r = sandbox.run([exe, "--no-config-lookup", "-c", str(RULES / "eslint.config.mjs"), "--format", "json", "--no-warn-ignored",
                     "--ignore-pattern", "**/node_modules/**", "--ignore-pattern", "**/dist/**", "--ignore-pattern", "**/build/**", "--ignore-pattern", "**/*.min.js", "."],
                    root, timeout=180)
    if r.timed_out:
        raise ToolFailed("eslint timed out")
    if r.returncode not in (0, 1):
        raise ToolFailed(f"eslint exited with {r.returncode}")
    return parse_eslint(_json(r.stdout or "[]", "eslint"), root)


# -------------------------------------------------------------------- tsc
TSC_LINE = re.compile(r"^(?P<file>.+?)\((?P<line>\d+),(?P<col>\d+)\): error (?P<code>TS\d+): (?P<msg>.*)$")
TSC_NOISE = {"TS2307", "TS7016", "TS2792", "TS2688", "TS6053", "TS18003", "TS5083"}   # missing deps/types: not installed in the sandbox


def parse_tsc(text: str, root: str, base: str | None = None) -> list[RawFinding]:
    out = []
    for line in text.splitlines():
        m = TSC_LINE.match(line.strip())
        if m and m["code"] not in TSC_NOISE:
            out.append(RawFinding("tsc", m["code"], "types", "low", f"TypeScript {m['code']}", m["msg"], norm_path(os.path.join(base, m["file"]) if base and not os.path.isabs(m["file"]) else m["file"], root), int(m["line"]), int(m["line"]), None))
    return out


def run_tsc(root: str, ctx: dict) -> list[RawFinding]:
    if "typescript" not in ctx["languages"]:
        raise ToolUnavailable("no TypeScript files")
    configs = [p for p in ctx["files"] if p.endswith("tsconfig.json") and "node_modules" not in p][:5]
    if not configs:
        raise ToolUnavailable("no tsconfig.json")
    out: list[RawFinding] = []
    for c in configs:
        d = os.path.dirname(os.path.join(root, c))
        r = sandbox.run([_need("tsc"), "--noEmit", "--pretty", "false", "-p", os.path.join(root, c)], d, timeout=180)
        if r.timed_out:
            raise ToolFailed("tsc timed out")
        out += parse_tsc(r.stdout, root, d)
    return out


# --------------------------------------------------------------- gitleaks
def parse_gitleaks(data: list, root: str) -> list[RawFinding]:
    return [RawFinding("gitleaks", i["RuleID"], "secret", "high", i.get("Description") or i["RuleID"],
                       "A credential-like value was committed. Rotate it and remove it from history.", norm_path(i["File"], root),
                       i.get("StartLine"), i.get("EndLine"), "[secret redacted]") for i in data or []]


def run_gitleaks(root: str, ctx: dict) -> list[RawFinding]:
    exe = _need("gitleaks")
    with tempfile.TemporaryDirectory() as td:
        rep = os.path.join(td, "r.json")
        r = sandbox.run([exe, "detect", "--no-git", "--source", root, "--report-format", "json", "--report-path", rep, "--redact",
                         "--no-banner", "--exit-code", "0"], root, timeout=180)
        if r.timed_out or r.returncode != 0:
            raise ToolFailed("gitleaks failed")
        return parse_gitleaks(json.loads(Path(rep).read_text() or "[]"), root) if os.path.exists(rep) else []


# ----------------------------------------------------------------- npm audit
def parse_npm_audit(data: dict, lockfile: str) -> list[RawFinding]:
    out = []
    for name, v in (data.get("vulnerabilities") or {}).items():
        direct = [x for x in v.get("via", []) if isinstance(x, dict)]
        fix = v.get("fixAvailable")
        fixed = fix.get("version") if isinstance(fix, dict) else None
        for x in direct or [{"title": f"Vulnerable dependency chain via {name}", "source": name}]:
            out.append(RawFinding("npm-audit", str(x.get("source", name)), "dependency", SEV_NPM.get(x.get("severity") or v.get("severity"), "medium"),
                                  x.get("title", name), f"{name} {v.get('range', '')}".strip() + (f" - {x['url']}" if x.get("url") else ""), lockfile,
                                  None, None, None, _cwe(x.get("cwe")), name, None, fixed))
    return out


def run_npm_audit(root: str, ctx: dict) -> list[RawFinding]:
    locks = [p for p in ctx["files"] if p.endswith("package-lock.json") and "node_modules" not in p][:5]
    if not locks:
        raise ToolUnavailable("no package-lock.json")
    out = []
    for lock in locks:
        d = os.path.dirname(os.path.join(root, lock))
        r = sandbox.run([_need("npm"), "audit", "--package-lock-only", "--json", "--ignore-scripts"], d, timeout=120, network=True)
        if r.timed_out:
            raise ToolFailed("npm audit timed out")
        data = _json(r.stdout, "npm audit")
        if "error" in data and "vulnerabilities" not in data:
            raise ToolFailed(f"npm audit could not reach the advisory service ({data['error'].get('code', 'error')})")
        out += parse_npm_audit(data, lock)
    return out


# ---------------------------------------------------------------- pip-audit
def parse_pip_audit(data: dict, req_file: str) -> list[RawFinding]:
    out = []
    for dep in data.get("dependencies", []):
        for v in dep.get("vulns", []):
            fixes = v.get("fix_versions") or []
            out.append(RawFinding("pip-audit", v["id"], "dependency", "high", f"{dep['name']} {dep.get('version')}: {v['id']}",
                                  (v.get("description") or "")[:1000], req_file, None, None, None, None, dep["name"], dep.get("version"), fixes[0] if fixes else None))
    return out


def run_pip_audit(root: str, ctx: dict) -> list[RawFinding]:
    reqs = [p for p in ctx["files"] if re.search(r"(^|/)requirements[^/]*\.txt$", p) and "node_modules" not in p][:5]
    if not reqs:
        raise ToolUnavailable("no requirements.txt")
    out = []
    for rq in reqs:
        r = sandbox.run([_need("pip-audit"), "-r", os.path.join(root, rq), "-f", "json", "--no-deps", "--disable-pip", "--progress-spinner", "off"],
                        root, timeout=180, network=True)
        if r.timed_out:
            raise ToolFailed("pip-audit timed out")
        if not r.stdout.strip():
            raise ToolFailed("pip-audit could not reach the advisory service")
        out += parse_pip_audit(_json(r.stdout, "pip-audit"), rq)
    return out


# ------------------------------------------------------------------ trivy
def parse_trivy(data: dict, root: str) -> list[RawFinding]:
    out = []
    for res in data.get("Results", []) or []:
        target = norm_path(res.get("Target"), root)
        for v in res.get("Vulnerabilities") or []:
            out.append(RawFinding("trivy", v["VulnerabilityID"], "dependency", SEV_TRIVY.get(v.get("Severity", "UNKNOWN"), "info"),
                                  v.get("Title") or v["VulnerabilityID"], (v.get("Description") or "")[:1000], target, None, None, None,
                                  _cwe(v.get("CweIDs")), v.get("PkgName"), v.get("InstalledVersion"), v.get("FixedVersion")))
        for m in res.get("Misconfigurations") or []:
            out.append(RawFinding("trivy", m["ID"], "iac", SEV_TRIVY.get(m.get("Severity", "UNKNOWN"), "info"), m.get("Title") or m["ID"],
                                  m.get("Message") or "", target, (m.get("CauseMetadata") or {}).get("StartLine"), (m.get("CauseMetadata") or {}).get("EndLine")))
    return out


def run_trivy(root: str, ctx: dict) -> list[RawFinding]:
    exe = _need("trivy")
    r = sandbox.run([exe, "fs", "--format", "json", "--scanners", "vuln,misconfig", "--quiet", "--skip-dirs", "node_modules,.git", root], root, timeout=300, network=True)
    if r.timed_out or r.returncode != 0:
        raise ToolFailed("trivy failed (its vulnerability database requires network access)")
    return parse_trivy(_json(r.stdout, "trivy"), root)


REGISTRY: dict[str, Callable[[str, dict], list[RawFinding]]] = {
    "semgrep": run_semgrep, "bandit": run_bandit, "ruff": run_ruff, "eslint": run_eslint, "tsc": run_tsc,
    "gitleaks": run_gitleaks, "npm-audit": run_npm_audit, "pip-audit": run_pip_audit, "trivy": run_trivy,
}
