from __future__ import annotations

import logging
from typing import Any

from janus.store import repo as store
from janus.store.oss import archive

logger = logging.getLogger(__name__)


async def record(
    repo_full_name: str, capability: str, level: str, summary: str, detail: dict[str, Any]
) -> int:
    action_id = await store.log_action(repo_full_name, capability, level, summary, detail, None)
    try:
        oss_key = await archive().put_action_detail(action_id, {"summary": summary, **detail})
    except Exception:
        logger.exception("failed to archive action %s to OSS", action_id)
        return action_id
    await _attach_oss_key(action_id, oss_key)
    return action_id


async def _attach_oss_key(action_id: int, oss_key: str) -> None:
    from sqlalchemy import update

    from janus.store.db import session
    from janus.store.schema import ActionLog

    async with session() as s:
        await s.execute(update(ActionLog).where(ActionLog.id == action_id).values(oss_key=oss_key))
