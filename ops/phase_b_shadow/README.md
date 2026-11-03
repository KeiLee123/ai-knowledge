# Phase B: isolated PDF shadow worker (code only)

This directory is a **Staging deployment proposal**, not an instruction to start a
service. No VPS deployment, model download, database access or timer cutover is
authorized by this code. The first real run needs a separate operator approval
and a reviewed, SHA256-pinned small PDF (prefer the already staged APP149 file).

## Existing contract and reuse

- `extract_document_v2.py` defines `document-manifest-v2`, source SHA256 and
  top-left page/table bounding boxes. The shadow code reuses its SHA and text
  normalization functions.
- `route_document_v2.py` assesses a complete manifest. The shadow runner records
  its diagnostic route without changing the active pipeline.
- `build_multimodal_chunks_v2.py` checks that native text and structured table
  evidence can become page-grounded chunks. The shadow runner does not persist
  those chunks or call a writer.
- `orchestrate_document_v2.py` currently enters DB inspection/ingestion paths.
  It is intentionally not invoked by this isolated, no-DB phase. Its manifest
  boundary is the compatibility target.
- HKeL XML parsing and frozen Retrieval/Answer are untouched.

## Manual fixture contract

The read-only fixture directory contains `catalog.json` and only reviewed PDF
bytes. A catalog entry is pinned to the local file SHA256 and an enabled official
`source_id` in `source_registry_v1.yaml`:

```json
{"fixtures":{"app149_small":{"source_id":"BD_PNAP_APP149","version_id":"REVIEWED_VERSION_ID","model_version":"REVIEWED_MODEL_BUNDLE_ID","filename":"APP149.pdf","sha256":"64 lowercase hex characters"}}}
```

`version_id` must come from reviewed source/version evidence. The catalog does
not grant current-version or publication authority by itself. Do not populate
it from a guessed URL, date or filename. The worker accepts only `fixture_id`
and SHA256 in the JSON task payload; no path, URL, PDF bytes or credentials.
Source size is capped at 5 MiB and parsed page count at 10.

The separately prepared, read-only model directory must contain all required
Docling model artifacts and a reviewed `model-version.txt` matching the
catalog's `model_version`. The worker sets offline mode and disables Docling remote services,
external plugins, OCR and GPU. No model is fetched as part of the first VPS
run. Model identity and table correctness still require real acceptance.

## Proposed Staging-only invocation after separate approval

An operator creates `/tmp/jason-os-phase-b-shadow/artifacts` owned by UID
10001, with no symlink and restrictive permissions. The operator provides
absolute paths for `PHASE_B_FIXTURE_DIR`, `PHASE_B_MODEL_DIR` and
`PHASE_B_REDIS_PASSWORD_FILE` outside Git. The password file is a dedicated
secret of at least 24 characters. The model directory is read-only in the
container. Then, from this repo and only after the deployment gate:

```sh
docker compose -f ops/phase_b_shadow/compose.yaml config
docker compose -f ops/phase_b_shadow/compose.yaml up --build -d redis worker
docker compose -f ops/phase_b_shadow/compose.yaml run --rm --no-deps worker \
  python -m phase_b_shadow.dispatch app149_small
```

The artifact directory holds one manifest and result receipt named by the
deterministic task ID. A duplicate task returns the previous receipt. An active
or crashed lock is held for manual reconciliation. Redis is a transient broker,
not a durable job ledger; Celery may redeliver, so no exactly-once claim is made.
No Beat service is defined. The Compose network is internal, no port is
published, and no DB or Docker socket is mounted.

The adapter converts Docling item boxes into PDF points with top-left origin,
`[x0, y0, x1, y1]`; `BOTTOMLEFT` boxes use the physical page height for
conversion. It preserves item reading order and table cell coordinates. A
missing/ambiguous page, box, table cell, model version or scanned/visual-only
page yields `AUTO_HOLD_CONTRACT_GAP`. Merged/spanning table cells are held
because the existing rows contract cannot represent them faithfully. OCR is
disabled in this MVP, so no OCR evidence is invented.

## Acceptance state

Offline unit tests can establish code-path behavior only. GitHub CI on the
exact PR head, a real small-PDF Docling run in isolated Staging, resource
benchmark, table/page comparison against the existing extractor, model cache
identity and product acceptance are separate gates. The PostgreSQL
authentication/recovery HOLD remains in force before any DB-connected worker.
