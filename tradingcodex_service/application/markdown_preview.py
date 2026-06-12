from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

import nh3
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
    data: dict[str, Any] = {}
    current_key = ""
    current_list: list[str] | None = None
    for raw_line in (text or "").splitlines():
        line = raw_line.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        stripped = line.strip()
        if current_key and current_list is not None and stripped.startswith("- "):
            current_list.append(str(_parse_frontmatter_scalar(stripped[2:].strip())))
            data[current_key] = current_list
            continue
        current_key = ""
        current_list = None
        if ":" not in line:
            continue
        key, raw_value = line.split(":", 1)
        key = key.strip()
        if not key:
            continue
        raw_value = raw_value.strip()
        if raw_value == "":
            current_key = key
            current_list = []
            data[key] = current_list
            continue
        data[key] = _parse_frontmatter_scalar(raw_value)
    return data


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


def _parse_frontmatter_scalar(raw: str) -> Any:
    if raw in {"true", "True"}:
        return True
    if raw in {"false", "False"}:
        return False
    if raw in {"null", "Null", "None", "~"}:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return raw.strip("'\"")
