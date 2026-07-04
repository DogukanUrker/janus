from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from janus.store.db import async_session, session
from janus.store.schema import ActionLog, Approval, WebhookEvent, utcnow


async def enqueue_event(
    delivery_id: str, event_type: str, action: str, repo: str, payload: dict[str, Any]
) -> bool:
    try:
        async with session() as s:
            s.add(
                WebhookEvent(
                    delivery_id=delivery_id,
                    event_type=event_type,
                    action=action,
                    repo_full_name=repo,
                    payload=payload,
                )
            )
        return True
    except IntegrityError:
        return False


async def claim_next_event() -> WebhookEvent | None:
    async with async_session() as s, s.begin():
        stmt = (
            select(WebhookEvent)
            .where(WebhookEvent.status == "pending")
            .order_by(WebhookEvent.id)
            .limit(1)
        )
        if s.bind.dialect.name == "postgresql":
            stmt = stmt.with_for_update(skip_locked=True)
        event = (await s.execute(stmt)).scalar_one_or_none()
        if event is None:
            return None
        event.status = "processing"
        return event


async def finish_event(event_id: int, status: str) -> None:
    async with session() as s:
        await s.execute(
            update(WebhookEvent).where(WebhookEvent.id == event_id).values(status=status)
        )


async def create_approval(
    repo: str, capability: str, action_payload: dict[str, Any], summary: str
) -> Approval:
    async with session() as s:
        approval = Approval(
            repo_full_name=repo,
            capability=capability,
            action_payload={**action_payload, "summary": summary},
        )
        s.add(approval)
        await s.flush()
        return approval


async def set_approval_message(approval_id: int, tg_message_id: str) -> None:
    async with session() as s:
        await s.execute(
            update(Approval).where(Approval.id == approval_id).values(tg_message_id=tg_message_id)
        )


async def resolve_approval(approval_id: int, status: str, comment: str | None = None) -> None:
    async with session() as s:
        await s.execute(
            update(Approval)
            .where(Approval.id == approval_id, Approval.status == "pending")
            .values(status=status, reject_comment=comment, resolved_at=utcnow())
        )


async def claim_resolved_approvals() -> list[Approval]:
    async with async_session() as s, s.begin():
        stmt = select(Approval).where(
            Approval.status.in_(["approved", "rejected"]), Approval.executed_at.is_(None)
        )
        if s.bind.dialect.name == "postgresql":
            stmt = stmt.with_for_update(skip_locked=True)
        approvals = list((await s.execute(stmt)).scalars())
        for a in approvals:
            a.executed_at = utcnow()
        return approvals


async def stale_pending_approvals(older_than_hours: int = 48) -> list[Approval]:
    cutoff = datetime.now(UTC) - timedelta(hours=older_than_hours)
    async with async_session() as s:
        stmt = select(Approval).where(Approval.status == "pending", Approval.created_at < cutoff)
        return list((await s.execute(stmt)).scalars())


async def log_action(
    repo: str,
    capability: str,
    level: str,
    summary: str,
    detail: dict[str, Any],
    oss_key: str | None,
) -> int:
    async with session() as s:
        row = ActionLog(
            repo_full_name=repo,
            capability=capability,
            level=level,
            summary=summary,
            detail=detail,
            oss_key=oss_key,
        )
        s.add(row)
        await s.flush()
        return row.id
