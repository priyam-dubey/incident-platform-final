# Code scanning

Deterministic tools produce findings; the LLM (optional) only explains them.

| Tool | Covers | Notes |
|---|---|---|
| Semgrep (OSS, fixed rules in `packages/scanner/rules`) | SAST, JS/TS/Python | rules are ours, not the repo's |
| Bandit, Ruff | Python security / lint | |
| ESLint (fixed config), `tsc` | JS/TS | the repo's own eslint config is never loaded |
| npm audit, pip-audit | dependency advisories | need network for advisory data |
| Gitleaks | secrets | matches are redacted before storage |
| Trivy | filesystem vulnerabilities / misconfig | |

Each scan records a per-tool status: `ok`, `skipped`, `unavailable` (not installed) or `failed`. A missing tool is shown
as such, never as "0 findings".

## Safety model
The worker downloads a tarball and *reads* it. It does not install dependencies, run scripts, build, or import repo code.
Tools run in a sandbox: network namespace isolation (`unshare -rn`, where the kernel allows it), rlimits, a scrubbed
environment and a timeout. Extraction rejects `..`, absolute paths, links, devices and executable bits, with file-count and
size caps. Run the worker in its own container (`apps/api-gateway/Dockerfile.worker`) with no secrets other than what it needs.

## Lifecycle
Findings have stable fingerprints (line shifts don't re-open them) and states `new / unchanged / fixed / reintroduced`.
Triage (`open / ignored / false_positive / accepted_risk`; `fixed` is set by re-scans) survives re-scans. Pull-request and branch scans are
stored on the scan and never alter default-branch state.

## Installing the tools
The worker image installs everything. Locally: `pip install bandit ruff pip-audit`, Semgrep in its own venv, plus
Gitleaks, Trivy, Node (eslint, typescript). Override discovery with `SCANNER_TOOL_PATH`; limit tools with `SCAN_ENABLED_TOOLS`.
