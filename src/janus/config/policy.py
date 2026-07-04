from __future__ import annotations

import logging

import yaml
from pydantic import BaseModel, Field, ValidationError

from janus.autonomy.gates import AutoMergeConfig
from janus.autonomy.levels import AutonomyLevel, Capability
from janus.config.profiles import PROFILES

logger = logging.getLogger(__name__)

KNOWN_KEYS = {"profile", "telegram", "vision", "paused", "capabilities", "auto_merge", "budget"}


class TelegramConfig(BaseModel):
    chat_id: str | None = None


class BudgetConfig(BaseModel):
    max_tokens_per_event: int = 60_000
    self_review_max_iters: int = 3


class Policy(BaseModel):
    profile: str = "autopilot"
    telegram: TelegramConfig = Field(default_factory=TelegramConfig)
    vision: bool = False
    paused: bool = False
    capabilities: dict[Capability, AutonomyLevel] = Field(default_factory=dict)
    auto_merge: AutoMergeConfig = Field(default_factory=AutoMergeConfig)
    budget: BudgetConfig = Field(default_factory=BudgetConfig)

    def level_for(self, capability: Capability) -> AutonomyLevel:
        if capability in self.capabilities:
            return self.capabilities[capability]
        preset = PROFILES.get(self.profile, PROFILES["cautious"])
        return preset.get(capability, AutonomyLevel.ASK)


def load_policy(yaml_text: str | None) -> Policy:
    if yaml_text is None:
        return Policy(profile="autopilot")
    try:
        raw = yaml.safe_load(yaml_text) or {}
        if not isinstance(raw, dict):
            raise ValueError("policy root must be a mapping")
    except (yaml.YAMLError, ValueError) as exc:
        logger.warning("malformed .janus/policy.yml (%s); falling back to cautious profile", exc)
        return Policy(profile="cautious")

    unknown = set(raw) - KNOWN_KEYS
    if unknown:
        logger.warning("unknown keys in policy.yml ignored: %s", ", ".join(sorted(unknown)))
        raw = {k: v for k, v in raw.items() if k in KNOWN_KEYS}

    try:
        return Policy(**raw)
    except ValidationError as exc:
        logger.warning("invalid policy.yml (%s); falling back to cautious profile", exc)
        return Policy(profile="cautious")
