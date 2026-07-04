from __future__ import annotations

import base64
import logging

from janus.capabilities.base import Context
from janus.models.prompts.vision import VISION
from janus.models.tiers import Tier

logger = logging.getLogger(__name__)

MAX_IMAGES = 2


async def analyze_images(ctx: Context, urls: list[str], issue_text: str) -> str:
    content: list[dict] = [{"type": "text", "text": f"{VISION}\n\nIssue:\n{issue_text}"}]
    for url in urls[:MAX_IMAGES]:
        try:
            data = await ctx.gh.download_attachment(url)
        except Exception:
            logger.warning("failed to fetch attachment %s", url)
            continue
        encoded = base64.b64encode(data).decode()
        content.append(
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{encoded}"}}
        )
    if len(content) == 1:
        return ""
    response = await ctx.budget.complete(Tier.VL, [{"role": "user", "content": content}])
    return response.choices[0].message.content or ""
