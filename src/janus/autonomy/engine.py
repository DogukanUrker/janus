from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from janus.autonomy.levels import AutonomyLevel, Capability

if TYPE_CHECKING:
    from janus.config.policy import Policy

_DEMOTION = {
    AutonomyLevel.AUTO: AutonomyLevel.ASK,
    AutonomyLevel.ASK: AutonomyLevel.SUGGEST,
    AutonomyLevel.SUGGEST: AutonomyLevel.SUGGEST,
    AutonomyLevel.OFF: AutonomyLevel.OFF,
}


@dataclass
class Signals:
    uncertainty: bool = False
    gate_failures: list[str] = field(default_factory=list)

    @property
    def any(self) -> bool:
        return self.uncertainty or bool(self.gate_failures)


@dataclass
class Resolution:
    level: AutonomyLevel
    demoted: bool
    reasons: list[str]


def resolve(
    capability: Capability, policy: Policy, *, signals: Signals | None = None
) -> Resolution:
    level = policy.level_for(capability)
    reasons = [f"policy[{capability}] = {level}"]

    if signals is None or not signals.any or level is AutonomyLevel.OFF:
        return Resolution(level=level, demoted=False, reasons=reasons)

    demoted = _DEMOTION[level]
    if signals.uncertainty:
        reasons.append(f"demoted {level}->{demoted}: model flagged uncertainty")
    if signals.gate_failures:
        failed = ", ".join(signals.gate_failures)
        reasons.append(f"demoted {level}->{demoted}: gates failed [{failed}]")
    return Resolution(level=demoted, demoted=demoted is not level, reasons=reasons)
