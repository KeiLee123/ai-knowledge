# Canonical Text Ingestion v1

Status: VERIFIED / FROZEN\n\nFrozen baseline: staging commit `c1ef9eb`\n\nValidated source: `BD_PNAP_APP145`\n\nValidated canonical SHA-256: `dc3262cc55c5fd79d29f337fd811cdd871543f59d795972d9f30f558e313127c`

## Purpose

Canonical Text Ingestion v1 is the Staging-only ingestion path for canonical documents that the deterministic document router classifies as `legacy-v1`.

It exists because the legacy Production ingester has a hard-coded Production database target and must not be reused directly for Staging validation.

## Architecture

```text
Business Google Drive Current
        |
        v
canonical checksum verification
        |
        v
Phase A deterministic extraction
        |
        v
document router
        |
        +--> multimodal-v2 -> existing multimodal path
        |
        +--> legacy-v1
                |
                v
        Canonical Text Ingestion v1
        native text only
                |
                v
        deterministic text chunks
                |
                v
        local embeddings
                |
                v
        isolated Staging Knowledge DB
                |
                v
        read-only retrieval validation
```

## Boundaries

This module does not modify `ingest_document.py`.

The legacy Production ingester remains untouched.

The new module reuses verified shared primitives for:

- canonical Drive download and checksum verification;
- Phase A extraction;
- deterministic routing;
- native-text chunk construction;
- local embedding generation;
- database contract validation;
- transaction structural validation;
- atomic database execution.

It supplies its own text-only metadata and transaction builder.

## Required route

The module only accepts a full-document routing decision of:

```text
recommended_pipeline = legacy-v1
eligible_for_v2 = false
production_decision_valid = true
```

If a future revision of the same document becomes multimodal, the text-only gate refuses it and the document must return to the multimodal path.

## Text metadata contract

Document metadata records:

```text
ingestion_version = canonical-text-ingestion-v1
multimodal = false
routing_profile = legacy-v1
canonical_source = Current/...
```

Chunk metadata records:

```text
evidence_origin = native_text
retrieval_role = text-primary
multimodal = false
```

The database `source_type` is:

```text
canonical-drive-text
```

This prevents a text-only canonical document from being mislabeled as multimodal.

## Safety gates

Before embedding or database mutation, the module verifies:

1. Git branch is `staging`;
2. the isolated Staging DB guard passes;
3. the canonical source is under `Current/`;
4. the Drive remote is exactly `gdrive-bd-write:`;
5. canonical bytes match the approved source-monitor baseline;
6. the deterministic router selects `legacy-v1`;
7. the DB target is exactly `jason-os-knowledge-db-staging`;
8. the DB schema and vector-dimension contract pass;
9. the checksum does not already exist in Staging;
10. Production writes are disabled.

## Prepare mode

```bash
python ingest_canonical_text_staging_v1.py \
  BD_PNAP_APP145 \
  --prepare \
  --workdir /tmp/app145-canonical-text
```

Prepare mode:

- downloads and verifies the canonical PDF;
- extracts native text;
- rechecks the legacy route;
- builds deterministic page-aware text chunks;
- validates the Staging DB contract;
- precomputes all local embeddings;
- builds and structurally inspects the atomic transaction;
- does not execute the SQL transaction.

Expected terminal status:

```text
STATUS: READY_FOR_STAGING_TEXT_WRITE
Database writes performed: False
```

## Write mode

Write mode requires explicit confirmation:

```bash
python ingest_canonical_text_staging_v1.py \
  BD_PNAP_APP145 \
  --write \
  --confirm-staging-write \
  --workdir /tmp/app145-canonical-text-write
```

It may write only to the isolated Staging Knowledge DB.

Production ingestion remains a separate future release gate.

## MVP principle

```text
Router chooses the cheapest correct path.

Text document
    -> text ingestion

Multimodal document
    -> multimodal ingestion
```

Do not force every document through OCR or Vision.


## Freeze evidence

The Staging milestone was live-validated after an actual isolated Staging DB write and a separate read-only integrity/retrieval validation.

Validated invariants:

```text
document_count = 1
chunk_count = 8
embedding_count = 8
native_text_chunks = 8
text_primary_chunks = 8
embedding_dimensions = 384
routing_profile = legacy-v1
multimodal = false
integrity_ok = true
semantic_ok = true
production_write = false
```

The semantic validation returned relevant APP-145 fire-safety content for multiple queries.

The final live validator reported:

```text
STATUS: CANONICAL_TEXT_STAGING_MILESTONE_VERIFIED
```

## Frozen-layer policy

The following v1 contract is now frozen:

- canonical checksum verification before ingestion;
- full-document deterministic route gate;
- `legacy-v1` requirement for this text-only path;
- Staging DB isolation;
- native-text-only chunk evidence;
- `text-primary` retrieval role;
- `multimodal = false` metadata;
- local `multilingual-e5-small` 384-dimensional embedding contract;
- checksum duplicate prevention;
- atomic document/chunk/embedding transaction;
- read-only post-write integrity and semantic retrieval validation.

Do not modify the frozen contract without regression coverage first.

Any future change must:

1. be developed in `staging`;
2. add or update regression tests before changing behavior;
3. preserve Production / Staging isolation;
4. re-run the live Staging milestone validator;
5. establish a new verified baseline before the changed layer is treated as frozen again.

## Production boundary after freeze

This freeze does not authorize a Production database write.

```text
Staging verified/frozen
        !=
Production promoted
```

Production promotion must be implemented as a separate release gate with its own Production guard, dry-run/prepare mode, explicit write confirmation, duplicate prevention, post-write retrieval validation, and rollback/recovery procedure.
