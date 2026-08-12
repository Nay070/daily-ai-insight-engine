"""Portable path formatting for persisted project artifacts."""

from __future__ import annotations

from pathlib import Path


def portable_path(path: Path, root: Path | None = None) -> str:
    """Return a POSIX-style path, relative to ``root`` when possible."""

    if root is None:
        return path.as_posix()
    resolved = path.resolve()
    try:
        return resolved.relative_to(root.resolve()).as_posix()
    except ValueError:
        return resolved.as_posix()
