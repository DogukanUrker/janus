from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from typing import Any


@dataclass
class InboundEvent:
    delivery_id: str
    event_type: str
    action: str
    repo_full_name: str
    installation_id: int
    sender_login: str
    sender_type: str
    payload: dict[str, Any]


def verify_signature(secret: str, body: bytes, signature_header: str | None) -> bool:
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(f"sha256={expected}", signature_header)


def parse(headers: dict[str, str], payload: dict[str, Any]) -> InboundEvent:
    sender = payload.get("sender") or {}
    return InboundEvent(
        delivery_id=headers.get("x-github-delivery", ""),
        event_type=headers.get("x-github-event", ""),
        action=payload.get("action", ""),
        repo_full_name=(payload.get("repository") or {}).get("full_name", ""),
        installation_id=(payload.get("installation") or {}).get("id", 0),
        sender_login=sender.get("login", ""),
        sender_type=sender.get("type", ""),
        payload=payload,
    )
