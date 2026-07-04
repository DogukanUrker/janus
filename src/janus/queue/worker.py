from __future__ import annotations

import asyncio
import logging
import time

from janus.autonomy.levels import Capability
from janus.capabilities.base import execute
from janus.config.policy import Policy, load_policy
from janus.github.client import GitHubClient
from janus.orchestrator import orchestrator
from janus.store import audit
from janus.store import repo as store

logger = logging.getLogger(__name__)

POLL_SECONDS = 2
CONFIG_TTL = 300
REMINDER_HOURS = 48

_config_cache: dict[str, tuple[float, Policy, str]] = {}
_clients: dict[int, GitHubClient] = {}


def _client(installation_id: int) -> GitHubClient:
    if installation_id not in _clients:
        _clients[installation_id] = GitHubClient(installation_id)
    return _clients[installation_id]


async def _repo_config(gh: GitHubClient, repo: str) -> tuple[Policy, str]:
    cached = _config_cache.get(repo)
    if cached and cached[0] > time.time() - CONFIG_TTL:
        return cached[1], cached[2]
    policy = load_policy(await gh.get_file(repo, ".janus/policy.yml"))
    agents_md = await gh.get_file(repo, "AGENTS.md") or "(no AGENTS.md in this repository)"
    _config_cache[repo] = (time.time(), policy, agents_md)
    return policy, agents_md


async def event_loop() -> None:
    while True:
        try:
            event = await store.claim_next_event()
            if event is None:
                await asyncio.sleep(POLL_SECONDS)
                continue
            gh = _client(event.payload.get("installation", {}).get("id", 0))
            policy, agents_md = await _repo_config(gh, event.repo_full_name)
            if policy.paused:
                logger.info("[%s] paused; skipping event %s", event.repo_full_name, event.id)
                await store.finish_event(event.id, "done")
                continue
            await orchestrator.handle(event, policy, agents_md, gh)
            await store.finish_event(event.id, "done")
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("event processing failed")
            if event is not None:
                await store.finish_event(event.id, "failed")


async def approvals_loop() -> None:
    from janus.telegram import bot

    while True:
        try:
            for approval in await store.claim_resolved_approvals():
                gh = _clients.get(next(iter(_clients), 0))
                if gh is None:
                    logger.warning("no github client yet; approval #%s deferred", approval.id)
                    continue
                payload = {**approval.action_payload, "repo": approval.repo_full_name}
                if approval.status == "approved":
                    await execute(gh, Capability(approval.capability), payload)
                    await audit.record(
                        approval.repo_full_name,
                        approval.capability,
                        "ask",
                        f"approved & executed: {payload.get('summary', '')}",
                        {"approval_id": approval.id},
                    )
                    await bot.notify(
                        f"[{approval.repo_full_name}] executed approved {approval.capability}"
                    )
                elif approval.reject_comment and payload.get("number"):
                    await gh.create_comment(
                        approval.repo_full_name, payload["number"], approval.reject_comment
                    )
                    await audit.record(
                        approval.repo_full_name,
                        approval.capability,
                        "ask",
                        "rejected with comment",
                        {"approval_id": approval.id},
                    )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("approvals processing failed")
        await asyncio.sleep(POLL_SECONDS)


async def reminder_loop() -> None:
    from janus.telegram import bot

    while True:
        await asyncio.sleep(3600)
        try:
            stale = await store.stale_pending_approvals(REMINDER_HOURS)
            for approval in stale:
                await bot.notify(
                    f"reminder: approval #{approval.id} on {approval.repo_full_name} "
                    f"({approval.capability}) still pending"
                )
        except Exception:
            logger.exception("reminder loop failed")
