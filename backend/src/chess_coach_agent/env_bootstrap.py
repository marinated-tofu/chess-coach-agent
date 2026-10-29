from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv

_PACKAGE_DIR = Path(__file__).resolve().parent
_BACKEND_DIR = _PACKAGE_DIR.parents[1]
_REPO_ROOT = _PACKAGE_DIR.parents[2]


def load_project_env() -> None:
    """Load .env from cwd, backend/, or repo root (first wins per file)."""
    candidates = [
        Path.cwd() / ".env",
        _BACKEND_DIR / ".env",
        _REPO_ROOT / ".env",
    ]
    seen: set[Path] = set()
    for path in candidates:
        resolved = path.resolve()
        if resolved in seen or not path.is_file():
            continue
        seen.add(resolved)
        load_dotenv(path, override=False)


load_project_env()
