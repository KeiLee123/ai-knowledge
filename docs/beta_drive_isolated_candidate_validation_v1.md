# Beta Gate 1: existing Drive candidate → isolated validation

Engineering proposal for Issue #59, based on staging
`9667c26d229f2df5688dd5d63ee23da95aca2f7c`. **Not deployed, not real
changed-document accepted, not shared-DB ingestion or release approval.**

## User failure and reuse

An official changed PDF may be saved by the existing versioned Drive handoff,
but that operation does not connect its readback proof to the existing isolated
parse/retrieval evidence. Operators otherwise have to join unrelated outputs
manually and could mistake evidence for a different candidate or monitor run.

`beta_validate_drive_candidate_v1.py` adds one operator entry point. It reuses:

- `m10b1_isolated_candidate_v1.process(validate=False)` and M10A intake for a
  fresh trusted identity, source SHA, monitor and accepted-reference lock;
- `beta_stage_monitor_candidate_v1.load_source/plan_candidate` for the shipped
  versioned destination and frozen M9 evidence policy;
- M10B-1 `process(validate=True)` for its existing immutable candidate workspace;
- M10B-2A `run()` for candidate-only native-text chunks and lexical canary.

No new parser, source registry, index service, writer, scheduler or AI model.
The approved [Beta contract](https://docs.google.com/document/d/1dfIGsY_VDwXS_B-DSlNtAB8SkOsvGkx5b-owgqSgQMQ/edit),
[M10B isolation](https://docs.google.com/document/d/1aZBVFRR0IperUB18xMNkrLWxTZUCEJU9jh9OG07XXFg/edit)
and [candidate-only retrieval](https://docs.google.com/document/d/1eev9RtJm7L_71Q0VQFDTMphtfqzHGyXzjphZTVTzaRg/edit)
remain the decision sources. This is a bounded engineering adapter under those
constraints, not permission to promote a candidate into Current or the active DB.

## Modes and side effects

The CLI requires the clean `staging` checkout at `/opt/ai-knowledge-staging`.
It accepts only APP145/APP149 and canonical state/workspace/registry paths;
no caller-supplied remote, DB endpoint or fixture roots. Importable functions
support sibling synthetic fixture roots for offline tests only.

Default plan, **no network or workspace creation**:

```bash
.venv/bin/python -B beta_validate_drive_candidate_v1.py \
  --summary /var/lib/jason-os/source-monitor-staging/batches/<UTC_STAMP>/summary.json \
  --source BD_PNAP_APP149
```

Only after explicit operational approval, read an **already existing** versioned
Drive object into temporary scratch and compare PDF header, bytes and SHA with
the freshly checked M9 original:

```bash
# Same --summary and --source as above:
# add --verify-drive
```

Only after separate candidate-workspace write approval, continue into the
existing isolated parse and in-memory lexical validation:

```bash
# Same --summary and --source as above:
# add --verify-drive --validate --confirm-staging-candidate-write
```

These examples describe a future authorized operation, not an executed
deployment or write. A genuine candidate and an existing verified Drive copy
are prerequisites. Never manufacture real M9 logs/official changes or upload a
synthetic document to the actual Drive destination to obtain a green status.

The reader executes only `rclone copyto <fixed-remote-object> <temp-file>` with
30 MiB maximum size, bounded retries and a 60-second process timeout. It never
calls upload, remote mkdir, overwrite, delete or promotion APIs. A missing,
oversized, unreadable, non-PDF or mismatched object fails before parse writes.
Raw rclone stderr is not exposed. Temporary readback copies are removed.

## Binding, retry and output contract

The adapter locks candidate ID/SHA, batch summary bytes SHA, monitor-output SHA,
monitor run ID/batch timestamp, trusted registry identity/bytes SHA and accepted
reference bytes SHA. It rechecks after Drive readback and parse/search, and
requires the actual immutable M10B-1 evidence to match the same binding.
An old `readback_verified=true` JSON is never accepted as fresh remote proof.

The remote proof is a **snapshot at `checked_at_utc`**; it does not guarantee
remote immutability after the read. M10B-1 still locks the validation-time
accepted reference, not a cryptographically preserved M9 monitor-time reference.

Existing M10B-1 workspace identity/idempotence and stale-lock policy are reused.
Changed references, cached evidence from a different run, parser drift or
unsupported provenance fail closed. A stale `.lock` is not cleared automatically.
M10B-1 may leave immutable HOLD evidence; this adapter does not delete or
rewrite it. Recovery remains an explicit operator review.

JSON goes to stdout only; no second persistent bundle or ledger. It links
Drive path/readback time/bytes/SHA, batch/monitor/reference identity, immutable
parse-evidence SHA, manifest SHA and lexical page/chunk/content hashes. Raw
source snippets and provider diagnostics are omitted. `proof_written=false`
refers to this aggregate stdout report; explicit validation may still create
the pre-existing M10B-1 `candidate.pdf` and `evidence.json`.

| Status | Meaning / CLI exit |
| --- | --- |
| `NO_CHANGE` | No remote call or candidate workspace; exit 0 |
| `READY_FOR_DRIVE_READBACK` | Local plan only; exit 0 |
| `DRIVE_READBACK_VERIFIED_PARSE_PENDING` | Existing remote matched, no parse evidence written; exit 0 |
| `DRIVE_LINKED_LEXICAL_CANARY_PASSED` | Same-candidate parse and lexical evidence linked to that readback; exit 0 |
| `REVIEW_REQUIRED` / `LEXICAL_CANARY_FAILED` | Quality HOLD or lexical failure; exit 3 |
| `BLOCKED` | Unsafe/missing/mismatched input; exit 2 |

Always false: Production access/write, Drive write, shared DB access,
canonical promotion/update, accepted-reference advancement, model API use,
retrieval/semantic/answer verification. Gold page remains null and currentness
NOT_VERIFIED. `candidate_workspace_write_requested` records the separate
parse-workspace mode; `write_authorized=false` does not claim canonical release.

## Verification and remaining gates

`test_beta_validate_drive_candidate_v1.py` uses synthetic PDF and fake rclone
readback, including real M10B-1/M10B-2A functions. It covers default/no-change
non-write behavior, same-candidate linking and repeatability, readback-only
mode, missing/wrong remote, candidate/summary/reference/registry drift,
multimodal HOLD, lexical failure, stale monitor-bound evidence, destination
restrictions, stderr redaction and CLI confirmations/exit codes.

The existing full Validation workflow runs this integration and the original
M10A/M10B-1/M10B-2A regressions. No new standalone workflow.

Still unverified: genuine changed official PDF → actual Drive readback → this
adapter on deployed Staging; independent professional/page-content correctness;
active knowledge DB update; scheduler automation; HKeL; Anki; full USER_BETA.
The prior 41/41 Linux synthetic regression at the base SHA does not verify this
new adapter. Exact-head CI and later separately authorized runtime proof are
distinct gates.

Rollback: leave the standalone adapter unused and retain the previous Beta.
No active path invokes it, so no service/data migration is required. Do not
merge/deploy this Draft automatically or delete candidate/Drive history.

Next gate: review this contract and exact-head CI; only then plan a separately
authorized Staging operation with a genuine changed candidate. KB-05 real DB
commit/readback still needs its independent least-privilege and recovery gate
in Issue #94; this candidate-only adapter cannot satisfy it.
