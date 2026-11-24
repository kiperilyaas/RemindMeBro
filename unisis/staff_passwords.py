"""Shared by UniLearn and UniSIS: random passwords for staff accounts, written to a local file."""
from __future__ import annotations

import secrets
from pathlib import Path
from typing import Dict, List, Tuple


def new_password() -> str:
    return secrets.token_urlsafe(9)   # 12 characters


def write_password_file(path: Path, title: str, rotated: List[Tuple[str, str]]) -> None:
    rows: Dict[str, str] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line and not line.startswith("#") and len(line.split()) == 2:
                name, pw = line.split()
                rows[name] = pw
    rows.update(dict(rotated))
    body = "\n".join(f"{name:<34}  {pw}" for name, pw in sorted(rows.items()))
    path.write_text(f"# {title}\n# Only on this computer. Do not share this file.\n{body}\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
