# Jason OS — Knowledge Brain

**Entry point for engineering and handover.** This repository is one domain component of Jason OS, not the entire Jarvis / AI OS.

**Current development status:** [docs/CURRENT_STATE.md](docs/CURRENT_STATE.md) — dated, evidence-scoped snapshot. Recheck GitHub refs and actual VPS state before development.

## Read in this order (progressive context loading)

1. [CURRENT_STATE](docs/CURRENT_STATE.md) — active goal, exact baseline, open PRs, blockers and next action.
2. The **specific Issue / PR** for the assigned task; consult only relevant code and tests.
3. [DEVELOPMENT_GOVERNANCE](docs/DEVELOPMENT_GOVERNANCE.md) — handover, safety, status labels and acceptance workflow.
4. [HEALTH_AUDIT_2026-11-01](docs/DEVELOPMENT_HEALTH_AUDIT_2026-11-01.md) — dated findings; not a continuously updated runtime report.
5. [Existing target architecture](docs/knowledge_system_target_architecture_v1.md) and [capability audit baseline](docs/knowledge_capability_status_v1.md) for necessary technical context.

**Authoritative product priority:** [Google Drive Beta-First Product Contract](https://docs.google.com/document/d/1dfIGsY_VDwXS_B-DSlNtAB8SkOsvGkx5b-owgqSgQMQ/edit). It supersedes older *priority proposals* but not existing implementation evidence or safety boundaries.

## Source of truth

- GitHub: code, tests, releases, PRs and Issues.
- Google Drive: approved architecture/product decisions and canonical source documents.
- VPS Staging / Production: **operational truth only when directly verified** with redacted evidence.
- Anki: review/scheduling history; never infer production deck state from export code.

A code file, successful CI or issue checkbox is not proof of a usable Beta or a deployed Production system. **No cleanup, merge, deployment or Production write is authorized by this README.**
