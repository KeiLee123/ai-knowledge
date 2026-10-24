# Canonical Ingestion v1

Status: STAGING MVP / IMPLEMENTED / LIVE VALIDATION PENDING

## Purpose

Canonical Ingestion v1 is the explicit gate between an accepted canonical document in Business Google Drive `Current` and the isolated Staging Knowledge DB.

It answers one question only:

> May this canonical document be prepared for, or written into, the Staging Knowledge DB?

It does not detect upstream changes, promote files into `Current`, update source baselines, or modify Production.

## Architecture

```text
Official publisher
      |
      v
Source Monitor + approved baseline
      |
      v
PNAP Staging Writer v1
      |
      v
Canonical Promotion v1
      |
      v
Business Google Drive
Current/APP/APP145.pdf
      |
      v
Canonical Ingestion v1
checksum + environment + DB guard
      |
      v
existing multimodal v2 canary pipeline
      |
      v
isolated Staging Knowledge DB
      |
      v
read-only retrieval validation
      |
      v
separate future Production ingestion gate
```

The existing multimodal v2 orchestrator and canary guard remain unchanged. Canonical Ingestion v1 is a separate wrapper around those verified components.

## Source of truth

- GitHub is the Source of Truth for code and ingestion configuration.
- Business Google Drive `Current` is the Source of Truth for the accepted document bytes.
- The source-monitor baseline is the approval fingerprint used to verify those bytes.
- The Staging Knowledge DB is disposable validation state, not the canonical document store.

## MVP configuration

The source entry in `source_registry_v1.yaml` declares a `canonical_ingestion` block.

For APP-145:

```text
environment = staging
remote = gdrive-bd-write:
source = Current/APP/APP145.pdf
db_container = jason-os-knowledge-db-staging
pipeline = multimodal-v2
allow_production_write = false
```

## Gates

Before any OCR, vision, embedding, or DB write, the wrapper verifies:

1. Git branch is `staging`;
2. the isolated Staging DB guard passes;
3. the source is enabled in the Git-controlled registry;
4. the configured remote is exactly `gdrive-bd-write:`;
5. the configured source is a PDF under `Current/`;
6. the DB target is exactly `jason-os-knowledge-db-staging`;
7. the Production DB container is not selected;
8. the pipeline is `multimodal-v2`;
9. Production writes are disabled;
10. the canonical Drive object SHA-256 matches the approved runtime baseline;
11. byte size matches the baseline when the baseline includes content length.

If any gate fails, the wrapper stops before invoking the multimodal pipeline.

## Execution modes

Default mode is read-only validation:

```bash
python ingest_canonical_staging_v1.py BD_PNAP_APP145
```

This downloads the canonical Current object to a temporary local file, verifies it against the baseline, and stops with `STATUS: READY_TO_PREPARE`. It performs no OCR, vision, embeddings, or DB writes.

Prepare mode:

```bash
python ingest_canonical_staging_v1.py BD_PNAP_APP145 --prepare
```

This invokes the existing multimodal v2 Staging canary in prepare-only mode. It does not write the Staging DB.

Write mode:

```bash
python ingest_canonical_staging_v1.py \
  BD_PNAP_APP145 \
  --write \
  --confirm-staging-write
```

This is the only mode allowed to request a Staging DB write. The existing canary guard still independently locks the target to the isolated Staging DB.

## Forbidden behavior

Canonical Ingestion v1 must not:

- read from `_Staging_Incoming` as its canonical source;
- select `gdrive:` or `gdrive-out:`;
- select the Production DB;
- modify Canonical Promotion v1;
- update the source-monitor baseline;
- delete or move the canonical Drive document;
- trigger Production ingestion;
- bypass the existing multimodal canary guard;
- silently continue after checksum, Drive, branch, or DB isolation errors.

## Production / Staging boundary

This module is Staging-only.

A successful Staging ingestion means only that the accepted canonical document has been loaded into the isolated Staging Knowledge DB.

It does not mean:

```text
Production Knowledge DB updated
Production deployment approved
source baseline updated
canonical document changed
```

Production ingestion remains a separate later gate.

## Regression coverage

`test_ingest_canonical_staging_v1.py` verifies:

- Current-path enforcement;
- isolated writer remote enforcement;
- Staging environment enforcement;
- fixed Staging DB target;
- Production DB rejection;
- multimodal-v2 pipeline selection;
- Production-write prohibition;
- explicit write confirmation command construction.

The GitHub Actions validation workflow runs this contract test on every push to `staging` and pull request to `main`.

## First live validation sequence

After CI passes, the Staging VPS should run these gates in order:

```text
1. dry-run checksum validation
2. prepare-only multimodal run
3. review generated artifacts / routing
4. explicit Staging DB write
5. read-only retrieval validation by checksum
6. freeze the milestone only after retrieval PASS
```

Do not merge this milestone to `main` before live Staging retrieval validation passes.
