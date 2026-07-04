from __future__ import annotations

import logging

from janus.capabilities.base import Context
from janus.capabilities.merge import evaluate_merge
from janus.capabilities.review import run_review
from janus.capabilities.triage import run_triage
from janus.config.policy import Policy
from janus.github.client import GitHubClient
from janus.models.router import Budget
from janus.settings import settings
from janus.store.schema import WebhookEvent

logger = logging.getLogger(__name__)

BOT_LOGIN_SUFFIX = "[bot]"


async def handle(event: WebhookEvent, policy: Policy, agents_md: str, gh: GitHubClient) -> None:
    ctx = Context(
        gh=gh,
        repo=event.repo_full_name,
        policy=policy,
        agents_md=agents_md,
        budget=Budget(policy.budget.max_tokens_per_event),
        payload=event.payload,
    )

    if event.event_type == "issues" and event.action == "opened":
        await run_triage(ctx)

    elif event.event_type == "pull_request" and event.action in (
        "opened",
        "synchronize",
        "ready_for_review",
    ):
        author = event.payload["pull_request"]["user"]["login"]
        if author == f"{settings.github_app_slug}{BOT_LOGIN_SUFFIX}":
            await evaluate_merge(ctx, event.payload["pull_request"]["number"])
        else:
            await run_review(ctx)

    elif event.event_type == "check_suite" and event.action == "completed":
        for pr in event.payload["check_suite"].get("pull_requests", []):
            await evaluate_merge(ctx, pr["number"])

    else:
        logger.info(
            "unhandled event %s/%s on %s", event.event_type, event.action, event.repo_full_name
        )
