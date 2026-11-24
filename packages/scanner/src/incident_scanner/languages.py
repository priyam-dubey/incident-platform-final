from __future__ import annotations

import os

EXT = {".py": "python", ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript", ".cjs": "javascript",
       ".ts": "typescript", ".tsx": "typescript", ".go": "go", ".java": "java", ".rb": "ruby", ".php": "php", ".rs": "rust",
       ".tf": "terraform", ".yml": "yaml", ".yaml": "yaml", ".json": "json", ".sh": "shell", ".dockerfile": "docker"}
SKIP_DIRS = {"node_modules", ".git", "venv", ".venv", "__pycache__", "dist", "build", ".next", "vendor", "coverage", ".tox"}
CODE = {"python", "javascript", "typescript", "go", "java", "ruby", "php", "rust"}


def walk(root: str) -> tuple[list[str], dict[str, int]]:
    files, langs = [], {}
    for dp, dn, fn in os.walk(root):
        dn[:] = [d for d in dn if d not in SKIP_DIRS]
        for f in fn:
            rel = os.path.relpath(os.path.join(dp, f), root).replace(os.sep, "/")
            files.append(rel)
            lang = EXT.get(os.path.splitext(f)[1].lower()) or ("docker" if f == "Dockerfile" else None)
            if lang in CODE:
                langs[lang] = langs.get(lang, 0) + 1
    return files, langs
