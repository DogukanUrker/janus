from __future__ import annotations

import logging
from typing import Any

from janus.autonomy.engine import Signals
from janus.autonomy.levels import AutonomyLevel, Capability
from janus.capabilities.base import Context, act_or_escalate
from janus.capabilities.vision import analyze_images
from janus.github.client import extract_image_urls
from janus.models.prompts import get_prompt
from janus.models.tiers import Tier

logger = logging.getLogger(__name__)


async def run_triage(ctx: Context) -> None:
    issue = ctx.payload["issue"]
    number = issue["number"]
    title = issue.get("title", "")
    body = issue.get("body") or ""

    vision_findings = ""
    image_urls = extract_image_urls(body)
    if image_urls and ctx.policy.vision:
        vision_findings = await analyze_images(ctx, image_urls, f"{title}\n\n{body}")

    labels = await ctx.gh.get_labels(ctx.repo)
    open_issues = await ctx.gh.list_open_issues(ctx.repo)
    others = "\n".join(
        f"#{i['number']}: {i['title']}" for i in open_issues if i["number"] != number
    )

    verdict = await _classify(ctx, title, body, labels, others, vision_findings)
    signals = Signals(uncertainty=bool(verdict.get("uncertain")))
    reason = verdict.get("reason", "")

    if verdict.get("labels"):
        await act_or_escalate(
            ctx,
            Capability.LABEL,
            f"label #{number} as {verdict['labels']}",
            {"number": number, "labels": verdict["labels"]},
            signals,
        )

    kind = verdict.get("verdict")
    if kind in ("spam", "duplicate", "off_topic"):
        dup = verdict.get("duplicate_of")
        suffix = f"\n\nDuplicate of #{dup}." if kind == "duplicate" and dup else ""
        await act_or_escalate(
            ctx,
            Capability.CLOSE_ISSUE,
            f"close #{number} as {kind}",
            {"number": number, "body": f"{reason}{suffix}"},
            signals,
        )
    elif kind == "vague":
        nudge = await ctx.budget.complete_json(
            Tier.MID,
            [
                {"role": "system", "content": get_prompt(Capability.VAGUE_NUDGE, Tier.MID)},
                {
                    "role": "user",
                    "content": f"Issue #{number}: {title}\n\n{body}\n\nMissing: {reason}",
                },
            ],
        )
        await act_or_escalate(
            ctx,
            Capability.VAGUE_NUDGE,
            f"ask for details on #{number}",
            {"number": number, "body": nudge.get("body", reason)},
            signals,
        )
    elif kind == "actionable":
        from janus.capabilities.plan import run_plan

        resolution = await run_plan(ctx, number, title, body, vision_findings, signals)
        if resolution is not None and resolution.level is AutonomyLevel.AUTO:
            logger.info("[%s] #%s planned; codegen follows", ctx.repo, number)


async def _classify(
    ctx: Context, title: str, body: str, labels: list[str], others: str, vision: str
) -> dict[str, Any]:
    user = (
        f"## Project (AGENTS.md)\n{ctx.agents_md}\n\n"
        f"## Existing labels\n{', '.join(labels)}\n\n"
        f"## Open issues\n{others or '(none)'}\n\n"
        f"## Incoming issue\n{title}\n\n{body}"
    )
    if vision:
        user += f"\n\n## Screenshot analysis\n{vision}"
    return await ctx.budget.complete_json(
        Tier.MID,
        [
            {"role": "system", "content": get_prompt(Capability.CLOSE_ISSUE, Tier.MID)},
            {"role": "user", "content": user},
        ],
    )
