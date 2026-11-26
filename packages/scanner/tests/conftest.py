import os
import pathlib

S = pathlib.Path("/tmp/claude-0/-home-claude/162ae94c-78d8-5309-ab2c-5867527ed50b/scratchpad")
for d in (S / "semgrepenv" / "bin", S / "tools", S / "venv" / "bin"):
    if d.exists():
        os.environ["SCANNER_TOOL_PATH"] = os.pathsep.join(filter(None, [os.environ.get("SCANNER_TOOL_PATH"), str(d)]))
