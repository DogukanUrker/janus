from __future__ import annotations

import re

_ESCAPE = re.compile(r"([_*\[\]()~`>#+\-=|{}.!])")


def escape(text: str) -> str:
    return _ESCAPE.sub(r"\\\1", text)


def approval_card(
    approval_id: int, repo: str, capability: str, summary: str, reasons: list[str]
) -> str:
    lines = [
        f"*Janus needs a decision* \\(\\#{approval_id}\\)",
        f"repo: {escape(repo)}",
        f"action: {escape(capability)}",
        "",
        escape(summary),
        "",
        "*why escalated:*",
        *[f"• {escape(r)}" for r in reasons],
    ]
    return "\n".join(lines)
