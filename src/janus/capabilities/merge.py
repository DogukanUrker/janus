from __future__ import annotations

import logging

from janus.autonomy.engine import Signals
from janus.autonomy.gates import auto_merge_allowed, derive_change_class
from janus.autonomy.levels import Capability
from janus.capabilities.base import Context, act_or_escalate

logger = logging.getLogger(__name__)


async def evaluate_merge(ctx: Context, pr_number: int) -> None:
    pr = await ctx.gh.get_pr(ctx.repo, pr_number)
    if pr.get("state") != "open" or pr.get("draft"):
        return

    diff = await ctx.gh.get_pr_diff_summary(ctx.repo, pr_number)
    ci_green = await ctx.gh.get_check_status(ctx.repo, pr["head"]["sha"])
    allowed, failures = auto_merge_allowed(diff, ci_green, ctx.policy.auto_merge)

    change_class = derive_change_class(diff.paths, ctx.policy.auto_merge)
    stats = (
        f"class={change_class}, {diff.additions + diff.deletions} lines, "
        f"{diff.files} files, ci={'green' if ci_green else 'red'}"
    )
    signals = Signals(gate_failures=failures)

    await act_or_escalate(
        ctx,
        Capability.MERGE_PR,
        f"merge PR #{pr_number} [{stats}]",
        {"number": pr_number, "gates": failures or ["all passed"]},
        signals,
    )
