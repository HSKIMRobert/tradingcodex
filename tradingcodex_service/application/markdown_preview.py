from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import nh3
import yaml
from markdown_it import MarkdownIt


@dataclass(frozen=True)
class MarkdownPreview:
    markdown: str
    html: str
    source_file: str
    source_label: str
    frontmatter: dict[str, Any]
    metadata_items: list[dict[str, str]]
    heading: str


_MARKDOWN = MarkdownIt("default", {"html": False, "linkify": False, "typographer": False})

_ALLOWED_TAGS = {
    "a",
    "blockquote",
    "br",
    "code",
    "del",
    "em",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "hr",
    "li",
    "ol",
    "p",
    "pre",
    "strong",
    "table",
    "tbody",
    "td",
    "th",
    "thead",
    "tr",
    "ul",
}

_ALLOWED_ATTRIBUTES = {
    "a": {"href", "title"},
    "th": {"align"},
    "td": {"align"},
}


def render_markdown_preview(
    markdown: str,
    *,
    source_file: str = "",
    source_label: str = "",
    strip_frontmatter: bool = True,
) -> MarkdownPreview:
    document = split_markdown_frontmatter(markdown or "") if strip_frontmatter else MarkdownDocument({}, "", markdown or "")
    body = document.body
    raw_html = _MARKDOWN.render(body or "")
    clean_html = nh3.clean(
        raw_html,
        tags=_ALLOWED_TAGS,
        attributes=_ALLOWED_ATTRIBUTES,
        url_schemes={"http", "https", "mailto"},
    )
    return MarkdownPreview(
        markdown=body,
        html=clean_html,
        source_file=source_file,
        source_label=source_label or "markdown",
        frontmatter=document.frontmatter,
        metadata_items=frontmatter_items(document.frontmatter),
        heading=document.heading,
    )


def read_markdown_preview(path: Path, *, source_file: str = "", source_label: str = "") -> MarkdownPreview:
    try:
        markdown = path.read_text(encoding="utf-8")
    except Exception:
        markdown = "_No markdown available._"
    return render_markdown_preview(markdown, source_file=source_file or str(path), source_label=source_label)


@dataclass(frozen=True)
class MarkdownDocument:
    frontmatter: dict[str, Any]
    heading: str
    body: str


def split_markdown_frontmatter(markdown: str) -> MarkdownDocument:
    lines = (markdown or "").splitlines()
    frontmatter: dict[str, Any] = {}
    body_lines = lines
    if lines and lines[0].strip() == "---":
        for index, line in enumerate(lines[1:], start=1):
            if line.strip() == "---":
                raw_frontmatter = "\n".join(lines[1:index])
                frontmatter = parse_simple_frontmatter(raw_frontmatter)
                body_lines = lines[index + 1 :]
                break
    heading = ""
    for line in body_lines:
        stripped = line.strip()
        if stripped.startswith("#"):
            heading = stripped.lstrip("#").strip()
            break
    body = "\n".join(body_lines).strip()
    return MarkdownDocument(frontmatter=frontmatter, heading=heading, body=body + ("\n" if body else ""))


def parse_simple_frontmatter(text: str) -> dict[str, Any]:
    try:
        parsed = yaml.safe_load(text or "") or {}
    except yaml.YAMLError:
        return {}
    return _normalize_frontmatter(parsed) if isinstance(parsed, dict) else {}


def _normalize_frontmatter(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, list):
        return [_normalize_frontmatter(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _normalize_frontmatter(item) for key, item in value.items()}
    return value


def frontmatter_items(frontmatter: dict[str, Any]) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for key, value in frontmatter.items():
        if value is None or value == "":
            continue
        if isinstance(value, bool):
            rendered = "true" if value else "false"
        elif isinstance(value, (list, tuple)):
            rendered = ", ".join(str(item) for item in value)
        else:
            rendered = str(value)
        items.append({"key": str(key), "label": str(key).replace("_", " ").title(), "value": rendered})
    return items
