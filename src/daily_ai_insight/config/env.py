"""Load a small allowlist of local environment values without extra dependencies."""

from __future__ import annotations

import os
from pathlib import Path

ALLOWED_KEYS = {
    "DEEPSEEK_API_KEY",
    "MODEL_NAME",
    "OPENAI_API_KEY",
}


def load_project_env(path: Path) -> dict[str, str]:
    """Load allowed ``KEY=value`` entries without overriding process variables."""

    if not path.is_file():
        return {}

    loaded: dict[str, str] = {}
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"invalid .env line {line_number}: expected KEY=value")
        key, value = (part.strip() for part in line.split("=", maxsplit=1))
        if key not in ALLOWED_KEYS:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        if value and key not in os.environ:
            os.environ[key] = value
            loaded[key] = value
    return loaded
