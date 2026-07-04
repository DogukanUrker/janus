from __future__ import annotations

import uuid
from datetime import UTC, datetime

from janus.github.client import GitHubClient

HISTORY_PATH = ".janus/HISTORY.md"
MEMORY_PATH = ".janus/MEMORY.md"


async def append_history(gh: GitHubClient, repo: str, line: str) -> None:
    branch = await gh.get_default_branch(repo)
    existing = await gh.get_file(repo, HISTORY_PATH, ref=branch) or "# Janus action history\n"
    stamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M")
    await gh.commit_file(
        repo, branch, HISTORY_PATH, f"{existing.rstrip()}\n- {stamp} {line}\n",
        f"janus: log action ({stamp})",
    )


async def propose_memory(gh: GitHubClient, repo: str, learning: str) -> None:
    base = await gh.get_default_branch(repo)
    sha = await gh.get_branch_sha(repo, base)
    branch = f"janus/memory-{uuid.uuid4().hex[:8]}"
    await gh.create_branch(repo, branch, sha)

    existing = await gh.get_file(repo, MEMORY_PATH, ref=base) or "# Janus memory\n"
    await gh.commit_file(
        repo, branch, MEMORY_PATH, f"{existing.rstrip()}\n- {learning}\n", "janus: propose memory"
    )
    await gh.create_pr(
        repo,
        head=branch,
        base=base,
        title="janus: memory update (review before merge)",
        body=(
            "Janus wants to add the following to its standing memory:\n\n"
            f"> {learning}\n\n"
            "Memory writes always go through a PR so the model can never silently "
            "rewrite its own long-term policy.\n\n— Janus 🤖"
        ),
    )
