from __future__ import annotations

import re
from dataclasses import dataclass

from pydantic import BaseModel, Field

CLASS_PATTERNS: dict[str, list[str]] = {
    "readme": ["README*", "**/README*"],
    "docs": ["docs/**", "*.md", "**/*.md"],
    "tokens": ["**/tokens.*", "static/css/tokens.*"],
    "deps": ["requirements*.txt", "pyproject.toml", "package.json"],
}


class AutoMergeConfig(BaseModel):
    enabled: bool = False
    allowlist_paths: list[str] = Field(default_factory=list)
    max_diff_lines: int = 30
    max_files: int = 3
    require_ci_green: bool = True
    protected_paths: list[str] = Field(
        default_factory=lambda: [".github/**", "**/*.lock", "SECURITY.md", ".janus/**"]
    )


@dataclass
class DiffSummary:
    paths: list[str]
    additions: int
    deletions: int
    files: int


def _glob_to_regex(pattern: str) -> re.Pattern[str]:
    out = []
    i = 0
    while i < len(pattern):
        c = pattern[i]
        if c == "*":
            if pattern[i : i + 3] == "**/":
                out.append("(?:.*/)?")
                i += 3
                continue
            if pattern[i : i + 2] == "**":
                out.append(".*")
                i += 2
                continue
            out.append("[^/]*")
        elif c == "?":
            out.append("[^/]")
        else:
            out.append(re.escape(c))
        i += 1
    return re.compile("^" + "".join(out) + "$")


def matches_any(path: str, patterns: list[str]) -> bool:
    return any(_glob_to_regex(p).match(path) for p in patterns)


def derive_change_class(paths: list[str], cfg: AutoMergeConfig) -> str | None:
    if not paths:
        return None
    for cls, patterns in CLASS_PATTERNS.items():
        if all(matches_any(p, patterns) for p in paths):
            return cls
    return None


def auto_merge_allowed(
    diff: DiffSummary, ci_green: bool, cfg: AutoMergeConfig
) -> tuple[bool, list[str]]:
    failures: list[str] = []

    if not cfg.enabled:
        failures.append("auto_merge disabled")
    if not diff.paths:
        failures.append("empty diff")
    for p in diff.paths:
        if matches_any(p, cfg.protected_paths):
            failures.append(f"protected path: {p}")
        if cfg.allowlist_paths and not matches_any(p, cfg.allowlist_paths):
            failures.append(f"path not in allowlist: {p}")
    if not cfg.allowlist_paths:
        failures.append("no allowlist configured")
    if diff.additions + diff.deletions > cfg.max_diff_lines:
        failures.append(f"diff too large: {diff.additions + diff.deletions} > {cfg.max_diff_lines}")
    if diff.files > cfg.max_files:
        failures.append(f"too many files: {diff.files} > {cfg.max_files}")
    if cfg.require_ci_green and not ci_green:
        failures.append("ci not green")
    if derive_change_class(diff.paths, cfg) is None:
        failures.append("change class not derivable from paths")

    return (not failures, failures)
