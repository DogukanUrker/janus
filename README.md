# Janus

**An autonomous GitHub maintainer that asks you one question a day.**

Janus is a GitHub App that runs the full repository maintenance lifecycle on its own: it triages incoming issues, closes spam and duplicates with a reasoned comment, nudges vague reports for details, reviews community PRs, plans fixes, writes the code in a sandbox, opens PRs — and escalates to you, on Telegram, only when an action crosses a reversibility line.

Built for the [Qwen Cloud Global AI Hackathon](https://qwen-cloud-hackathon.devpost.com/) (Track 4: Autopilot Agent), powered by Qwen models via Qwen Cloud and deployed on Alibaba Cloud ECS with OSS as the audit archive.

## The trust model

Most "autonomous" agents are either fully autonomous (terrifying) or ask about everything (useless). Janus does neither:

1. **Reversibility-gated escalation.** Every capability has an autonomy level (`auto` / `ask` / `suggest` / `off`). Cheap-to-undo actions (labeling, closing spam with a reopen path) run autonomously. Socially expensive or irreversible actions (merging non-trivial code, closing a human's PR) require one tap on Telegram.
2. **Demotion, never self-confidence.** When the model flags uncertainty or a deterministic gate fails, the action drops exactly one autonomy level. The LLM never argues its way *up* to more autonomy.
3. **Mechanical merge gates.** Auto-merge eligibility is computed from file paths, diff size, and CI status — never from the model's opinion of its own code. The change class is derived from paths with plain glob rules (`src/janus/autonomy/gates.py`); if it can't be derived, the merge escalates.
4. **Memory as an attack surface.** Janus's standing memory (`.janus/MEMORY.md`) can only change via a pull request it opens against itself. The model cannot silently rewrite its own long-term policy — issue authors trying prompt injection end up proposing a publicly reviewable diff.

## Architecture

```
GitHub webhooks ──> FastAPI ingress ──> Postgres queue ──> worker
                                                            │
                              ┌─────────────────────────────┤
                              ▼                             ▼
                     Qwen Cloud (DashScope)          Docker sandbox
                     qwen3.6-plus   triage/review    (clone, codegen,
                     qwen3.7-max    planning          tests, push)
                     qwen3-coder-plus codegen
                     qwen3-vl-plus  screenshots
                              │
                              ▼
              Telegram approvals ── Alibaba OSS audit archive
```

Runs as a single container next to Postgres and Caddy on an Alibaba Cloud ECS instance (`deploy/`). Every action is archived to Alibaba OSS (`src/janus/store/oss.py`); Telegram approval cards link to presigned OSS payloads.

## Per-repo configuration

Drop two files in any repo where Janus is installed:

- **`AGENTS.md`** — what the project is, its scope, its conventions. Fed to every model call.
- **`.janus/policy.yml`** — autonomy profile and overrides:

```yaml
profile: autopilot        # autopilot | cautious | self-host
vision: true              # analyze issue screenshots with qwen3-vl
capabilities:
  merge_pr: ask           # override any single capability
auto_merge:
  enabled: true
  allowlist_paths: ["README*", "docs/**", "**/*.md"]
  max_diff_lines: 30
```

No policy file → full-autonomy `autopilot` defaults. Malformed policy file → `cautious`.

## Running it

```bash
cp .env.example .env       # fill in GitHub App, Telegram, DashScope, OSS creds
docker compose up -d       # local postgres
uv run uvicorn janus.main:app --reload
```

Tests and lint:

```bash
uv run pytest
uv run ruff check src tests
```

Production deployment on Alibaba Cloud ECS: see [`deploy/README.md`](deploy/README.md).

## Repo layout

```
src/janus/
  autonomy/     levels, resolution engine, deterministic merge gates
  config/       profiles + .janus/policy.yml parsing
  ingest/       webhook verification + queue ingress
  queue/        event / approvals / reminder loops
  orchestrator/ event -> capability dispatch
  capabilities/ triage, review, plan, codegen, merge, vision
  models/       Qwen tier routing, token budgets, prompt registry
  sandbox/      hardened Docker clone for codegen
  telegram/     approval cards, digest notifications
  store/        Postgres schema + Alibaba OSS audit archive
  memory/       HISTORY.md appends, MEMORY.md via PR
```

## License

Apache-2.0
