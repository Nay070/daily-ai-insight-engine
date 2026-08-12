"""Small, deterministic JSON writers used by the MVP."""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from pydantic import BaseModel


def _json_value(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    return value


def write_jsonl(path: Path, values: Iterable[Any]) -> None:
    """Write one compact UTF-8 JSON object per line using an atomic replace."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        for value in values:
            handle.write(
                json.dumps(_json_value(value), ensure_ascii=False, sort_keys=True) + "\n"
            )
    temporary.replace(path)


def write_json(path: Path, value: Any) -> None:
    """Write pretty UTF-8 JSON using an atomic replace."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(_json_value(value), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    temporary.replace(path)

