"""Tests for portable paths persisted in public run artifacts."""

from pathlib import Path

from daily_ai_insight.paths import portable_path


def test_portable_path_is_relative_inside_project_root(tmp_path: Path) -> None:
    artifact = tmp_path / "data" / "runs" / "manifest.json"

    assert portable_path(artifact, tmp_path) == "data/runs/manifest.json"
