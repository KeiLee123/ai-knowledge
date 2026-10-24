# Canonical Text Production Promotion v1

Status: ARCHITECTURE DEFINED / NOT IMPLEMENTED

## Goal

Promote a canonical text document that has already passed the frozen Staging ingestion milestone into the Production Knowledge DB without weakening the Production / Staging boundary.

This is a release workflow, not a second source-ingestion workflow.

## Source of truth

Production promotion must rebuild from the same authoritative inputs instead of copying mutable Staging database rows.

```text
GitHub main
  -> code / release contract

Business Google Drive Current
  -> canonical document bytes

approved source-monitor baseline
  -> canonical SHA-256 approval fingerprint

Staging milestone evidence
  -> proof that this exact checksum and routing profile were validated
```

The Staging DB is not a Production data source.

## Why not copy Staging rows

Do not copy `documents`, `chunks`, or `embeddings` directly from the Staging DB into Production.

Reasons:

- Staging is disposable validation state.
- Production should be reproducible from canonical source bytes.
- direct DB copying couples two environments;
- copied row IDs are environment-specific;
- the Production transaction must be independently validated;
- Production rollback must be keyed by the canonical checksum, not Staging IDs.

## Architecture

```text
GitHub main
        |
        v
Production Promotion Guard
branch = main
target = fixed Production DB
Staging DB explicitly forbidden
        |
        v
Google Drive Current
        |
        v
canonical SHA-256 verification
        |
        v
frozen route contract
legacy-v1
        |
        v
deterministic Phase A extraction
        |
        v
native-text chunk rebuild
        |
        v
local embedding rebuild
multilingual-e5-small / 384
        |
        v
Production DB contract check
duplicate checksum check
        |
        v
prepare-only transaction inspection
        |
        v
explicit Production write confirmation
        |
        v
single atomic DB transaction
        |
        v
read-only Production integrity validation
        |
        v
read-only Production semantic retrieval validation
        |
        v
release accepted
```

## Environment contract

Production Promotion v1 must enforce all of the following:

```text
Git branch = main

Production DB =
ai-knowledge-db-jiyckdrlappwgimwebnzxwmr

Staging DB =
jason-os-knowledge-db-staging

Production DB != Staging DB
```

A Production promotion script must never accept an arbitrary DB container from the command line.

The target should be a fixed constant owned by the Production guard.

## Required inputs

For a source such as `BD_PNAP_APP145`, the release gate must resolve from Git-controlled configuration:

- source ID;
- canonical Drive object;
- canonical source URL;
- approved SHA-256 baseline;
- title;
- domain;
- topic;
- document type;
- authority;
- jurisdiction;
- language;
- required route;
- frozen ingestion contract version.

The canonical file must be downloaded fresh from `Current/` for each prepare or write attempt.

## Promotion eligibility

A document is eligible only when all conditions pass:

1. canonical source exists in Google Drive `Current/`;
2. downloaded SHA-256 equals the approved baseline;
3. source is enabled in the Git registry;
4. the frozen text-ingestion contract is marked verified;
5. deterministic full-document routing still returns `legacy-v1`;
6. Production DB schema contract passes;
7. local embedding model contract is `multilingual-e5-small`, 384 dimensions;
8. checksum does not already exist in Production;
9. Production guard confirms branch and DB target;
10. Production write confirmation is explicit.

Any mismatch stops the promotion before DB mutation.

## Modes

### 1. Verify

Read-only.

Checks:

- branch;
- DB target;
- canonical checksum;
- route;
- Production DB schema;
- duplicate checksum.

No embeddings need to be persisted and no DB writes occur.

Expected status:

```text
STATUS: PRODUCTION_PROMOTION_VERIFIED
```

### 2. Prepare

Read-only with full release construction.

Performs:

- deterministic extraction;
- text chunk rebuild;
- all local embeddings;
- full Production SQL transaction generation;
- transaction structural inspection;
- duplicate check immediately before completion.

The SQL is not executed.

Expected status:

```text
STATUS: READY_FOR_PRODUCTION_TEXT_WRITE
Database writes performed: False
```

### 3. Write

Requires an explicit flag such as:

```text
--write
--confirm-production-write
```

The write must:

- re-run the Production guard;
- re-run duplicate prevention;
- execute one atomic transaction;
- stop on any SQL error.

Expected success:

```text
STATUS: INGESTED_TEXT_TO_PRODUCTION
```

## Production metadata contract

Production should preserve the validated semantic meaning of the frozen Staging contract while recording the Production release separately.

Document metadata should include at minimum:

```text
ingestion_version = canonical-text-ingestion-v1
release_gate = canonical-text-production-promotion-v1
multimodal = false
routing_profile = legacy-v1
canonical_source = Current/...
canonical_sha256 = ...
```

Chunk metadata should retain:

```text
evidence_origin = native_text
evidence_tier = primary
retrieval_role = text-primary
multimodal = false
```

Production does not need to reuse Staging row IDs.

## Duplicate policy

Canonical checksum is the idempotency key.

If Production already contains the checksum:

```text
promotion = refused
no overwrite
no second document
no second chunk set
```

A future updated official document must have a new checksum and must first pass the source-change, canonical-promotion, Staging ingestion, and Staging milestone validation lifecycle again.

## Transaction policy

The Production insert must remain atomic:

```text
BEGIN
  insert document
  insert N chunks
  insert N embeddings
COMMIT
```

Any failure before COMMIT must leave no partial Production document.

## Pre-write recovery checkpoint

Before the first Production write attempt, capture a read-only recovery checkpoint containing:

- target checksum;
- current Production document count for that checksum;
- current Production chunk count for that checksum;
- current Production embedding count for that checksum;
- Production DB container identity;
- Git commit;
- canonical source path;
- canonical SHA-256;
- planned chunk count;
- planned embedding count.

For the first promotion, expected pre-write counts are all zero.

This checkpoint is evidence, not a backup of the entire database.

## Rollback / recovery

Two failure classes are different.

### Transaction failure before COMMIT

No rollback procedure is needed beyond PostgreSQL transaction rollback because the write is atomic.

### Post-COMMIT validation failure

Do not silently patch rows.

A separate checksum-locked recovery command must be available before Production write is enabled.

Recovery must:

1. require `main`;
2. lock to the Production DB;
3. require the exact canonical checksum;
4. show the document/chunk/embedding rows that would be removed;
5. require explicit recovery confirmation;
6. delete only the promoted document and its dependent rows for that checksum;
7. verify zero remaining rows for that checksum;
8. never delete any unrelated Production data.

Production write implementation is not considered ready until this recovery path has regression coverage.

## Post-write validation

After COMMIT, run a separate read-only Production validator.

It must verify:

```text
document_count = 1
chunk_count = expected
embedding_count = expected
native_text_chunks = expected
text_primary_chunks = expected
embedding_dimensions = 384
checksum = canonical baseline
routing_profile = legacy-v1
multimodal = false
```

It must also run at least two semantic retrieval queries against that checksum.

The release is accepted only when both integrity and semantic validation pass.

## Frozen-layer rule

Production Promotion v1 must not modify the frozen Canonical Text Ingestion v1 behavior to make Production easier.

Shared lower-level helpers may be reused only when their behavior remains covered by regression tests.

Do not modify these frozen semantics without a new Staging baseline:

- canonical checksum verification;
- `legacy-v1` route requirement;
- chunking contract;
- native-text evidence role;
- embedding model/dimensions;
- duplicate-by-checksum semantics.

## MVP implementation modules

Keep implementation small and replaceable.

Recommended modules:

```text
production_promotion_guard_v1.py
    fixed main-branch + Production DB guard

promote_canonical_text_production_v1.py
    verify / prepare / write release gate

validate_canonical_text_production_v1.py
    read-only post-write integrity + retrieval validator

recover_canonical_text_production_v1.py
    checksum-locked post-COMMIT recovery

test_production_promotion_guard_v1.py
test_promote_canonical_text_production_v1.py
test_validate_canonical_text_production_v1.py
test_recover_canonical_text_production_v1.py
```

Do not add a service, queue, scheduler, API, or dashboard for v1.

## First Production candidate

The first candidate remains:

```text
source_id = BD_PNAP_APP145
canonical source = Current/APP/APP145.pdf
canonical SHA-256 =
dc3262cc55c5fd79d29f337fd811cdd871543f59d795972d9f30f558e313127c
required route = legacy-v1
validated Staging chunks = 8
validated Staging embeddings = 8
```

The Staging counts are acceptance evidence, not rows to copy.

## Implementation order

```text
P1  Production guard + tests
P2  verify/prepare promotion path + tests
P3  recovery path + tests
P4  Production post-write validator + tests
P5  full GitHub CI
P6  live Production verify
P7  live Production prepare
P8  explicit Production write
P9  post-write integrity + semantic validation
P10 freeze Production Promotion v1
```

No Production write should occur before P1-P7 pass.
