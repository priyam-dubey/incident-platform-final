from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

SEVERITIES = ("critical", "high", "medium", "low", "info")
CATEGORIES = ("sast", "lint", "types", "dependency", "secret", "iac", "other")
MAX_SNIPPET = 600


@dataclass
class RawFinding:
    tool: str
    rule_id: str
    category: str
    severity: str
    title: str
    message: str = ""
    file_path: str | None = None
    start_line: int | None = None
    end_line: int | None = None
    snippet: str | None = None
    cwe: str | None = None
    package_name: str | None = None
    package_version: str | None = None
    fixed_version: str | None = None

    def __post_init__(self) -> None:
        if self.severity not in SEVERITIES:
            self.severity = "info"
        if self.category not in CATEGORIES:
            self.category = "other"
        self.title = (self.title or self.rule_id)[:300]
        self.message = (self.message or "")[:2000]
        if self.snippet:
            self.snippet = self.snippet[:MAX_SNIPPET]

    @property
    def fingerprint(self) -> str:
        """Stable across commits: identifies the issue by tool+rule+file+code content (or package), not line number,
        so unrelated edits that shift lines do not make an old finding look new."""
        if self.category == "dependency":
            basis = f"{self.tool}|{self.rule_id}|{self.package_name}|{self.file_path}"
        else:
            basis = f"{self.tool}|{self.rule_id}|{self.file_path}|{re.sub(r'\s+', ' ', self.snippet or self.message).strip()}"
        return hashlib.sha256(basis.encode()).hexdigest()[:40]


def norm_path(path: str | None, root: str) -> str | None:
    if not path:
        return None
    p = path.replace("\\", "/")
    r = root.rstrip("/") + "/"
    if p.startswith(r):
        p = p[len(r):]
    return p.lstrip("./") if p.startswith("./") else p
