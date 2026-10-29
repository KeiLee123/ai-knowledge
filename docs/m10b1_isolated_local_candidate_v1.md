# M10B-1 — Isolated Local Candidate Validation v0.1

Status: **Implementation candidate / GitHub feature branch / no VPS deployment**.

Architecture Source of Truth:
https://docs.google.com/document/d/1aZBVFRR0IperUB18xMNkrLWxTZUCEJU9jh9OG07XXFg/edit

M10B-0 contract audit:
https://docs.google.com/document/d/11SMODBMPaAsUum5gWOHPvwQA7iNHrc3Ixu2WJ0SIEqI/edit

## Purpose and release boundary

M10B-1 bridges M10A verified M9 candidates to **local parse-only quality evidence**. It never updates M9 baselines, M5D accepted reference, Google Drive Current, production, or any Staging DB. There is no auto-ingest, semantic retrieval or release qualification. Its most favorable state is `PARSE_VERIFIED`; this is **not** `STAGING_VERIFIED`, `AUTO_QUALIFIED` or release approval.

## CLI

Default plan (strictly read only, no directory creation):

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python m10b1_isolated_candidate_v1.py \
  --summary /var/lib/jason-os/source-monitor-staging/batches/<TIMESTAMP>/summary.json \
  --source BD_PNAP_APP149
```

Explicit parse evidence in a dedicated Staging-only workspace (no DB/Drive/API):

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python m10b1_isolated_candidate_v1.py \
  --summary /var/lib/jason-os/source-monitor-staging/batches/<TIMESTAMP>/summary.json \
  --source BD_PNAP_APP149 \
  --validate --confirm-staging-candidate-write
```

Workspace: `/var/lib/jason-os/source-update-validation-staging/candidates/<source_id>/<candidate_sha256>/`. The only permitted files are `candidate.pdf`, `evidence.json` and a transient `.lock`. The candidate-specific output is stable/idempotent, with atomic create-if-absent evidence. Synthetic fixture workspaces must be siblings of fixture `source-monitor-staging` root.

## Security gates

1. Re-run M10A `inspect_batch` for the exact source/summary; NO_CHANGE does not create a workspace. Intake BLOCKED is never translated to pass.
2. Load **trusted repository** `source_registry_v1.yaml` and require enabled source, nonblank authority/document code/source family/canonical URL, HTTPS, and allowlisted canonical host. Ignore any candidate-supplied endpoint.
3. Compare the accepted M5D reference *entire record* SHA from M10A against current raw bytes; require accepted identity and material fingerprints. Reject `None == None` source identity.
4. Lock candidate ID `source_id:sha256`; copy original M9 PDF only into candidate workspace and recheck SHA. No modification of original M9 run files.
5. Use only local `extract_document_v2.build_manifest`, `route_document_v2.assess_manifest(allow_partial=False)`, `version_signal_extractor_v1` snapshot/compare and `version_qualification_policy_v1.evaluate_version_candidate`.
6. Verify all pages, source bytes and accepted reference SHA again at finish. If reference changed => REVIEW_REQUIRED, if policy rejects => BLOCKED or REVIEW_REQUIRED. If OCR/Vision needed => REVIEW_REQUIRED. Only legacy-v1 PDF with >=100 normalized text characters and candidate policy `CANDIDATE_NEW_VERSION` can produce `PARSE_VERIFIED`.
7. No use of `orchestrate_document_v2.py --prepare` (DB reads), `run_multimodal_canary_v2.py`, `ingest_manifest_v2.py`, `ingest_canonical_text_staging_v1.py`, `augment_vision_v2.py`, `validate_staging_retrieval_v2.py`. No model endpoint calls.

## States

- `NO_CHANGE`: no candidate, zero workspace writes.
- `READY_FOR_PARSE`: read-only plan, no workspace writes.
- `PARSE_VERIFIED`: local PDF manifest + router + trusted identity + version candidate policy verified. Retrieval remains NOT VERIFIED.
- `REVIEW_REQUIRED`: multimodal or reference drift or insufficient data; not a release state.
- `BLOCKED`: mismatched identity or SHA, invalid PDF/unsafe workspace, unsupported source, failed evidence guard. Exit code 2.

Every output includes `production_access=false`, `production_write=false`, `write_authorized=false`, `canonical_promoted=false`, `accepted_reference_advanced=false`, `retrieval_verified=false`.

## Test scope

Use synthetically generated PDF with clearly fake policy text. Regression tests cover no-write plan, valid local parse, deterministic/idempotent evidence, NO_CHANGE, absent/mismatched identity, candidate tamper, malformed PDF, multimodal not silently downgraded, accepted-reference drift, workspace symlink escape and explicit write flag. An integration check forbids network/subprocess invocation during the local plan/parse path.

## Limitations / follow-up

- M10B-1 records **validation-time** reference snapshot, not monitor-time cryptographic lock. M9 remains frozen.
- Current parser extracts text and route metadata but does not prove OCR/Vision content, table-level semantic retrieval, or citation quality.
- In-flight interruption may leave a stale `.lock`; the first release intentionally fails closed rather than automatically unlocking. Recovery requires review of state and owner.
- Workspace evidence does not replace Drive as document Source of Truth; evidence retention/archival policy belongs in the next milestone.
- No real official newer APP145/APP149 PDF has been live-proven. Successful synthetic tests must not be represented as official updates.
