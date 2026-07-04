from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from janus.autonomy.engine import Resolution, Signals, resolve
from janus.autonomy.levels import AutonomyLevel, Capability
from janus.config.policy import Policy
from janus.github.client import GitHubClient
from janus.models.router import Budget
from janus.store import audit
from janus.store import repo as store

logger = logging.getLogger(__name__)

MARKER = "\n\n— Janus 🤖 (autonomous maintainer; reply or reopen to overrule)"


@dataclass
class Context:
    gh: GitHubClient
    repo: str
    policy: Policy
    agents_md: str
    budget: Budget
    payload: dict[str, Any]


Executor = Callable[[GitHubClient, dict[str, Any]], Awaitable[None]]
_EXECUTORS: dict[Capability, Executor] = {}


def executor(capability: Capability) -> Callable[[Executor], Executor]:
    def _inner(fn: Executor) -> Executor:
        _EXECUTORS[capability] = fn
        return fn

    return _inner


async def execute(gh: GitHubClient, capability: Capability, payload: dict[str, Any]) -> None:
    await _EXECUTORS[capability](gh, payload)


async def act_or_escalate(
    ctx: Context,
    capability: Capability,
    summary: str,
    payload: dict[str, Any],
    signals: Signals | None = None,
) -> Resolution:
    resolution = resolve(capability, ctx.policy, signals=signals)
    detail = {"payload": payload, "reasons": resolution.reasons}

    if resolution.level is AutonomyLevel.OFF:
        logger.info("[%s] %s: off", ctx.repo, capability)

    elif resolution.level is AutonomyLevel.SUGGEST:
        number = payload.get("number")
        if number:
            await ctx.gh.create_comment(
                ctx.repo, number, f"**Suggestion** ({capability}): {summary}{MARKER}"
            )
        await audit.record(ctx.repo, capability, resolution.level, summary, detail)

    elif resolution.level is AutonomyLevel.ASK:
        approval = await store.create_approval(ctx.repo, capability, payload, summary)
        from janus.telegram import bot

        await bot.send_approval(approval, summary, resolution.reasons)
        await audit.record(ctx.repo, capability, resolution.level, f"escalated: {summary}", detail)

    else:
        await execute(ctx.gh, capability, {**payload, "repo": ctx.repo})
        await audit.record(ctx.repo, capability, resolution.level, summary, detail)
        from janus.telegram import bot

        await bot.notify(f"[{ctx.repo}] {capability}: {summary}")

    return resolution


@executor(Capability.LABEL)
async def _label(gh: GitHubClient, p: dict[str, Any]) -> None:
    if p.get("labels"):
        await gh.add_labels(p["repo"], p["number"], p["labels"])


@executor(Capability.VAGUE_NUDGE)
async def _vague_nudge(gh: GitHubClient, p: dict[str, Any]) -> None:
    await gh.create_comment(p["repo"], p["number"], p["body"] + MARKER)


@executor(Capability.CLOSE_ISSUE)
async def _close_issue(gh: GitHubClient, p: dict[str, Any]) -> None:
    await gh.create_comment(p["repo"], p["number"], p["body"] + MARKER)
    await gh.close_issue(p["repo"], p["number"])


@executor(Capability.REVIEW_PR)
async def _review_pr(gh: GitHubClient, p: dict[str, Any]) -> None:
    await gh.create_review(p["repo"], p["number"], p["event"], p["body"] + MARKER)


@executor(Capability.CLOSE_HUMAN_PR)
async def _close_human_pr(gh: GitHubClient, p: dict[str, Any]) -> None:
    await gh.create_comment(p["repo"], p["number"], p["body"] + MARKER)
    await gh.close_pr(p["repo"], p["number"])


@executor(Capability.PLAN_ISSUE)
async def _plan_issue(gh: GitHubClient, p: dict[str, Any]) -> None:
    await gh.create_comment(p["repo"], p["number"], p["body"] + MARKER)


@executor(Capability.MERGE_PR)
async def _merge_pr(gh: GitHubClient, p: dict[str, Any]) -> None:
    await gh.merge_pr(p["repo"], p["number"])


@executor(Capability.WRITE_PR)
async def _write_pr(gh: GitHubClient, p: dict[str, Any]) -> None:
    from janus.capabilities.codegen import run_codegen_job

    await run_codegen_job(gh, p["repo"], p["number"], p["plan"], p.get("budget_tokens", 60_000))
