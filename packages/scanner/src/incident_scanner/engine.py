from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field

from incident_scanner import tools
from incident_scanner.languages import walk
from incident_scanner.models import RawFinding

logger = logging.getLogger("scanner")
DEFAULT_TOOLS = ("semgrep", "bandit", "ruff", "eslint", "tsc", "gitleaks", "npm-audit", "pip-audit", "trivy")


@dataclass
class ToolReport:
    tool: str
    status: str                 # ok | skipped | unavailable | failed
    detail: str | None = None
    findings: int = 0
    seconds: float = 0.0


@dataclass
class ScanResult:
    findings: list[RawFinding] = field(default_factory=list)
    reports: list[ToolReport] = field(default_factory=list)
    languages: dict[str, int] = field(default_factory=dict)
    file_count: int = 0

    @property
    def ok_tools(self) -> set[str]:
        return {r.tool for r in self.reports if r.status == "ok"}


def scan_directory(root: str, enabled: tuple[str, ...] | list[str] = DEFAULT_TOOLS) -> ScanResult:
    """Statically analyse `root`. Never imports, installs, builds or runs the repository's code."""
    files, langs = walk(root)
    ctx = {"files": files, "languages": set(langs)}
    result = ScanResult(languages=langs, file_count=len(files))
    seen: set[tuple] = set()
    for name in enabled:
        runner = tools.REGISTRY[name]
        t0 = time.monotonic()
        try:
            found = runner(root, ctx)
            status, detail = "ok", None
        except tools.ToolUnavailable as exc:
            found, status, detail = [], ("skipped" if str(exc).startswith("no ") else "unavailable"), str(exc)
        except tools.ToolFailed as exc:
            found, status, detail = [], "failed", str(exc)
        except Exception:                                     # a tool bug must not abort the whole scan
            logger.exception("scanner_tool_crashed tool=%s", name)
            found, status, detail = [], "failed", "internal error while running the tool"
        _fill_snippets(root, found)
        unique = []
        for f in found:
            k = (f.fingerprint, f.start_line)
            if k not in seen:
                seen.add(k)
                unique.append(f)
        result.findings += unique
        result.reports.append(ToolReport(name, status, detail, len(unique), round(time.monotonic() - t0, 2)))
    return result


def _fill_snippets(root: str, findings: list[RawFinding]) -> None:
    """Semgrep OSS withholds source lines unless logged in; read the (bounded) lines from the checked-out file ourselves."""
    cache: dict[str, list[str]] = {}
    for f in findings:
        if f.snippet or f.category in ("secret", "dependency") or not f.file_path or not f.start_line:
            continue
        path = os.path.realpath(os.path.join(root, f.file_path))
        if not path.startswith(os.path.realpath(root) + os.sep) or not os.path.isfile(path):
            continue
        if path not in cache:
            try:
                with open(path, encoding="utf-8", errors="replace") as fh:
                    cache[path] = fh.read(2_000_000).splitlines()
            except OSError:
                cache[path] = []
        lines = cache[path][f.start_line - 1:min(f.end_line or f.start_line, f.start_line + 9)]
        if lines:
            f.snippet = "\n".join(lines)[:600]
