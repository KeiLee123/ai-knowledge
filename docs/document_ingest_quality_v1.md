# Document Ingestion Quality & Coverage v1

Status: **Draft PR #88 / Staging-only**. Source: Google Drive first, then GitHub. This module does not change the existing Document v2 Extractor, Router or Chunk Builder.

## Scope

The real Concrete Repair Sheet1 PDF has **298 physical pages** (observed via read-only PyMuPDF preflight), size **1,016,489 bytes**, and local SHA256 `6a506fb13e4c8f294268cdcb64aa89e4133dc26c63769b4b95b1a6b281c3c7ac`. These are observed operator values, not independent proof of official/legal source identity.

`audit_document_ingest_quality_v1.py` uses existing Document v2 `build_manifest(selected_pages=...)` to process **25 pages per batch**. The preflight limits document total to 500 pages and refuses mismatched input size/hash and invalid PDFs. Every batch carries original physical page IDs and the same source SHA. It requires complete, non-overlapping coverage of every page before returning a document-level report.

For each batch, reuse `route_document_v2.assess_manifest(allow_partial=True)` and `build_multimodal_chunks_v2.build_chunks` to inspect table rows, columns, page/bbox and chunk provenance. The aggregator counts pages, tables and chunks, tracks any OCR/table/route risks by page or batch, and auto-holds uncertainty. Zero tables in one batch is not treated as a full-document failure; zero tables across the whole document is. Internal mechanical checks never establish source cell/numeric/unit/semantic accuracy.

No PDF excerpts or cell values are printed. No model or OCR calls, DB access, Drive modification, Production write, Anki write or mandatory human verification. The report is read-only evidence for deciding where targeted fixes are needed. The source PDF remains in an ephemeral local directory and is not published to GitHub.

## Development and release boundary

- Existing single-manifest audit ceiling: 150 pages, preserved.
- New batched full-document ceiling: 500 pages, 25 pages per batch (not an unbounded extension).
- A 298-page PDF must produce 12 batches; the last covers pages 276–298. Gaps and duplicates are forbidden.
- Synthetic offline tests and full CI precede real VPS Staging acceptance.
- Staging acceptance of structural diagnostics is not acceptance of semantic answer, OCR, version/applicability, Anki, or Production ingest.
- Keep PR #88 Draft and unmerged until results inspected. Production and frozen modules unchanged.


## Real Concrete Repair Sheet1 PDF — observed VPS Staging audit

At commit `1bf1dd3d435d4f57062d677b010e99ea94457f5e`, existing SHA-pinned source passed read-only audit: 298/298 physical pages processed, 12 batches, 150 native-text pages (1–150), 148 no-native-text pages (151–298). There were 148 detected tables, 148 structured table chunks, and 148/148 real Canonical Text Writer metadata previews matched (0 mismatches). The batch-level Router selected `legacy-v1` 12/12 times; this route *does not itself prove data loss*, because the canonical text Staging writer reuses the Structured Table chunk builder. Database round-trip, numeric cell semantics and OCR accuracy remain NOT MEASURED.

All 148 no-native-text pages were `extractor_blank_candidate`; image-only, vector/graphic and unclassified counts were zero. These are **Extractor signals** and not a raster-rendered proof of white or semantically empty pages. Preserve their source physical page numbers.

## Bounded, independent raster probe — separate evidence gate

`verify_pdf_blank_pages_v1.py` renders only explicitly requested PDF pages in memory at 72 DPI grayscale with annotations enabled. For every pixel, it counts any byte darker than pure white. It never saves PNGs or extracted text, and writes only metadata JSON at the explicit local `--report-json` path. A non-white pixel triggers `AUTO_HOLD_RENDERED_NONWHITE`. If all sampled pixels are white, it returns `RENDER_NO_NONWHITE_DETECTED_LIMITED` — **not** a proof of absence of hidden/occluded PDF objects, very fine high-resolution details, invisible or white-on-white elements, nor a guarantee of semantic source completeness. To claim an entire page range was rendered, page count must match the required count, with no gaps; this does not claim the whole PDF was rendered if only a subrange was supplied.

Safety guards: require exact observed input file SHA256/size, expected physical 298 page count, 1–150 requested render pages, total maximum 500, and per-page size ceiling of two million rendered pixels; no AI, OCR, DB/Drive writes or network access. Use a temporary local folder for both PDF and report. Avoid human review as a mandatory gate. This independent probe is additive and does not modify Frozen v1.3 or any existing Extractor, Router or Writer.

Next real Staging gate: `--expected-total-pages 298 --first-page 151 --last-page 298 --expected-sha256 6a506fb13e4c8f294268cdcb64aa89e4133dc26c63769b4b95b1a6b281c3c7ac --expected-size 1016489`. Independently check all 148 blank-candidate pages. No real render outcome has been observed yet. If nonwhite pages occur, keep them on auto-hold and triage only those pages. Even if all are white at 72 DPI, do not treat that as a semantic correctness or indexing acceptance.

## 2026-11-02 — VPS mechanical gate and pre-writer safety handoff

The pinned 298-page PDF was run by the operator on an isolated VPS worktree at commit `29037512f6c8c8e358a837892fe38cb95a026a47`. Result: `STAGING_READONLY_MECHANICAL_EVIDENCE_MATCHED_AUTO_HOLD`, `EVIDENCE_MATCHED_LIMITED`, zero reconciliation reason codes, 148/148 candidate pages with nonwhite raster pixels. Four metadata JSON artifacts were generated in the private temporary evidence directory. This **supersedes** the earlier sentence above saying the real render had not yet occurred; it does not prove page semantic blankness, table numeric accuracy or database round-trip.

A small, standalone `pre_writer_document_quality_gate_v1.py` now specifies a fail-closed, source-scoped hold. The proposed source profile is `document_quality_gate: {enabled: true}`. When required, missing evidence, malformed evidence and even matched `AUTO_HOLD_UNVERIFIED` evidence must refuse writes. `test_pre_writer_document_quality_gate_v1.py` runs as part of GitHub Validation. There is deliberately **no** approved status that could turn matched mechanical evidence into writer authorization.

**Integration status: NOT ACTIVE IN THE CONTROLLER.** An attempted edit of `process_official_source_staging_v1.py` was blocked by connected-tool safety validation, and the existing source registry was not modified. Future authorized integration must call the gate after loading the source profile but **before** `resolve_baseline(execute=True)`, because this may write a baseline before the subsequent Staging Drive, canonical promotion and database writer steps. The opt-in policy cannot have a command-line bypass; existing ungated APP145/APP146/APP149 flows must retain their behavior. Direct invocations of individual writer scripts remain outside this controller-level guard and need independent consideration. Do not claim the pipeline is protected end-to-end until that integration and both negative and historical-source regressions have passed.

PR #88 remains Draft and unmerged. No Staging/Production DB write or Frozen v1.3 change is authorized by this work.

## 2026-11-02 — Official Source Controller pre-writer gate integrated in PR #88

The controller integration is now present in this **unmerged Draft PR**, superseding the prior "NOT ACTIVE IN THE CONTROLLER" statement for branch contents. In `process_official_source_staging_v1.py`, `--execute` calls `enforce_pre_writer_quality_gate(source, --document-quality-report-json)` immediately after `load_source()`, before `resolve_baseline(execute=True)`. A source configured with `document_quality_gate: {enabled: true}` cannot bypass the hold by omitting the report. Missing, malformed, explicitly matched-but-held or forged write-permission reports are refused. The policy does not implement any "allow" outcome.

The regression `test_official_source_quality_gate_controller_v1.py` exercises the real `main()` entrypoint with mocked I/O and asserts that neither baseline initialization nor Drive stage/canonical operations nor text/multimodal writer dispatch are called on AUTO_HOLD. The existing historical ungated source route remains reachable under its mocked baseline test. The validation workflow runs this new test as well as the existing suite.

**Environment limitation:** This code is present in PR #88, not merged to GitHub staging and not deployed in the active VPS staging checkout. Existing APP145/APP146/APP149 source registry profiles were not changed to opt in; direct independent writer scripts are outside this controller guard. Therefore no claim of an end-to-end global write barrier or real database protection can yet be made. A controlled staging activation, runtime verification and separate DB round-trip gate remain future tasks. Production and Frozen v1.3 are untouched.

## 2026-11-02 — Two direct writer entrypoints: source policy and fallback AUTO_HOLD

The PR #88 Draft branch now includes opt-in Quality Gate controls on the two previously identified direct writer wrappers, with synthetic tests added to the existing Validation workflow.

- `ingest_canonical_text_staging_v1.py --write`: reads the checked-in `source_registry_v1.yaml` before `load_expected_baseline`, remote download, embedding computation or SQL execution. When the registry contains any enabled document quality policy, direct writes reject `--registry` overrides and unknown registry source IDs. The selected source is checked using the shared `enforce_pre_writer_quality_gate`. An opted-in source with a missing, malformed, falsely approved or matched-but-held report remains blocked. An explicit report on a legacy source is also checked, not silently ignored.
- `run_multimodal_canary_v2.py --write`: unlike the text wrapper, the generic CLI accepts an arbitrary local PDF, and `--source-url` alone is not a trustworthy source identity. For MVP, any `document_quality_gate.enabled: true` in the checked-in Registry causes *all direct multimodal writes through this wrapper* to fail closed, including otherwise legacy-source direct invocations. Its `--verify-only` / non-write paths stay available. This is deliberately conservative and must be revisited with reliable source identity binding before registering a production-relevant opted-in source.
- Sources not opted in retain historical behavior so long as no source in the active Registry has opted in. The current checked-in APP145, APP146 and APP149 profiles were not changed. No live source opt-in was activated.

`test_direct_writer_quality_gate_v1.py` uses mocked runtime, registry, baseline, remote downloader, model embeddings and SQL execution to demonstrate hold-before-side-effect on opted-in text sources, forged reports, registry overrides, and anonymous multimodal writes. It also exercises historical legacy behavior and multimodal verify-only. The existing GitHub Validation invokes this synthetic test.

**Not a global enforcement guarantee:** further lower-level entrypoints including `orchestrate_document_v2.py` and `ingest_manifest_v2.py` retain their own write flags and confirmation guards. They are not automatically covered by the Controller or the two new wrapper gates. Their use for opted-in sources must be separately governed before claiming end-to-end ingestion safety. Do not treat passing CI as authorizing database writes, Staging deploy, PR merge or Frozen Production changes.


## 2026-11-02 — Raw v2 Writer Safety Boundary v1 (feature branch, not activated)

This follow-up to merged PR #88 is restricted to the two generic v2 `--write` CLIs: `orchestrate_document_v2.py` and `ingest_manifest_v2.py`. Both accept user-supplied local paths/chunk manifests, source URLs and `--synthetic`; none of these inputs is a trusted identity for an opted-in Registry source. The manifest CLI can write straight to a selected DB container, bypassing both the official controller and the multimodal canary wrapper.

**MVP fail-closed design:** both direct write entrypoints load only their checked-in sibling `source_registry_v1.yaml` and call the shared `enforce_unattributed_raw_v2_write` before file/workdir processing, OCR, embedding, remote operations or DB I/O. If any source enables `document_quality_gate.enabled: true`, refuse *all* unattributed raw v2 writes with `QUALITY_GATE_UNATTRIBUTABLE_RAW_V2_WRITE_AUTO_HOLD`, regardless of `--synthetic` or `--confirm-live-write`. Malformed/missing Registry fails closed; no CLI source or policy override is accepted. Without any enabled policy, current historical behavior remains, and validation/prepare paths never invoke this new guard. This is a temporary conservative restriction; a future trusted source-binding contract is needed before safe opted-in raw writes.

The offline `test_raw_v2_writer_quality_gate_v1.py` checks both actual CLI `main()` functions under mock patches for enabled/legacy/non-write cases, synthetic and live confirmation flags, invalid policy and Registry loading failure. It asserts no source processing, OCR, DB read, embeddings or transaction is reached on hold. The standard Validation workflow runs this test. This does not execute an actual ingestion, DB query, Drive operation or external call.

**Limitations and release boundaries:** no Source Registry opt-in, Production, Frozen v1.3, schema, Scheduler/Service or VPS changes are included. The guard covers these Python CLI entrypoints; it does not turn a callable `execute_transaction` utility, shell-level direct docker/psql command or all historical writers into a global DB authorization system. Nor does it authorize/validate semantic correctness of scanned pages, an AUTO_HOLD PDF, real Staging DB write/readback or Production. This feature branch requires exact-head CI and separate controlled VPS Staging synthetic review before a GitHub Staging code merge; activation and actual database tests are distinct authorization gates.


## 2026-11-02 — Staging DB Target Lock v1 (feature branch; no DB operation)

**Risk identified from actual VPS read-only inspection:** `jason-os-knowledge-db-staging` is running, `network=none`, labels `environment=staging` and `purpose=knowledge-canary`. However `ingest_manifest_v2.py` had a Production database container as its implicit default. PR90 quality gating only holds a raw write once a Registry quality source opts in; no source is opted in today.

**Smallest reusable fix:** retain the existing `run_multimodal_canary_v2.verify_runtime` guard; use it via `staging_db_target_guard_v1.enforce_staging_write_target` in the two raw v2 `--write` CLI entrypoints and again immediately inside `ingest_manifest_v2.execute_transaction`. A raw DB write must explicitly pass `--db-container jason-os-knowledge-db-staging`; the target must match that exact name, the Git checkout branch must be `staging`, Docker labels must identify `staging/knowledge-canary`, network mode must be `none`, no ports published, and the container must be running and healthy. Any violation or failed inspection stops BEFORE the DB transaction. No caller-provided `--synthetic` or `--confirm-live-write` can override this check.

`DEFAULT_DB_CONTAINER` is now empty, not Production: any `--write`, `--prepare-write`, `--check-db`, and orchestrator `--prepare` need an explicit `--db-container` target. Read-only/route-only operations that never access the DB remain usable without it. Historical canary wrappers already pass an explicit Staging target and require no interface change. Read-only operations with an explicit Production target remain outside the live Staging write acceptance scope; this lock is a **write boundary**, not a global data-access policy.

The new offline regression `test_staging_db_target_lock_v1.py` exercises both real CLI `main()` entrypoints, the direct `execute_transaction` function, disabled/missing/default/Production/arbitrary targets, explicit staging target, and simulated branch/health failure with mocks. The existing PR90 raw-v2 quality test was adapted to explicitly supply a Staging target and mock the runtime check. Standard Validation runs both tests. The offline suite never contacts Docker/DB or executes SQL, OCR, or file ingestion.

**Release gates:** This change remains in a separate feature PR until exact-head CI and independent isolated VPS tests. No Source Registry opt-in, main/Production/Frozen changes, schema migration, real data write/readback, or original document changes. After code-only staging integration, do a separate read-only runtime check including Docker `State.Health.Status` and DB schema identity; only then design and separately authorize a single synthetic Staging DB transaction with readback and safe cleanup. Guarding this Python code does not stop privileged shell `docker exec` or direct DB clients, which require operational access controls.


## 2026-11-03 — Staging least-privilege Raw v2 Writer v1 (code-only proposal)

**MVP architecture:** Keep Coolify Root Access Terminal and the existing PostgreSQL administrator account for operator administration. The automated Raw v2 writer must instead use a fixed, separate Staging-only login `ai_knowledge_writer_staging`. A fixed Staging Docker container guard from PR #91 remains mandatory. No new service, broker, database or alternate Source of Truth.

**Fail-closed code contract:** `orchestrate_document_v2.py --write` and `ingest_manifest_v2.py --write` require explicit `--db-container jason-os-knowledge-db-staging --db-role ai_knowledge_writer_staging`. The existing canary command builders propagate the fixed role automatically. Before expensive OCR/embedding or DB work, the code checks Staging identity and performs a bounded read-only `pg_roles` query **as the requested role**: the actual connected login must match, must be able to log in, must be in the `ai_knowledge` database, must not hold SUPERUSER/CREATEDB/CREATEROLE/REPLICATION/BYPASSRLS, and must not be a member of any privileged role. The lowest-level `execute_transaction` repeats Staging and role checks immediately before SQL; its `psql -U` selects the fixed role rather than the previous admin login. Duplicate checks and schema checks during `--write` also use that writer role. These Python guards cannot stop a privileged Root shell or arbitrary SQL clients.

**Legacy compatibility / explicit limits:** Read-only and `--prepare` paths continue to use the existing administrative read identity until a separately scoped migration. The specific wrappers `run_multimodal_canary_v2.py` and `write_prepared_canary_v2.py` now pass the fixed Writer Role for write commands; no canary is automatically run. No changes to Production, main, Frozen Retrieval v1.3, Source Registry Quality Gate opt-in, DB schema, service/timers or Docker configuration. This feature is CODE ONLY: the new role does not yet exist; a real write should therefore fail closed.

**Future DB role grant gate (not executed):** After read-only inspection of existing grants, sequences, defaults and triggers, separately approve a Staging-only login with NO SUPERUSER/CREATEDB/CREATEROLE/REPLICATION/BYPASSRLS and no inherited privileged memberships. Proposed initial table access for the raw v2 pipeline: SELECT on required schema/catalog plus `documents`/`chunks`/`embeddings`, INSERT on those three tables, and USAGE (plus necessary SELECT) on precisely their ID sequences; avoid UPDATE, DELETE, CREATE SCHEMA, or privileges on unrelated tables unless separately justified. Check that connected role is not the admin user and that all read/preflight calls use the intended role. No credentials are to be committed or placed in this document.

**Acceptance gates:** New offline role guard/CLI/low-level SQL/Canary tests plus PR91 and Quality Gate regressions must pass exact PR-head GitHub Validation, then isolated VPS tests before any code-only merge. A separate explicit approval is required to create/grant the role, and yet another separate gate for a single bounded Staging synthetic INSERT → readback → safe cleanup or transactional rollback. Since the actual generated SQL includes BEGIN/COMMIT, do not assume wrapping an existing Writer CLI with an outer transaction will roll it back. Production promotion and automatic scheduled writes remain prohibited.
