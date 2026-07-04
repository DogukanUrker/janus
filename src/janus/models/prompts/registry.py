from __future__ import annotations

from collections.abc import Callable

from janus.autonomy.levels import Capability
from janus.models.tiers import Tier

_REGISTRY: dict[tuple[Capability, Tier], str] = {}


def register(capability: Capability, tier: Tier) -> Callable[[str], str]:
    def _inner(prompt: str) -> str:
        _REGISTRY[(capability, tier)] = prompt
        return prompt

    return _inner


def get_prompt(capability: Capability, tier: Tier) -> str:
    try:
        return _REGISTRY[(capability, tier)]
    except KeyError:
        raise KeyError(
            f"no prompt registered for ({capability}, {tier}); "
            f"available: {sorted((str(c), str(t)) for c, t in _REGISTRY)}"
        ) from None
