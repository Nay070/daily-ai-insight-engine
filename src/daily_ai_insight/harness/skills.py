"""Load repository-local SKILL.md files as stable Pydantic AI capabilities.

This deliberately small adapter uses Pydantic AI's capability interface so the
project's domain instructions remain versioned, validated, and portable.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic_ai.capabilities import AbstractCapability


@dataclass(frozen=True)
class LoadedSkill:
    name: str
    description: str
    instructions: str
    path: Path


def load_skill(skill_dir: Path) -> LoadedSkill:
    """Read and validate the frontmatter and instruction body of one SKILL.md."""

    path = skill_dir / "SKILL.md"
    if not path.is_file():
        raise FileNotFoundError(f"missing skill file: {path}")

    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise ValueError(f"skill frontmatter must start with '---': {path}")

    try:
        frontmatter_text, instructions = text[4:].split("\n---\n", maxsplit=1)
    except ValueError as error:
        raise ValueError(f"skill frontmatter is not terminated: {path}") from error

    frontmatter = yaml.safe_load(frontmatter_text)
    if not isinstance(frontmatter, dict):
        raise TypeError(f"skill frontmatter must be a mapping: {path}")

    name = frontmatter.get("name")
    description = frontmatter.get("description")
    if not isinstance(name, str) or not name.strip():
        raise ValueError(f"skill name is required: {path}")
    if name != skill_dir.name:
        raise ValueError(f"skill name {name!r} must match directory {skill_dir.name!r}")
    if not isinstance(description, str) or not description.strip():
        raise ValueError(f"skill description is required: {path}")
    if not instructions.strip():
        raise ValueError(f"skill instructions are empty: {path}")

    return LoadedSkill(
        name=name,
        description=description.strip(),
        instructions=instructions.strip(),
        path=path.resolve(),
    )


class SkillCapability(AbstractCapability[Any]):
    """Expose a validated SKILL.md body as model instructions."""

    def __init__(self, skill_dir: Path, *, defer_loading: bool = False) -> None:
        skill = load_skill(skill_dir)
        self.id = skill.name
        self.description = skill.description
        self.defer_loading = defer_loading
        self.skill = skill

    def get_instructions(self) -> str:
        return f"## Skill: {self.skill.name}\n\n{self.skill.instructions}"
