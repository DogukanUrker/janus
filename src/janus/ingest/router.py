from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from janus.github.webhook import parse, verify_signature
from janus.settings import settings
from janus.store import repo as store

logger = logging.getLogger(__name__)
router = APIRouter()

HANDLED = {"issues", "issue_comment", "pull_request", "pull_request_review", "check_suite"}
MAX_BODY = 1_000_000


@router.get("/healthz")
async def healthz() -> dict[str, bool]:
    return {"ok": True}


@router.post("/webhook")
async def webhook(request: Request) -> Response:
    body = await request.body()
    if len(body) > MAX_BODY:
        return Response(status_code=413)
    if not verify_signature(
        settings.github_webhook_secret, body, request.headers.get("x-hub-signature-256")
    ):
        return Response(status_code=401)

    event = parse(dict(request.headers), json.loads(body))

    if event.sender_type == "Bot" and event.sender_login == f"{settings.github_app_slug}[bot]":
        logger.info("dropped self-authored event %s", event.delivery_id)
        return JSONResponse({"self": True})
    if event.event_type not in HANDLED:
        return JSONResponse({"ignored": True})

    enqueued = await store.enqueue_event(
        event.delivery_id, event.event_type, event.action, event.repo_full_name, event.payload
    )
    return JSONResponse({"queued": True} if enqueued else {"dedup": True})
