# Phase B model supply gate — offline preparation and acceptance v0.1

**Status: OFF-VPS BYTES HASHED / CPU PYTHON WHEEL CHECK PASS (2026-11-05).
Models were downloaded to an ephemeral GitHub Runner, not retained or delivered
to Staging. No weights were published as GitHub artifacts; no CPU Docker image
was built. VPS deployment, PostgreSQL, Production, Beat, and PR merge remain
NOT AUTHORIZED.**

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
| Immutable HF source revision / downloaded bytes | 3 SHA-pinned repositories fetched, 20 files / 701,224,343 bytes SHA-verified (candidate evidence) |
| Model licensing / private transfer / Staging model mount | HOLD (metadata only; binaries not retained in a secure destination) |
| CPU-only dependency install and pip check | PASS in temporary Linux runner (Torch 2.9.1+cpu and Docling 2.146.0) |
| Actual CPU-only Docker image build, size and digest | HOLD (no image built) |
| Real Docling conversion + resources + provenance | NOT RUN |
| Private Beta / Product Acceptance | NOT RUN |
| PostgreSQL trust auth and backup restore for future Writer | HOLD |

**One explicitly approved off-VPS model download and Python CPU package
feasibility test were executed on 2026-11-05. This approval does not cover
another remote acquisition, permanent binary redistribution/transfer,
VPS/Docker container start, model inference or Production change.**

## 6. GitHub Actions preparation feasibility — reviewed 2026-11-04

The current repository is **public** and its default branch is **main**.
GitHub Actions `workflow_dispatch` requires the workflow definition to
exist on the default branch; a new manually dispatched workflow added **only**
to Draft PR #95 is **not directly runnable** from the Actions UI. Creating
that file alone is not an accepted model-preparation process. Do not
merge or add a dispatch workflow to main simply to work around this gate.

Standard GitHub-hosted `ubuntu-24.04` runners have **14 GB SSD**
(virtual CPU/RAM allocations depend on repository visibility); model
dependencies, CPU-only Torch wheels, the build cache, and final artifacts
must all fit that temporary disk. This has not been benchmarked. Any
remote model download or Docker build can consume network and compute;
neither is authorized by this Code-only PR.

GitHub Action artifacts in a **public** repository are readable by
anyone with repository read access. They are not an appropriate default
destination for model weights before licensing, redistribution, retention
and trusted delivery are reviewed. They also expire. Do not upload
private PDFs, passwords, full PDF text, credentials or unreviewed
weights. For the first MVP, prefer a separately authorized external
preparation environment and a private, verified model transfer; keep
GitHub as the code source, not the source of truth for the model binaries.
If external preparation is unavailable, propose a narrowly scoped
manual workflow after a separate explicit approval and source/license
review; do not activate it now.

The **existing** inventory tool has two read-only modes:

```sh
# Outside VPS, after independently approved model supply. No downloads occur.
python -m phase_b_shadow.model_inventory /path/to/models > /private/model-inventory.json

# After a human has reviewed and pinned that exact 64-char digest:
python -m phase_b_shadow.model_inventory \
  /path/to/models --expected-sha256 REVIEWED_64_CHAR_SHA256
```

The second form fails closed for altered, missing or unreviewed model
assets. Run it against the final standalone model directory **after**
copy/transfer as well, never against only the downloader's cache.
Do not write the JSON inventory into the model directory itself
(it would recursively change its own digest).

Official references:
- https://docs.github.com/en/actions/how-tos/manage-workflow-runs/manually-run-a-workflow
- https://docs.github.com/en/actions/how-tos/write-workflows/choose-where-workflows-run/choose-the-runner-for-a-job
- https://docs.github.com/en/actions/how-tos/manage-workflow-runs/download-workflow-artifacts

**Status:** The branch-only workflow was executed once; actual model bytes
were hashed on GitHub's temporary runner, without a permanent model-binary
artifact. Metadata is in the referenced model evidence artifact. Private
binary delivery remains HOLD; no workflow may be merged to a frozen layer
without separate review.

## 7. Candidate immutable upstream source identities — 2026-11-04

**PUBLIC-METADATA-VERIFIED ONLY; candidate pins, NOT approval of supplied
model bytes, selected downloader output or runtime compatibility.**

The public Hugging Face repository history links identify these full commits,
where the upstream repository browser showed the following files/licensing:

| Purpose | Repository | Candidate full revision | Upstream license label |
| --- | --- | --- | --- |
| Layout Heron | `docling-project/docling-layout-heron` | `8f39ad3c0b4c58e9c2d2c84a38465abf757272d8` | Apache-2.0 |
| TableFormer shared repository | `docling-project/docling-models` | `2199320848bb9a8a519d22e4b528185a4f9a6f64` | CDLA-Permissive-2.0 / Apache-2.0 |

- Layout repo at the observed revision: `model.safetensors` (~172 MB
  displayed), `config.json`, `preprocessor_config.json`, model card and
  image. TableFormer shared repo displayed ~358 MB total. These are **Hub
  UI estimates**, not verified downloaded byte counts, not an acceptance
  memory/RAM figure.
- Upstream commit references:
  https://huggingface.co/docling-project/docling-layout-heron/commit/8f39ad3c0b4c58e9c2d2c84a38465abf757272d8
  https://huggingface.co/docling-project/docling-models/commit/2199320848bb9a8a519d22e4b528185a4f9a6f64
- The pinned Docling wheel's PyPI release page independently lists
  `docling-2.146.0-py3-none-any.whl` SHA256
  `0a513ade59476e49501f60f23fca8ae2064158e1731e726a55381d99fb21c015`
  and attests a build from
  `docling-project/docling@c622bcb97c6e24736bf81402cbe4ebc908a7bd9c`.
  This pins the top-level package artifact provenance, **NOT** its
  transitive Python wheels or the separate pretrained models.
  Reference: https://pypi.org/project/docling/2.146.0/
- The official CLI reference explicitly supports
  `docling-tools models download layout tableformer --output-dir MODELS`;
  the default selection and `--all` are larger. Reference:
  https://docling-project.github.io/docling/reference/cli/
- **Safety/compatibility HOLD:** the CLI's named download command does not
  itself accept these pinned Hugging Face commit hashes. An operator must
  prove the downloader's actual resolved revisions and paths match these
  reviewed candidates, or use a separately reviewed immutable-revision
  download and reproduce the exact artifacts-path layout. If revisions
  differ, review the discrepancy instead of silently changing the catalog.
- **Additional hold:** PyTorch's official installation instructions have
  a separate Linux CPU package option. The existing Worker Dockerfile
  has not been built with a CPU-only lock or vetted wheelhouse.
  Reference: https://pytorch.org/get-started/locally/

Next acceptance evidence, **not yet present**: resolved model source
revisions from the actual preparation run, final local artifact path/size/
SHA256 inventory, licensing and attribution review, verified canonical
bundle digest and CPU-only image digest/package manifest. These must be
recorded before anyone is authorized to start the Staging shadow worker.

## 8. One-shot external model supply evidence (separately authorized 2026-11-05)

A single `push`-triggered workflow on this Feature Branch is intentionally
limited to **the workflow file itself** via `paths`, so routine PR changes
will not repeat downloads. This is a GitHub-hosted, non-VPS environment,
not `workflow_dispatch`, not a Production release, and not a new scheduler.

`ops/phase_b_shadow/prepare_model_supply.py` obtains **actual bytes** from
three immutable Hugging Face commits selected from the pinned Docling
v2.146.0 downloader and calculates the existing canonical bundle digest.
The extra Layout Heron ONNX repo is required by the downloader even though
the default Layout engine is Transformers. TableFormer uses tag `v2.3.0`
in the Docling source; the observed immutable commit behind that tag is
`fc0f2d45e2218ea24bce5045f58a389aed16dc23`. This supersedes the
earlier *candidate main-branch* TableFormer SHA
`2199320848bb9a8a519d22e4b528185a4f9a6f64` for this v2.146.0
preparation trial. Third ONNX commit:
`40bde044036bb181c130ddf6c51792187268748f`.

The workflow NEVER uploads model weights or PDFs. It uploads at most two
short-lived publicly readable **metadata-only** artifacts (file SHA256
inventory and CPU package versions, retention 3 days). It includes a
separate bounded CPU-only PyTorch/Docling 2.146.0 dependency feasibility
job; this is **not** a final Docker image or validated CPU/RAM runtime.

**Approval boundary:** The operator has authorized this one-shot external
download/CPU wheel feasibility run, NOT private delivery of weights, a new
VPS container, offline Staging model mount, Database Writer, PR merge or
Production. A failed remote download/build results in a documented HOLD,
never a fallback to an unpinned model revision.

## 9. Actual one-shot off-VPS evidence — 2026-11-05

**Source:** [model supply workflow run #41873845270](https://github.com/KeiLee123/ai-knowledge/actions/runs/41873845270),
commit `77f05ec9ef216db795b9a3c3b9ddcc4e3b3011fc`, both jobs **SUCCESS**.
The matching [existing Validation #41873862969](https://github.com/KeiLee123/ai-knowledge/actions/runs/41873862969)
also completed SUCCESS on that exact SHA.

The ephemeral `model-byte-inventory` job used immutable `snapshot_download()`
revisions and verified each completed local file byte-for-byte by SHA256.
It saved **only** the public file inventory as a short-lived GitHub Action
artifact (`phase-b-model-sha256-only`, artifact ID `13346166019`).
The model weights themselves were not uploaded, copied to the VPS,
transferred to private storage, or retained after the Runner completed.

| Repo | Resolved full commit | Hugging Face card license metadata |
| --- | --- | --- |
| `docling-project/docling-layout-heron` | `8f39ad3c0b4c58e9c2d2c84a38465abf757272d8` | `apache-2.0` |
| `docling-project/docling-layout-heron-onnx` | `40bde044036bb181c130ddf6c51792187268748f` | `apache-2.0` |
| `docling-project/docling-models` | `fc0f2d45e2218ea24bce5045f58a389aed16dc23` | `cdla-permissive-2.0` |

**Candidate model inventory:** 20 regular files, 701,224,343 bytes
(approximately 668.7 MiB), canonical model bundle SHA256:

`ddf0c219b5586defee118e03c6a8b6c2716d0117c1b6b51763f1601e90351ead`

This digest includes all model directory bytes and a **candidate**
`model-version.txt`. It identifies the completed temporary download,
**not** a shipping bundle approved for Production/Staging. Any future copied
bundle MUST be re-hashed after transfer; changing its version marker changes
the digest. Model card license metadata does not replace legal attribution
or redistribution approval.

The `cpu-package-feasibility` job installed on Linux x86_64/Python 3.12.15:
`torch==2.9.1+cpu`, `torchvision==0.24.1+cpu`, `docling==2.146.0`,
`docling-core==2.106.0`, `docling-ibm-models==4.0.4`,
`docling-parse==7.24.2`, `transformers==5.22.1`,
`celery==5.6.3`. `pip check` PASS; `torch.version.cuda is None`,
`torch.cuda.is_available() is False`. CPU metadata artifact:
`phase-b-cpu-package-versions-only` (ID `13345542590`).
No actual Docker image was built or measured, no model inference happened,
and no APP149 PDF was present in these jobs.

**Next release HOLDS:** independently approved private model delivery and
post-transfer hash reconciliation, reproducible CPU-only Docker build/image
size/digest, isolated Staging APP149 Docling runtime/time/peak RAM and page
provenance, user Private Beta, PostgreSQL auth and verified backup restore
for any future DB-connected Writer. The one-shot workflow is feature-branch
only and must not be promoted/merged to long-lived branches as an ongoing
automatic downloader without explicit review.
