"""Run analysis tools with no network, tight resource limits and a scrubbed environment.

None of the tools run in this module execute repository code: they read files statically. The sandbox is
defence in depth against tool vulnerabilities and hostile files (e.g. decompression bombs, huge inputs).
"""

from __future__ import annotations

import os
import resource
import shutil
import subprocess
import tempfile
from dataclasses import dataclass

MAX_OUTPUT = 20_000_000


@dataclass
class RunResult:
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False


_NETNS: bool | None = None


def network_isolation_available() -> bool:
    global _NETNS
    if _NETNS is None:
        try:
            _NETNS = bool(shutil.which("unshare")) and subprocess.run(["unshare", "-rn", "true"], capture_output=True, timeout=5).returncode == 0
        except Exception:
            _NETNS = False
    return _NETNS


def _limits(cpu_seconds: int, mem_bytes: int):
    def apply():
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds + 5))
        resource.setrlimit(resource.RLIMIT_FSIZE, (200_000_000, 200_000_000))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        if mem_bytes:
            resource.setrlimit(resource.RLIMIT_AS, (mem_bytes, mem_bytes))
        os.setsid()
    return apply


def run(cmd: list[str], cwd: str, timeout: int = 120, network: bool = False, mem_mb: int = 2048,
        extra_env: dict[str, str] | None = None, extra_path: list[str] | None = None) -> RunResult:
    """`network=True` is only for dependency-audit tools that must query advisory databases; they read lockfiles only."""
    home = tempfile.mkdtemp(prefix="scan-home-")
    path = os.pathsep.join([*(extra_path or []), os.path.dirname(shutil.which("python3") or "/usr/bin"), "/usr/local/bin", "/usr/bin", "/bin"])
    env = {"PATH": path, "HOME": home, "TMPDIR": home, "LANG": "C.UTF-8", "CI": "1", "NO_COLOR": "1", **(extra_env or {})}
    for k in ("HTTPS_PROXY", "HTTP_PROXY", "NODE_EXTRA_CA_CERTS", "SSL_CERT_FILE", "REQUESTS_CA_BUNDLE") if network else ():
        if os.environ.get(k):
            env[k] = os.environ[k]
    full = (["unshare", "-rn", *cmd]) if (not network and network_isolation_available()) else cmd
    try:
        p = subprocess.run(full, cwd=cwd, env=env, capture_output=True, timeout=timeout, preexec_fn=_limits(timeout, mem_mb * 1024 * 1024 if mem_mb else 0))
        return RunResult(p.returncode, p.stdout[:MAX_OUTPUT].decode("utf-8", "replace"), p.stderr[:200_000].decode("utf-8", "replace"))
    except subprocess.TimeoutExpired as e:
        return RunResult(-1, (e.stdout or b"")[:MAX_OUTPUT].decode("utf-8", "replace") if e.stdout else "", "timeout", timed_out=True)
    finally:
        shutil.rmtree(home, ignore_errors=True)
