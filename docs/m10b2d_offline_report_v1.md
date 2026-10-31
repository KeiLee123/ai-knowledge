# M10B-2D — Offline Retrieval Report Contract v0.1

Status: GitHub feature branch → staging CI gate → VPS Staging offline regression. **No live Embedding or Production work.**

Architecture: M10B-2C is the trusted, **fabricated synthetic-only** in-memory comparison of Lexical search and supplied fake 384-dimensional vectors. M10B-2D adds a small pure Markdown view to make those already-validated results readable. No new retrieval engine, no database, no UI service, no PDF/Drive exporter or timer.

## Architecture / Data flow

Two-page synthetic PDF and Gold Fixture → existing M10B-2C comparison result (with report SHA256) → **M10B-2D renderer** → bounded Markdown string in memory.

Function: `m10b2d_offline_report_v1.render_offline_markdown(comparison)`. No CLI and **no file output**; the developer test script is the offline entry point. A future export can be separately approved after reviewing a redaction contract.

## What the report shows

- Permanently visible **SYNTHETIC ONLY** / non-real-AI warning, source/candidate SHA, suite/fixture ID, comparison checksum, top-k.
- Summary table: synthetic positive page matches for Lexical vs hand-authored vector fixture; synthetic negative false positives.
- Individual rows: case ID/type, lexical PASS/FAIL, hand-authored vector PASS/FAIL, expected synthetic page(s), retrieved pages and an allowlisted human-readable reason. **No raw query, PDF text, excerpt, vector, model server or logs.**
- Clear distinction between the baseline Lexical miss on the paraphrase fixture and the hand-authored mock vector finding a page. The latter is **NOT** evidence that intfloat/multilingual-e5-small improves retrieval.
- Explicit failure row and count when the fabricated vector predicts a wrong page or incorrectly answers a negative.

## Safeguards and tamper protection

Input schema is **exactly** the M10B-2C report fields; extra fields, case fields, malformed/duplicate case IDs, unbounded lengths and arbitrary Markdown-containing names are rejected. A canonical comparison SHA256 is rechecked against the original result (reproducibility check only, not cryptographic authorship proof).

In addition to the checksum, M10B-2D recomputes counters from per-case status and difference labels and checks reason/status/page semantics, positive/negative coverage, case identity and source/candidate binding. Even a maliciously recomputed hash cannot change the immutable synthetic-only flags, model contract, reason codes or schema.

It rejects any `official_document_verified=true`, `gold_page_verified=true`, `semantic_verified=true`, `real_embedding_service_called=true`, `production_access=true`, `shared_db_access=true` or write authorization. Must not falsely present fabricated vectors as live model results.

The formatter returns a deterministic Markdown string, maximum 30,000 characters, and does not mutate the input. No model inference, HTTP, disk reads/writes, Docker, database, shared state, scheduler or Production changes.

## Synthetic fixture example (not real-world performance)

The 5-case test fixture contains 3 positives and 2 negatives. Expected hand-authored results: Lexical positive page match = 2/3, hand-authored vector = 3/3; Lexical negative false positives = 1/2, hand-authored vector = 0/2. A positive paraphrase intentionally has no literal lexical overlap. A negative near-miss intentionally shares vocabulary. The mock fixture has predetermined vector axes and predetermined abstain flags; its resulting PASS counts do not measure model intelligence.

## Regression and acceptance

`test_m10b2d_offline_report_v1.py` has 16 tests: five-row readable report; paraphrase disclaimer; negative near-miss visibility; fixture false positives/wrong pages; checksum tampering; forged approved flags even with recomputed hash; malicious/extra fields; falsified counters/status; wrong reasons/labels; unsafe pages; real-model impersonation; cross-candidate/fixture; determinism; network, file and subprocess blocks; no raw PDF/Gold/query text.

CI must run M10A, M10B-0, M10B-1, M10B-2A lexical, M10B-2A synthetic Gold, M10B-2B-0 synthetic semantic, M10B-2B-1 offline endpoint audit, M10B-2C comparison and M10B-2D renderer. Dedicated PR CI + post-merge dedicated/full Validation must PASS against exact Staging SHA before VPS acceptance.

Acceptance sequence: GitHub Feature → PR review → staging merge → full CI PASS → VPS Staging pinned commit → regression-only. No modification of Frozen Graph-aware Retrieval v1.3, M5D accepted references, M8/M9, main/Production, Oracle Firewall or Coolify.

## Limitation

Official APP145/APP149 Gold Page verification, actual Embedding model behavior and answer grounding remain **NOT VERIFIED**. Live model security audit is paused at user request. Rendering a test result is not equivalent to deploying a report, emailing it or creating a Google Drive report.

Source: https://github.com/KeiLee123/ai-knowledge/blob/staging/docs/m10b2c_offline_comparison_v1.md
