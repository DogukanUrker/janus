from __future__ import annotations

import json
import logging

from janus.autonomy.gates import matches_any
from janus.autonomy.levels import Capability
from janus.github.auth import installation_token
from janus.github.client import GitHubClient
from janus.models.prompts import get_prompt
from janus.models.prompts.codegen import SELF_REVIEW
from janus.models.router import Budget
from janus.models.tiers import Tier
from janus.sandbox.runner import SandboxJob
from janus.store import audit
from janus.store.oss import archive

logger = logging.getLogger(__name__)

MAX_TOOL_ITERS = 25
PROTECTED = [".github/**", "**/*.lock", ".janus/**"]

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a file from the repo clone.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write full file contents (overwrites).",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run",
            "description": "Run a shell command in the repo (tests, linters).",
            "parameters": {
                "type": "object",
                "properties": {"cmd": {"type": "string"}},
                "required": ["cmd"],
            },
        },
    },
]


async def run_codegen_job(
    gh: GitHubClient, repo: str, issue_number: int, plan: str, budget_tokens: int
) -> None:
    budget = Budget(budget_tokens)
    token = await installation_token(gh.installation_id)
    base = await gh.get_default_branch(repo)
    branch = f"janus/issue-{issue_number}"

    async with SandboxJob(repo, token, base) as sandbox:
        outcome = await _agent_loop(sandbox, budget, plan)
        await _self_review(sandbox, budget)
        changed = await sandbox.changed_paths()
        diff = await sandbox.diff()
        artifact_key = await archive().put_artifact(sandbox.job_id, "diff.patch", diff.encode())

        blocked_reason = None
        if outcome.startswith("BLOCKED"):
            blocked_reason = outcome
        elif not changed:
            blocked_reason = "BLOCKED codegen produced no changes"
        elif any(matches_any(p, PROTECTED) for p in changed):
            blocked_reason = f"BLOCKED touched protected paths: {changed}"

        if blocked_reason:
            await _escalate_blocked(gh, repo, issue_number, blocked_reason, diff, artifact_key)
            return

        summary = outcome.removeprefix("DONE").strip() or f"fix #{issue_number}"
        if not await sandbox.push_branch(branch, f"{summary}\n\nCloses #{issue_number}"):
            await _escalate_blocked(
                gh, repo, issue_number, "BLOCKED git push failed", diff, artifact_key
            )
            return

    pr = await gh.create_pr(
        repo,
        head=branch,
        base=base,
        title=summary[:80],
        body=(
            f"Autonomous implementation of #{issue_number}.\n\n## Plan\n{plan}\n\n"
            f"Closes #{issue_number}\n\n— Janus 🤖"
        ),
    )
    await audit.record(
        repo,
        Capability.WRITE_PR,
        "auto",
        f"opened PR #{pr['number']} for issue #{issue_number}",
        {"branch": branch, "changed": changed, "oss_artifact": artifact_key},
    )
    from janus.telegram import bot

    await bot.notify(f"[{repo}] opened PR #{pr['number']} for issue #{issue_number}")


async def _agent_loop(sandbox: SandboxJob, budget: Budget, plan: str) -> str:
    messages: list[dict] = [
        {"role": "system", "content": get_prompt(Capability.WRITE_PR, Tier.CODER)},
        {"role": "user", "content": f"## Plan\n{plan}"},
    ]
    for _ in range(MAX_TOOL_ITERS):
        response = await budget.complete(Tier.CODER, messages, tools=TOOLS)
        message = response.choices[0].message
        if not message.tool_calls:
            return (message.content or "").strip()
        messages.append(message.model_dump(exclude_none=True))
        for call in message.tool_calls:
            args = json.loads(call.function.arguments)
            result = await _dispatch_tool(sandbox, call.function.name, args)
            messages.append(
                {"role": "tool", "tool_call_id": call.id, "content": result[:20_000]}
            )
    return "BLOCKED hit tool iteration cap"


async def _dispatch_tool(sandbox: SandboxJob, name: str, args: dict) -> str:
    if name == "read_file":
        return await sandbox.read_file(args["path"])
    if name == "write_file":
        if matches_any(args["path"], PROTECTED):
            return "(refused: protected path)"
        return await sandbox.write_file(args["path"], args["content"])
    if name == "run":
        code, out = await sandbox.run(f"sh -c {json.dumps(args['cmd'])}")
        return f"exit={code}\n{out}"
    return f"(unknown tool {name})"


async def _self_review(sandbox: SandboxJob, budget: Budget) -> None:
    from janus.config.policy import BudgetConfig

    max_iters = BudgetConfig().self_review_max_iters
    for _ in range(max_iters):
        diff = await sandbox.diff()
        if not diff.strip():
            return
        review = await budget.complete_json(
            Tier.CODER,
            [{"role": "user", "content": f"{SELF_REVIEW}\n\n## Diff\n{diff[:40_000]}"}],
        )
        if review.get("ok", True):
            return
        issues = "\n".join(review.get("issues", []))
        await _agent_loop(sandbox, budget, f"Fix these review findings, nothing else:\n{issues}")


async def _escalate_blocked(
    gh: GitHubClient, repo: str, issue_number: int, reason: str, diff: str, artifact_key: str
) -> None:
    from janus.store import repo as store
    from janus.telegram import bot

    approval = await store.create_approval(
        repo,
        Capability.WRITE_PR,
        {"number": issue_number, "blocked": reason, "oss_artifact": artifact_key},
        f"codegen blocked on #{issue_number}: {reason}",
    )
    await bot.send_approval(
        approval, f"codegen blocked on #{issue_number}: {reason}", [reason]
    )
    await audit.record(
        repo,
        Capability.WRITE_PR,
        "ask",
        f"codegen blocked on #{issue_number}",
        {"reason": reason, "oss_artifact": artifact_key, "diff_head": diff[:2000]},
    )
