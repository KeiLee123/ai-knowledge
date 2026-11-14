# KB-03 Private Feedback Review Loop — MVP v0.1

**Scope:** `staging` only; no browser/admin endpoint, no model/provider, no new database, no automatic GitHub issue creation, no changes to Frozen Retrieval, Production, timers, Drive originals, or personal Anki.

## Data ownership and architecture

- The existing local `feedback.jsonl` remains **append-only original evidence** written by the token-authenticated Private Beta. The review tool never edits it.
- Manual review decisions append to **`feedback-reviews.jsonl`** in the same private staging directory. Each event references a **1-based file row number** and the SHA-256 fingerprint of that exact row. If an earlier source row was altered, the tool fails closed instead of silently attaching a decision to a different item.
- Private state directory remains owner-only `0700`; both JSONL files are regular, owner-only `0600`; symlinks and malformed records are rejected. The review event file stores status, priority, UTC timestamp and a **numeric GitHub issue reference**, not feedback text or request IDs. All output stays in the operator's local terminal. Do not paste `show` output or queue JSONL into a public issue.
- No network/API calls: the issue number is a **manual reference**, not a claim that GitHub has been queried or that a fix has shipped. Original feedback content is only shown through an explicit `show --item` operation.

## MVP commands (operator-only in isolated Staging)

Use `/opt/ai-knowledge-staging/.venv/bin/python -B` and the staging checkout after the exact-commit regression gate, never Production. Commands below are documentation of intended use, **not authorization to execute or mutate the live VPS**.

```bash
python -B beta_feedback_review_staging_v1.py summary
python -B beta_feedback_review_staging_v1.py list
python -B beta_feedback_review_staging_v1.py show --item 2
# Dry-run: prints the proposed status change without writing
python -B beta_feedback_review_staging_v1.py set --item 2 --state TRIAGED --priority MEDIUM --issue 60
# Only after explicit review/approval: append one private audit event
python -B beta_feedback_review_staging_v1.py set --item 2 --state TRIAGED --priority MEDIUM --issue 60 --apply
python -B beta_feedback_review_staging_v1.py set --item 2 --state IN_PROGRESS --priority HIGH --issue 60 --apply
python -B beta_feedback_review_staging_v1.py set --item 2 --state RESOLVED --priority HIGH --issue 60 --apply
```

`summary` and `list` **never print comments or request IDs**. `show` prints one raw private comment to the local operator terminal by explicit action, so avoid recording terminal output or pasting it into external systems. `set` defaults to **no write**; `--apply` appends a new event. Supported states: `NEW → TRIAGED → IN_PROGRESS → RESOLVED` (or `WONT_FIX` after triage), with permitted direct `TRIAGED → RESOLVED`; terminal states are immutable in v0.1. `IN_PROGRESS` and `RESOLVED` require an issue number. Priority is `LOW`, `MEDIUM`, or `HIGH`.

## Acceptance and rollback

1. Run `test_beta_feedback_review_staging_v1.py` with **synthetic-only** private files, including permission and symlink refusal, status transitions, source-row tampering, dry-run, no-leak defaults, issue gates, and immutability of original feedback JSONL.
2. Require exact-head GitHub CI on an isolated feature branch, then operator **read-only VPS preflight**; do not touch Production/Frozen, add network listeners or grant public review access.
3. For real operator acceptance, first run **only** `summary`/`list` and verify two existing records appear with status `NEW` without printing private comments. Owner must explicitly authorize any `--apply` operation on the real feedback queue.
4. Rollback is simply not running the CLI. For already-applied review actions, the original feedback queue is intact; a separate, owner-approved governance decision is required before editing/removing a review log. This MVP intentionally does **not** allow event deletion, status mutation in-place, or silent reopening.

**Not yet delivered by this MVP:** automatic GitHub issue creation/verification, issue status synchronization, reviewer roles/web UI, actual human resolution verification, production deployment, or complete KB-03 Beta Gate 2 approval.
