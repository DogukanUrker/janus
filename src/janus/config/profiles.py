from janus.autonomy.levels import AutonomyLevel as L
from janus.autonomy.levels import Capability as C

AUTOPILOT: dict[C, L] = {
    C.LABEL: L.AUTO,
    C.VAGUE_NUDGE: L.AUTO,
    C.CLOSE_ISSUE: L.AUTO,
    C.REVIEW_PR: L.AUTO,
    C.CLOSE_HUMAN_PR: L.ASK,
    C.PLAN_ISSUE: L.AUTO,
    C.WRITE_PR: L.AUTO,
    C.MERGE_PR: L.ASK,
    C.MEMORY_WRITE: L.ASK,
}

CAUTIOUS: dict[C, L] = {
    **AUTOPILOT,
    C.CLOSE_ISSUE: L.ASK,
    C.PLAN_ISSUE: L.ASK,
    C.WRITE_PR: L.ASK,
    C.MERGE_PR: L.ASK,
}

SELF_HOST: dict[C, L] = {
    **AUTOPILOT,
    C.WRITE_PR: L.AUTO,
    C.MERGE_PR: L.OFF,
}

PROFILES: dict[str, dict[C, L]] = {
    "autopilot": AUTOPILOT,
    "cautious": CAUTIOUS,
    "self-host": SELF_HOST,
}
