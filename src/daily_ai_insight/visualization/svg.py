"""Dependency-light SVG bar charts suitable for reports and GitHub previews."""

from __future__ import annotations

from html import escape
from pathlib import Path


def render_bar_chart(
    rows: list[tuple[str, float]],
    *,
    title: str,
    value_suffix: str = "",
    max_value: float | None = None,
) -> str:
    if not rows:
        raise ValueError("bar chart requires at least one row")
    width = 960
    left = 330
    right = 90
    top = 78
    row_height = 38
    height = top + row_height * len(rows) + 38
    chart_width = width - left - right
    scale_max = max_value or max(value for _, value in rows)
    if scale_max <= 0:
        scale_max = 1

    elements = [
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
            f'viewBox="0 0 {width} {height}" role="img" aria-label="{escape(title)}">'
        ),
        "<style>",
        ".title{font:700 24px system-ui,sans-serif;fill:#172033}",
        ".label{font:14px system-ui,sans-serif;fill:#26324a}",
        ".value{font:600 14px system-ui,sans-serif;fill:#172033}",
        ".bar{fill:#5078e8}",
        ".track{fill:#edf1fb}",
        "</style>",
        f'<rect width="{width}" height="{height}" rx="14" fill="#ffffff"/>',
        f'<text class="title" x="24" y="38">{escape(title)}</text>',
    ]
    for index, (label, value) in enumerate(rows):
        y = top + index * row_height
        display_label = label if len(label) <= 42 else label[:39] + "…"
        bar_width = chart_width * value / scale_max
        elements.extend(
            [
                f'<text class="label" x="24" y="{y + 16}">{escape(display_label)}</text>',
                f'<rect class="track" x="{left}" y="{y}" width="{chart_width}" height="20" rx="5"/>',
                f'<rect class="bar" x="{left}" y="{y}" width="{bar_width:.1f}" height="20" rx="5"/>',
                f'<text class="value" x="{left + chart_width + 12}" y="{y + 16}">{value:g}{escape(value_suffix)}</text>',
            ]
        )
    elements.append("</svg>")
    return "\n".join(elements) + "\n"


def write_bar_chart(
    path: Path,
    rows: list[tuple[str, float]],
    *,
    title: str,
    value_suffix: str = "",
    max_value: float | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        render_bar_chart(
            rows,
            title=title,
            value_suffix=value_suffix,
            max_value=max_value,
        ),
        encoding="utf-8",
        newline="\n",
    )
    temporary.replace(path)
