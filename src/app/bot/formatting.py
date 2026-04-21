from __future__ import annotations

import html
import re

_PLACEHOLDER_TEMPLATE = "\x00{}\x00"
_INLINE_CODE_PATTERN = re.compile(r"`([^`\n]+)`")
_MARKDOWN_LINK_PATTERN = re.compile(r"\[([^\]\n]+)\]\((https?://[^\s)]+)\)")
_BOLD_PATTERN = re.compile(r"\*\*([^\n*][^\n]*?)\*\*")


def render_telegram_html(text: str) -> str:
    placeholders: list[str] = []

    def reserve(value: str) -> str:
        placeholders.append(value)
        return _PLACEHOLDER_TEMPLATE.format(len(placeholders) - 1)

    rendered = text.replace("\r\n", "\n")
    rendered = _INLINE_CODE_PATTERN.sub(
        lambda match: reserve(f"<code>{html.escape(match.group(1))}</code>"),
        rendered,
    )
    rendered = _MARKDOWN_LINK_PATTERN.sub(
        lambda match: reserve(
            f'<a href="{html.escape(match.group(2), quote=True)}">{html.escape(match.group(1))}</a>'
        ),
        rendered,
    )
    rendered = _BOLD_PATTERN.sub(
        lambda match: reserve(f"<b>{html.escape(match.group(1))}</b>"),
        rendered,
    )
    rendered = html.escape(rendered)
    for index, value in enumerate(placeholders):
        rendered = rendered.replace(_PLACEHOLDER_TEMPLATE.format(index), value)
    return rendered
