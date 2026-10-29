# M10B-2A — Candidate-only lexical retrieval v0.1

**GitHub feature PR / no VPS deployment / no Production changes.**

Architecture Source of Truth:
https://docs.google.com/document/d/1eev9RtJm7L_71Q0VQFDTMphtfqzHGyXzjphZTVTzaRg/edit

## Scope

M10B-2A is a **read-only** candidate-scoped lexical canary. It only reads one existing M10B-1 `PARSE_VERIFIED` candidate at a content-addressed path, rechecks immutable evidence, accepted reference and manifest, builds page-scoped native-text chunks in memory, and runs registry-defined query/expected-term smoke checks. The code does not call an embedding endpoint, shared Staging DB, Docker, Google Drive, external Vision, or the frozen v1.3 answer pipeline. It does not create any directory or evidence file.

The outcome `LEXICAL_CANARY_PASSED` **does not** mean Gold Page, semantic retrieval, answer quality, full Staging qualification or Production approval. In all outcomes `retrieval_verified=false`, `gold_page_verified=null`, `semantic_verified=false`, `answer_verified=false`, `write_authorized=false`.

## Input

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python m10b2a_candidate_lexical_v1.py \
  --source BD_PNAP_APP149 --candidate-sha <M10B-1_CANDIDATE_SHA256>
```

For **synthetic regression only**, `--state-root` and `--workspace-root` may target sibling fixture directories named `source-monitor-staging` and `source-update-validation-staging`. Real Staging paths must remain the fixed canonical paths. M10B-2A requires an existing `candidate.pdf` and `evidence.json`; NO_CHANGE does not create them and is not a retrieval PASS.

## Admission and replay

1. Strictly allowlisted repository Source Registry identity, source enabled, canonical HTTPS host, English-language smoke case.
2. M10B-1 evidence status PARSE_VERIFIED, route legacy-v1, policy CANDIDATE_NEW_VERSION, version and trusted identity match; unsafe flags all false.
3. Verify SHA-256 of candidate PDF, evidence bytes, and M5D accepted reference before and after. Reject symlinks in candidate paths and any changed accepted snapshot.
4. Rebuild document-manifest-v2 with existing local parser; compare the exact canonical JSON SHA against M10B-1 evidence manifest_sha256. A parser drift is a failure, not silently accepted.
5. Re-evaluate local source version candidate policy with validation/release flags false. Do not derive release permission.
6. Reuse pure build_multimodal_chunks_v2.build_chunks() with fixed target_chars=1800 and overlap_chars=0; only permit provenance native_text. Verify each chunk's text is present in the exact page recorded by metadata and page range is valid.
7. Deterministic English token-overlap lexical ranking with top_k=1..10, scores + stable page/chunk ordering. Smoke test queries/expected terms come from the trusted source registry, not candidate content.
8. JSON to stdout only; snippets, SHA, candidate ID, page and origin accompany every result. No proof persistence in v0.1; evidence storage option from the broader architecture deferred until content and gold tests are reviewed.

## Status semantics

- `LEXICAL_CANARY_PASSED`: indexed candidate native text contains registry terms in relevant top-k chunks and candidate page citations are structurally traceable; **not independently gold-page verified**.
- `LEXICAL_CANARY_FAILED`: test is missing expected terms or returned no ranked hits. This is **not** a pass (even though CLI returns a data report).
- `BLOCKED`: unsafe/mismatched evidence, SHA, source, accepted reference, manifest drift, unsupported route/language, altered page metadata, untrusted symlinks or no candidate.

Any semantic search, Gold Page accuracy and AI-generated answers remain unverified by design. Do not mark a FULL STAGING VERIFIED state based on a lexical canary result.

## Test evidence and remaining gates

Synthetic PDF fixture from `test_m10b1_isolated_candidate_v1.py`. M10B-2A tests cover read-only no writes, repeatability, expected-term PASS, missing-term FAIL, no-hit FAIL, empty expectations block, wrong candidate/source SHA, altered evidence, accepted-reference drift, tampered PDF, changed parser manifest, forged page metadata, unsupported vision-derived chunk, symlink, NO_CHANGE missing candidate, deterministic page tie-breaker and denied external network/subprocess.

Gold Page test cases are not supplied by the current Source Registry; no synthetic Gold Page can establish correctness of real regulatory PDF page citations. Proposed M10B-2A Gold fixture and M10B-2B semantic adapter are separate changes, with human/independently verified ground truth and explicit independent approval.

M10A, M10B-0, M10B-1 regressions and the existing staging Validation CI must remain green; after GitHub staging merge, VPS Staging read-only execution still requires separate user-run acceptance.
