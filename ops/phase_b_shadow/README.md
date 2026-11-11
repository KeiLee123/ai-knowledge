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
{"fixtures":{"app149_small":{"source_id":"BD_PNAP_APP149","version_id":"REVIEWED_VERSION_ID","model_version":"REVIEWED_MODEL_BUNDLE_ID","model_bundle_sha256":"64 lowercase hex digits from reviewed offline model inventory","filename":"APP149.pdf","sha256":"64 lowercase hex characters"}}}
```

`version_id` must come from reviewed source/version evidence. The catalog does
not grant current-version or publication authority by itself. Do not populate
it from a guessed URL, date or filename. The worker accepts only `fixture_id`
and SHA256 in the JSON task payload; no path, URL, PDF bytes or credentials.
Source size is capped at 5 MiB; PyMuPDF verifies the PDF has 1–10 physical
pages and is not encrypted before dispatch or Docling model loading.

The separately prepared, read-only model directory must contain all required
Docling model artifacts and a reviewed `model-version.txt` matching the
catalog's `model_version`. Prepare a content-based inventory **offline in a
separately approved preparation environment**, without running any model:

```sh
python -m phase_b_shadow.model_inventory /absolute/path/to/reviewed/models
```

The tool produces sorted relative paths, byte sizes, per-file SHA256 and the
canonical `model_bundle_sha256`. Review that inventory independently; pin
its exact digest in the **read-only** `catalog.json` fixture entry. Every
artifact, including `model-version.txt`, must be a regular file (no symlinks,
including Hugging Face cache links). Materialize a standalone model bundle
before review if needed. The Worker now recomputes the entire bundle digest
**before conversion** and refuses mismatches; changing model bytes also
changes the deterministic task ID. The Worker sets offline mode and disables
Docling remote services, external plugins, OCR and GPU. No model is fetched
as part of the first VPS run. Model content integrity alone does not establish
license/provenance, verified model quality or successful Docling runtime.

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
deterministic task ID.
The manifest is first written to a private candidate filename; the existing
Router and Chunk Builder must both succeed and produce at least one grounded
chunk before it is atomically published as `*.manifest.json`. Any failed
chunk compatibility check yields HOLD without a published manifest. A hard
worker kill still requires manual reconciliation of the preserved task lock;
a successful shadow receipt is not a canonical DB/Drive approval.
 A duplicate task returns the previous receipt only after rechecking the
matching source/model identity and manifest hash. A published manifest without
a valid READY receipt, a HOLD receipt coexisting with a published manifest, or
a surviving task lock triggers manual reconciliation before any replay.
If writing the READY receipt fails after publishing the manifest, the task
lock is deliberately preserved instead of automatically retrying the parse.
Redis is a transient broker,
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

The separate [Model Supply Gate](MODEL_SUPPLY_GATE.md) describes the official
model sources, offline preparation, CPU-only packaging and approval checklist.

## Next Staging acceptance gate (not authorized to run yet)

**Trusted input:** a read-only Google Drive copy named APP149.pdf was re-fetched and
hashed on 2026-11-04, 25,520 bytes, 5 unencrypted physical pages, SHA256
`a5b4d5a1af5f4a32b43973db33d95436f9390e8e2da77747ee666015077bb1a8`.
This verifies the reviewed source *bytes*, NOT Docling conversion or current
legal/official version status. The catalog must use an independently reviewed
`version_id`; never infer it from the file basename or date.

Before any new VPS container/service installation, obtain separate deployment
authorization. The operator then needs an isolated, non-Production handoff for
the above exact five-page PDF, `catalog.json`, and Docling's entire **offline**
model bundle. In a separately approved preparation environment, record the
Docling package version, each model artifact's relative path/size/SHA256, and
a canonical bundle inventory digest; review and preserve those values in the
acceptance evidence. Mount the bundle read-only. **A matching
`model-version.txt` alone is insufficient to authenticate model bytes.** The
new code additionally verifies every staged model artifact against the catalog's
pinned whole-bundle digest, but genuine model supply/identity still require
independent operator review. Never let the runtime fetch missing models.

For the approved one-job trial, the operator should:

1. Rehash APP149.pdf inside the final fixture mount; check 25,520 bytes,
   5 pages, and exact SHA256 before dispatch. Fail closed on any difference.
2. Verify the staged model inventory against the reviewed offline inventory,
   installed Docling 2.146.0, no missing/changed files, and no model downloads.
3. Verify the isolated Compose configuration has **no published ports, DB
   network, credentials, Docker/DB socket, Beat, or Writer access**, then start
   only the new staging shadow Redis and single worker after authorization.
4. Dispatch exactly one allowlisted `app149_small` job, collect task ID,
   exit/error code, wall time, peak worker RSS/CPU and host memory pressure,
   model/cache identity and stdout/stderr without secret or PDF-text leakage.
   Initial limits: 1 vCPU/3 GiB worker, 0.25 vCPU/256 MiB Redis,
   Celery concurrency=1 and 180s hard task limit.
5. Read back the isolated manifest and receipt with SHA256. Require
   `READY_SHADOW` with five physical pages, matching source hash,
   stable item/page coordinates, no missing native-text pages, existing
   Router/Chunk compatibility and no DB write. Compare page text/provenance
   against the existing v2 extractor, recording any differences as HOLD.
   APP149 alone **cannot** prove table-cell numerical quality or OCR accuracy.
6. Exercise one bounded duplicate and one controlled worker-failure recovery
   after the successful run; never infer exactly-once delivery.
7. **STOP / HOLD** on any SHA/model mismatch, missing evidence, unexpected
   network access, duplicate publication, OOM, excessive runtime, page loss,
   wrong source version, or provenance mismatch. Stop/remove only the new
   shadow containers; leave Frozen M8/M9, Staging DB and Production untouched.
   Preserve incident evidence separately, then review an approved rollback.

GitHub Unit/CI PASS is not a real Staging benchmark or Product Acceptance.

The pinned Docling v2.146.0 `DocumentConverter.convert()` accepts
`max_num_pages` and `max_file_size`. The adapter now passes the same
10-page/5-MiB bounds enforced by the local SHA-pinned Fixture preflight,
providing a second parser-side limit if the source changes before conversion.
The API signature and status enum were reviewed against the v2.146.0
repository source; the offline shim regression verifies call configuration,
not real model behavior or CPU/RAM fit.
