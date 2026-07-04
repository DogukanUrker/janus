from __future__ import annotations

import json
import logging
from functools import lru_cache
from typing import Any

from openai import AsyncOpenAI

from janus.models.tiers import Tier
from janus.settings import settings

logger = logging.getLogger(__name__)


class BudgetExceeded(Exception):
    pass


@lru_cache(maxsize=1)
def client() -> AsyncOpenAI:
    return AsyncOpenAI(base_url=settings.dashscope_base_url, api_key=settings.dashscope_api_key)


def model_for(tier: Tier) -> str:
    return {
        Tier.MID: settings.model_mid,
        Tier.MAX: settings.model_max,
        Tier.CODER: settings.model_coder,
        Tier.VL: settings.model_vl,
    }[tier]


class Budget:
    def __init__(self, max_tokens: int):
        self.max_tokens = max_tokens
        self.used = 0

    def _charge(self, total_tokens: int | None) -> None:
        self.used += total_tokens or 0
        if self.used > self.max_tokens:
            raise BudgetExceeded(f"event token budget exceeded: {self.used} > {self.max_tokens}")

    async def complete(self, tier: Tier, messages: list[dict[str, Any]], **kwargs: Any) -> Any:
        if self.used >= self.max_tokens:
            raise BudgetExceeded(f"event token budget exhausted before call: {self.used}")
        response = await client().chat.completions.create(
            model=model_for(tier), messages=messages, **kwargs
        )
        self._charge(response.usage.total_tokens if response.usage else None)
        return response

    async def complete_json(
        self, tier: Tier, messages: list[dict[str, Any]], **kwargs: Any
    ) -> dict[str, Any]:
        response = await self.complete(tier, messages, **kwargs)
        text = response.choices[0].message.content or ""
        try:
            return _parse_json(text)
        except ValueError:
            logger.warning("model returned invalid JSON, retrying once")
        retry = [*messages, {"role": "assistant", "content": text},
                 {"role": "user", "content": "Reply with valid JSON only. No prose, no fences."}]
        response = await self.complete(tier, retry, **kwargs)
        return _parse_json(response.choices[0].message.content or "")


def _parse_json(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ValueError(f"not valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError("expected a JSON object")
    return parsed
