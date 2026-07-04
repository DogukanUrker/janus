from __future__ import annotations

from janus.autonomy.engine import Signals
from janus.autonomy.levels import Capability
from janus.capabilities.base import Context, act_or_escalate
from janus.models.prompts import get_prompt
from janus.models.tiers import Tier

REVIEW_EVENTS = {
    "approve": "APPROVE",
    "request_changes": "REQUEST_CHANGES",
    "comment": "COMMENT",
}


async def run_review(ctx: Context) -> None:
    pr = ctx.payload["pull_request"]
    number = pr["number"]
    diff = await ctx.gh.get_pr_diff_text(ctx.repo, number)

    verdict = await ctx.budget.complete_json(
        Tier.MID,
        [
            {"role": "system", "content": get_prompt(Capability.REVIEW_PR, Tier.MID)},
            {
                "role": "user",
                "content": (
                    f"## Project (AGENTS.md)\n{ctx.agents_md}\n\n"
                    f"## PR #{number}: {pr.get('title', '')}\n{pr.get('body') or ''}\n\n"
                    f"## Diff\n{diff}"
                ),
            },
        ],
    )
    signals = Signals(uncertainty=bool(verdict.get("uncertain")))
    body = verdict.get("body", "")

    if verdict.get("verdict") == "junk":
        await act_or_escalate(
            ctx,
            Capability.CLOSE_HUMAN_PR,
            f"close PR #{number} as junk",
            {"number": number, "body": body},
            signals,
        )
        return

    event = REVIEW_EVENTS.get(verdict.get("verdict", "comment"), "COMMENT")
    await act_or_escalate(
        ctx,
        Capability.REVIEW_PR,
        f"review PR #{number}: {event.lower()}",
        {"number": number, "event": event, "body": body},
        signals,
    )
