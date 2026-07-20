# Deployment & Alibaba Cloud Evidence

Janus runs entirely on Alibaba Cloud infrastructure: the backend on **ECS**, all
model inference through **Qwen Cloud** (Model Studio / DashScope International),
and a full audit trail of every action in **OSS**. This document is the
submission's proof-of-deployment reference.

## Backend — Alibaba Cloud ECS

The GitHub App backend (webhook receiver, event queue, orchestrator, Telegram
approval bot) runs 24/7 on a single ECS instance.

| | |
| --- | --- |
| Instance ID | `i-t4n70jdizgoyml9558qu` |
| Region | Singapore (`ap-southeast-1`) |
| Spec | 2 vCPU · 4 GiB |
| Public IP | `47.236.152.214` |
| State | Running |

Deployed with Docker Compose (`deploy/docker-compose.prod.yml`), which runs the
Janus app, PostgreSQL (audit + approvals store), and Caddy (TLS termination for
the inbound GitHub webhook).

## Model inference — Qwen Cloud

All LLM calls go through the OpenAI-compatible endpoint
`https://dashscope-intl.aliyuncs.com/compatible-mode/v1`, routed by task tier:

| task | model |
| --- | --- |
| triage, labeling, PR review | `qwen3.6-plus` |
| implementation planning (thinking) | `qwen3.7-max` |
| codegen + self-review | `qwen3-coder-plus` |
| screenshot understanding | `qwen3-vl-plus` |

Usage is verifiable in the Qwen Cloud Analytics console (requests, token counts,
and per-model breakdown), which is the source of truth for the numbers cited in
the write-up.

## Audit trail — Alibaba Cloud OSS

Every action Janus takes is archived as a dated JSON object to the OSS bucket
`janus-github-bot` under `actions/`. Telegram approval cards link to presigned
OSS URLs so the full decision context is inspectable from a phone.

The OSS integration is in [`src/janus/store/oss.py`](../src/janus/store/oss.py) —
this is the code-file link for the Devpost submission.

## Live evidence (real, unseeded)

Recent autonomous activity on public repos, verifiable on GitHub:

- **Triaged & labeled** issues on `DogukanUrker/Tamga` (#33, #34, #35, #38) and
  auto-closed junk with reasoned comments (#34 spam, #35 off-topic).
- **Posted full implementation plans** on actionable issues (#33, #38) naming
  exact files and a test plan.
- **Reviewed and approved community PRs** from an external contributor who
  implemented those plans — `DogukanUrker/Tamga#40` (NO_COLOR support, merged)
  and `#39` (readable repr). The contributor's own comment confirms
  *"Janus has approved it."*
- **Escalated** the one irreversible-ish action — closing a human's PR (#37) —
  to Telegram with `policy[close_human_pr] = ask`, instead of acting
  unilaterally.

## Screenshots

Evidence captures are in `docs/evidence/`:

- `ecs-instance.png` — ECS console, instance Running in Singapore
- `qwen-analytics.png` — Qwen Cloud Analytics, per-model usage
- `oss-bucket.png` — OSS bucket with dated action archives
- `telegram-escalation.png` — the `close_human_pr` approval card
