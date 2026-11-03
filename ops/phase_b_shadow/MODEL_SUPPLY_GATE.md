# Phase B model supply gate — offline preparation and acceptance v0.1

**Status: DESIGN / CODE-ONLY. No model binaries acquired or distributed by this PR.
No VPS download, Docker deployment, PostgreSQL access, source publication, Beat
enablement, Production change, or PR merge authorized.**

This note is for a separately authorized preparation environment, followed by
a second and independent authorization for a bounded Staging runtime test.

## 1. Locked application and expected model categories

- Phase B Python package pin is `docling==2.146.0` in
  `requirements-phase-b.txt`. Verify the exact installed
  `docling` / `docling-core` / `docling-ibm-models` / `docling-parse`
  versions and a dependency lock/SBOM from the *same final image*, not a laptop.
- The actual `PdfPipelineOptions` in
  `phase_b_shadow/docling_adapter.py` enables layout detection and
  `do_table_structure=True`, disables OCR and remote services/plugins,
  and requests CPU processing. The first small-PDF gate therefore targets
  **layout + tableformer**, not every Docling model.
- Official model sources to verify in the final v2.146.0 implementation:
  `docling-project/docling-layout-heron` and
  `docling-project/docling-models` on Hugging Face. An actual downloader
  may fetch additional layout engine/override files; record all files and
  repositories seen rather than guessing the final bundle contents.
- Model repositories' visible license metadata differ (Heron: Apache-2.0;
  docling-models: CDLA-Permissive-2.0 / Apache-2.0). Verify attribution and
  each included artifact's permitted use; this file does **not** approve
  licensing.
- The default model downloader fetches more than layout + table structure.
  Do **not** use `--all` or `docling-tools models download` without
  selecting the two models during the MVP.

References (review again against the pinned release when preparing):
- https://docling-project.github.io/docling/usage/advanced_options/
- https://docling-project.github.io/docling/reference/cli/
- https://docling-project.github.io/docling/reference/pipeline_options/
- https://pypi.org/project/docling/2.146.0/
- https://huggingface.co/docling-project/docling-layout-heron
- https://huggingface.co/docling-project/docling-models

## 2. Offline supply design (NOT a command to run on the VPS now)

Use a separately authorized, disposable Linux x86_64 preparation environment
matching the Worker image's Python and CPU architecture. Keep credentials out
of terminal logs, PRs and artifacts. The following commands are **illustrative**;
they require first installing reviewed and pinned dependencies in that
preparation environment, and checking `docling-tools models download --help`
for the installed Docling release.

```sh
# PREPARATION ENVIRONMENT ONLY — NOT THE PRODUCTION/STAGING VPS
MODEL_DIR="/absolute/private/path/models"
docling-tools models download layout tableformer --output-dir "$MODEL_DIR"

# Add a reviewed immutable identifier after the download has completed.
# Content must be separately approved; DO NOT invent or reuse a prior ID.
printf '%s\n' "REVIEWED_MODEL_VERSION_ID" > "$MODEL_DIR/model-version.txt"

# Run from a checkout of the exact PR #95 code with its Python dependencies.
# Save outside MODEL_DIR to avoid a self-hashing circular file.
python -m phase_b_shadow.model_inventory "$MODEL_DIR" > /absolute/private/path/acceptance/model-inventory.json
```

**Important:** these commands have not been executed in this review. Do not
place `model-inventory.json`, operator approvals, secrets or private PDF bytes
inside `MODEL_DIR` or the Git repository. Model downloads may use Hugging
Face cache symlinks; create a standalone regular-file copy **without
changing relative paths needed by Docling**, then inventory that final copy.
`model_inventory.py` intentionally fails on symlinks, missing weight files
or unsafe filename control characters.

The downloader has no proven immutable per-repository revision pin in the
above CLI invocation. Record the **resolved immutable Hugging Face commit
revisions** for every downloaded model repository, model cards/licenses,
download logs, selected Docling and other dependency versions, architecture,
inventory path/size/per-file SHA256 and canonical bundle digest. This
provenance metadata is maintained separately from the actual model directory.
An approved bundle digest authenticates **bytes**, not licensing, source
approval, compatibility or correctness. Record any extra model repositories
seen during downloader execution for independent review rather than assuming
the two named repositories are exhaustive.

## 3. CPU-only packaging is a separate blocker

The current `ops/phase_b_shadow/Dockerfile` uses
`pip install -r requirements-phase-b.txt` in `python:3.12-slim`. The
`CUDA_VISIBLE_DEVICES=""` environment variable does **not** guarantee
CPU-only Torch wheel installation. On Linux, pip resolution may include
GPU/CUDA dependencies, increasing image size, build I/O and risk to the
shared 2-vCPU, 11-GiB-RAM, zero-swap VPS.

Before approving any `docker compose up --build` on the VPS, independently
review a CPU-only PyTorch wheelhouse/index and a reproducible, pinned
dependency lock; verify the resolved `torch` distribution, model versions,
container image digest, image size and `pip check` in an isolated build
environment. Do not uncritically introduce a guessed Torch version into
this frozen feature branch. If the final validated image cannot run the
unmodified Phase B contract offline, HOLD and fix only with regression.
Reference: https://pytorch.org/get-started/previous-versions/

## 4. Staging receipt / artifact acceptance

Once and only once the user separately approves the Staging runtime:

1. Confirm Git commit, clean worktree, runtime isolation, no DB routes,
   no host ports, no Docker/DB sockets and no Beat.
2. Verify the mounted APP149.pdf source matches the previously independently
   fetched Drive bytes: **25,520 bytes, 5 pages, SHA256
   a5b4d5a1af5f4a32b43973db33d95436f9390e8e2da77747ee666015077bb1a8**.
   Its source/version authority is separately reviewed; a file checksum
   alone does not prove it is the currently effective official edition.
3. Verify final offline model bundle against reviewed inventory and
   `model_bundle_sha256`; write the **approved** digest and model ID into
   the read-only fixture `catalog.json`. The current Worker recomputes
   the model bundle digest before every new parse and before reusing a
   successful duplicate receipt.
4. In the separately approved isolated Worker, dispatch one manual
   allowlisted job only; measure elapsed seconds, peak CPU/RAM, OOMs,
   timeouts, input/output SHA256, five-page coverage and provenance
   parity with the old extractor. Record material table/reading-order
   discrepancies as `AUTO_HOLD`; do not interpret synthetic unit tests
   as real parser acceptance.
5. Duplicate and bounded crash/retry tests are separate acceptance
   observations. Do not allow old and new engines to concurrently write
   canonical DB/Drive state. **No DB Writer exists in Phase B.**
6. Rollback: stop and remove only newly approved shadow services,
   preserve evidence, leave Frozen M8/M9, PostgreSQL and Production
   unchanged. A failed build/download or unverified model => HOLD; no
   Production promotion.

## 5. Current gates

| Gate | Status |
| --- | --- |
| APP149 source bytes/SHA256 from Google Drive | VERIFIED at source, not VPS mount |
| Phase B contract Unit/CI | PASS at exact PR head recorded in PR |
| Verified model download repository revisions/license | HOLD |
| Actual offline model asset inventory, digest and Staging mount | HOLD |
| CPU-only image dependencies and size | HOLD |
| Real Docling conversion + resources + provenance | NOT RUN |
| Private Beta / Product Acceptance | NOT RUN |
| PostgreSQL trust auth and backup restore for future Writer | HOLD |

**This runbook does not authorize any installation, download, Docker
container start, external model execution or production change.**
