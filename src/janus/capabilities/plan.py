from __future__ import annotations

import json
import logging

from janus.autonomy.engine import Resolution, Signals
from janus.autonomy.levels import AutonomyLevel, Capability
from janus.capabilities.base import Context, act_or_escalate
from janus.models.prompts import get_prompt
from janus.models.tiers import Tier

logger = logging.getLogger(__name__)

MAX_FILE_READS = 8

READ_FILE_TOOL = {
    "type": "function",
    "function": {
        "name": "read_file",
        "description": "Read a file from the repository by exact path.",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
}


async def run_plan(
    ctx: Context, number: int, title: str, body: str, vision: str, signals: Signals
) -> Resolution | None:
    tree = await ctx.gh.get_tree(ctx.repo)
    user = (
        f"## Project (AGENTS.md)\n{ctx.agents_md}\n\n"
        f"## Issue #{number}: {title}\n{body}\n\n"
        f"## File tree\n" + "\n".join(tree[:400])
    )
    if vision:
        user += f"\n\n## Screenshot analysis\n{vision}"

    messages: list[dict] = [
        {"role": "system", "content": get_prompt(Capability.PLAN_ISSUE, Tier.MAX)},
        {"role": "user", "content": user},
    ]

    plan_text = ""
    for _ in range(MAX_FILE_READS + 1):
        response = await ctx.budget.complete(Tier.MAX, messages, tools=[READ_FILE_TOOL])
        message = response.choices[0].message
        if not message.tool_calls:
            plan_text = message.content or ""
            break
        messages.append(message.model_dump(exclude_none=True))
        for call in message.tool_calls:
            path = json.loads(call.function.arguments).get("path", "")
            content = await ctx.gh.get_file(ctx.repo, path) or "(file not found)"
            messages.append(
                {"role": "tool", "tool_call_id": call.id, "content": content[:20_000]}
            )
    else:
        plan_text = "Plan generation hit the file-read cap without concluding."
        signals = Signals(uncertainty=True, gate_failures=signals.gate_failures)

    if not plan_text.strip():
        logger.warning("[%s] empty plan for #%s", ctx.repo, number)
        return None

    resolution = await act_or_escalate(
        ctx,
        Capability.PLAN_ISSUE,
        f"post implementation plan on #{number}",
        {"number": number, "body": plan_text},
        signals,
    )

    if resolution.level is AutonomyLevel.AUTO:
        await act_or_escalate(
            ctx,
            Capability.WRITE_PR,
            f"implement #{number} and open a PR",
            {
                "number": number,
                "plan": plan_text,
                "budget_tokens": ctx.policy.budget.max_tokens_per_event,
            },
            signals,
        )
    return resolution
