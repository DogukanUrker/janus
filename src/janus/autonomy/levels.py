from enum import StrEnum


class AutonomyLevel(StrEnum):
    OFF = "off"
    SUGGEST = "suggest"
    ASK = "ask"
    AUTO = "auto"


class Capability(StrEnum):
    LABEL = "label"
    VAGUE_NUDGE = "vague_nudge"
    CLOSE_ISSUE = "close_issue"
    REVIEW_PR = "review_pr"
    CLOSE_HUMAN_PR = "close_human_pr"
    PLAN_ISSUE = "plan_issue"
    WRITE_PR = "write_pr"
    MERGE_PR = "merge_pr"
    MEMORY_WRITE = "memory_write"
