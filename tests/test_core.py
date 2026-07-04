import pytest

from janus.autonomy.engine import Signals, resolve
from janus.autonomy.gates import (
    AutoMergeConfig,
    DiffSummary,
    auto_merge_allowed,
    derive_change_class,
    matches_any,
)
from janus.autonomy.levels import AutonomyLevel as L
from janus.autonomy.levels import Capability as C
from janus.config.policy import Policy, load_policy


def policy(**caps):
    return Policy(profile="autopilot", capabilities=caps)


class TestEngine:
    def test_clean_signals_keep_policy_level(self):
        r = resolve(C.WRITE_PR, policy())
        assert r.level is L.AUTO and not r.demoted

    def test_uncertainty_demotes_one_level(self):
        r = resolve(C.WRITE_PR, policy(), signals=Signals(uncertainty=True))
        assert r.level is L.ASK and r.demoted

    def test_gate_failure_demotes_ask_to_suggest(self):
        r = resolve(C.MERGE_PR, policy(), signals=Signals(gate_failures=["ci not green"]))
        assert r.level is L.SUGGEST
        assert any("ci not green" in reason for reason in r.reasons)

    def test_suggest_floor(self):
        r = resolve(C.LABEL, policy(label=L.SUGGEST), signals=Signals(uncertainty=True))
        assert r.level is L.SUGGEST

    def test_off_never_moves(self):
        r = resolve(C.MERGE_PR, policy(merge_pr=L.OFF), signals=Signals(uncertainty=True))
        assert r.level is L.OFF and not r.demoted

    def test_never_promotes(self):
        r = resolve(C.MERGE_PR, policy())
        assert r.level is L.ASK


class TestGlobs:
    @pytest.mark.parametrize(
        ("path", "pattern", "expected"),
        [
            ("README.md", "README*", True),
            ("docs/guide/x.md", "docs/**", True),
            ("src/deep/nested/a.md", "**/*.md", True),
            ("a.md", "**/*.md", True),
            (".github/workflows/ci.yml", ".github/**", True),
            ("src/main.py", "*.md", False),
            ("docs.py", "docs/**", False),
        ],
    )
    def test_matching(self, path, pattern, expected):
        assert matches_any(path, [pattern]) is expected


class TestChangeClass:
    cfg = AutoMergeConfig()

    def test_pure_readme(self):
        assert derive_change_class(["README.md"], self.cfg) == "readme"

    def test_mixed_paths_none(self):
        assert derive_change_class(["README.md", "src/app.py"], self.cfg) is None

    def test_empty_none(self):
        assert derive_change_class([], self.cfg) is None

    def test_docs(self):
        assert derive_change_class(["docs/a.md", "guide.md"], self.cfg) == "docs"


class TestAutoMerge:
    def cfg(self, **kw):
        base = dict(
            enabled=True,
            allowlist_paths=["README*", "docs/**", "**/*.md"],
            max_diff_lines=30,
            max_files=3,
            require_ci_green=True,
        )
        base.update(kw)
        return AutoMergeConfig(**base)

    def diff(self, paths=("README.md",), additions=5, deletions=2):
        return DiffSummary(
            paths=list(paths), additions=additions, deletions=deletions, files=len(paths)
        )

    def test_happy_path(self):
        ok, failures = auto_merge_allowed(self.diff(), True, self.cfg())
        assert ok and failures == []

    def test_disabled(self):
        ok, failures = auto_merge_allowed(self.diff(), True, self.cfg(enabled=False))
        assert not ok and "auto_merge disabled" in failures

    def test_ci_red(self):
        ok, failures = auto_merge_allowed(self.diff(), False, self.cfg())
        assert not ok and "ci not green" in failures

    def test_protected_path(self):
        ok, failures = auto_merge_allowed(
            self.diff(paths=[".github/workflows/ci.yml"]), True, self.cfg()
        )
        assert not ok and any("protected path" in f for f in failures)

    def test_too_large(self):
        ok, failures = auto_merge_allowed(self.diff(additions=40), True, self.cfg())
        assert not ok and any("diff too large" in f for f in failures)

    def test_too_many_files(self):
        ok, failures = auto_merge_allowed(
            self.diff(paths=["a.md", "b.md", "c.md", "d.md"]), True, self.cfg()
        )
        assert not ok and any("too many files" in f for f in failures)

    def test_outside_allowlist(self):
        ok, failures = auto_merge_allowed(self.diff(paths=["src/app.py"]), True, self.cfg())
        assert not ok

    def test_no_allowlist_configured(self):
        ok, failures = auto_merge_allowed(self.diff(), True, self.cfg(allowlist_paths=[]))
        assert not ok and "no allowlist configured" in failures


class TestPolicy:
    def test_missing_file_is_autopilot(self):
        p = load_policy(None)
        assert p.profile == "autopilot"
        assert p.level_for(C.WRITE_PR) is L.AUTO
        assert p.level_for(C.MERGE_PR) is L.ASK

    def test_profile_preset_applies(self):
        p = load_policy("profile: cautious")
        assert p.level_for(C.WRITE_PR) is L.ASK

    def test_explicit_capability_overrides_preset(self):
        p = load_policy("profile: autopilot\ncapabilities:\n  write_pr: ask")
        assert p.level_for(C.WRITE_PR) is L.ASK
        assert p.level_for(C.CLOSE_ISSUE) is L.AUTO

    def test_malformed_yaml_falls_back_cautious(self):
        p = load_policy("profile: [unclosed")
        assert p.profile == "cautious"

    def test_unknown_keys_ignored(self):
        p = load_policy("profile: autopilot\nfrobnicate: true")
        assert p.profile == "autopilot"

    def test_unknown_profile_uses_cautious_levels(self):
        p = load_policy("profile: yolo")
        assert p.level_for(C.WRITE_PR) is L.ASK

    def test_budget_defaults(self):
        p = load_policy("profile: autopilot")
        assert p.budget.max_tokens_per_event == 60_000


class TestRegistry:
    def test_all_core_prompts_registered(self):
        from janus.models.prompts import get_prompt
        from janus.models.tiers import Tier

        for cap, tier in [
            (C.CLOSE_ISSUE, Tier.MID),
            (C.VAGUE_NUDGE, Tier.MID),
            (C.LABEL, Tier.MID),
            (C.REVIEW_PR, Tier.MID),
            (C.PLAN_ISSUE, Tier.MAX),
            (C.WRITE_PR, Tier.CODER),
        ]:
            assert get_prompt(cap, tier)

    def test_missing_prompt_raises_helpfully(self):
        from janus.models.prompts import get_prompt
        from janus.models.tiers import Tier

        with pytest.raises(KeyError, match="no prompt registered"):
            get_prompt(C.MEMORY_WRITE, Tier.VL)
