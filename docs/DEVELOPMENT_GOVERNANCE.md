# Development Governance — Knowledge Brain

**Purpose:** Preserve continuity between ChatGPT web, Codex, GitHub and human operation **without spending tokens rereading the entire repository**. This is a workflow, not a new agent/orchestration system.

## Authoritative places

1. **GitHub**: code and tests (`main` frozen/production code baseline, `staging` working code), Issues for backlog, PRs for change and test evidence.
2. **Google Drive**: approved product/architecture decisions and canonical source PDF/XML versions. [Beta-First Product Contract](https://docs.google.com/document/d/1dfIGsY_VDwXS_B-DSlNtAB8SkOsvGkx5b-owgqSgQMQ/edit).
3. **Actual VPS**: observed operational truth only after an authorized read-only check (SHA, service, runtime, health, timestamp).
4. **Anki**: actual personal deck and scheduling state; do not infer from code or staging packages.
5. **`CURRENT_STATE.md`**: short **dated derived index**, not a replacement for the above. Never copy large specs or secrets into it.

## Shared M1 / M2 / M3 entrypoint

Retrieve the [Google Drive Master Index](https://docs.google.com/document/d/1QDcl287N5zFqeYEpukN10cd-2qv7lJEdNcT4rJ0lpTI/edit) and [Knowledge Brain Current State](https://docs.google.com/document/d/1ETsFRfbE2HsRG2yb78EKDfRm2VzveyLNkLS-cr1g6Nk/edit) before coding. Use the [M2 Preflight/Handoff SOP](https://docs.google.com/document/d/1_WZ2rtpQOEsQFAWq1zjgoSxAgf6qyRrbhKlmqJlql5U/edit). The [M3 consistency audit](https://docs.google.com/document/d/1Kq28KgAtzR9zcn5iYA8VoznxyrW3PsfDN0LrlSUKqAg/edit) is a dated, on-demand example, not an automatic synchronization service. Reconcile this repository's dated state with live GitHub PR, exact CI SHA and runtime evidence before asserting acceptance.

The Google Drive decision log remains authoritative for cross-system product and architecture decisions; GitHub remains authoritative for code and tests. If sources conflict, label the discrepancy for review rather than silently overwriting decisions. No present-day VPS checks are implied by these governance documents.

## Progressive context loading

- **L0**: first read the linked Google Drive M1 Index, system Current State and M2 SOP; then read root `AGENTS.md` and `CURRENT_STATE.md` as repository navigation snapshots.
- **L1**: target Issue, PR, approved decision link and *only* relevant module README/contract.
- **L2**: exact code, tests, CI logs, deployment evidence when needed.
- No whole-repo scan by default. If status is stale, refresh from actual GitHub and/or the authorized environment, reporting exact source/date/commit.
- Context budgets are goals, not hard limits; don't skip evidence to meet an arbitrary token quota.

## Workflow and work-in-progress

1. **Triage before coding**: check duplicate work, existing modules and exact owning workstream. One active feature per repo + at most one separate urgent security fix by default.
2. **Task contract**: Issue states purpose, user-visible acceptance, non-goals, dependencies, risks and evidence to collect. Do not open serial micro-milestones just to count green CI.
3. **Code on feature branch**: do not alter `main` or existing frozen layers without a reviewed compatibility and regression plan. Draft PRs remain draft until gates pass.
4. **Verify**: exact head SHA + CI tests, then real bounded Staging test/acceptance, then separate user/Production gates when relevant. Capture data provenance and fail-closed cases.
5. **Handover**: close each session with changed SHA/files, tests attempted and results, what is *not* verified, blocked risks, link to the actual Issue/PR and one next concrete action.
6. **Update index** only on material changes: branch tip, active priority, merged/closed issue, acceptance level or blocker. Keep older audits immutable as dated history. Never silently overwrite approved Drive decisions.
7. **Review releases**: no automatic `staging→main`, no Production writes, no personal Anki imports, no provider/model egress, no VPS deployment absent explicit separate authorization.

## Completion status semantics

| Status | Minimum evidence |
| --- | --- |
| `DESIGNED` | Approved design/acceptance recorded, implementation not asserted |
| `CODED` | Exact Git SHA and files exist |
| `CI_PASS` | Linked CI run on exact head SHA; records what tests covered |
| `STAGING_ACCEPTED` | Actual Staging runtime/test with timestamp, pinned SHA, inputs, observed outputs, safety evidence |
| `USER_BETA` | Real private user journey, measured usefulness/feedback and product-level gates passed |
| `PRODUCTION_VERIFIED` | Explicit approved release, deployed SHA and operational post-change check |

Never infer next status from previous one. A source checksum match/embedding result cannot prove correct professional reasoning, and automated checks cannot be labelled human-verified Gold.

## Every coding-session handover template

```md
Task / Issue: #...
Repository / target branch:
Snapshot timestamp / exact base SHA / head SHA:
Goal & acceptance criteria:
Files changed (or NONE):
Tests run / exact CI URL / result:
Staging test: PASS / FAIL / NOT RUN (proof link):
Production and personal-data changes: NONE / explicitly approved:
What remains unverified (do not omit):
Decision conflicts / blockers:
Next smallest action:
Docs / CURRENT_STATE update needed? yes/no + reason:
```

**Snapshot discipline:** The index must explicitly say `GitHub-only` versus `VPS-verified`. When an agent cannot access VPS, it must write `NOT VERIFIED` rather than inferring success.

## Controlled consolidation policy

- Preserve old branches, tests and historical documents until their last use, dependencies and safety coverage are recorded.
- Identify redundant CI workflows by trigger/runtime/coverage; only consolidate with replacement checks and observed validation parity. Do not delete tests to make the repo appear cleaner.
- Reject a new dashboard/database/job framework unless current tools demonstrably cannot support the required user outcome. Shared cross-domain task/approval infrastructure belongs to Jarvis Core, not a second system built here.
