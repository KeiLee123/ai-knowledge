# Official Source Processing Pipeline v1

Status: STAGING AUTOMATION LAYER

## Purpose

Official Source Processing Pipeline v1 replaces the manually repeated Staging lifecycle used during APP-145 / APP-146 / APP-149 qualification.

It is a new orchestration layer. It does not modify the frozen extraction, routing, text-ingestion, retrieval, or Production release implementations.

## Architecture

```text
Source Registry
      |
      v
Official source probe / baseline gate
      |
      +-- document changed --> REVIEW REQUIRED
      |
      v
Drive Staging verification
      |
      v
Canonical Current verification
      |
      v
Deterministic router
   /                  \
legacy-v1          multimodal-v2
   |                   |
   v                   v
Reusable text       Explicit handoff
Staging ingestion   (no automatic DB write in v1)
   |
   v
Read-only milestone validation
   |
   v
READY_FOR_PRODUCTION_REVIEW
```

## Safety boundary

v1 is Staging-only.

- Fixed Staging DB: `jason-os-knowledge-db-staging`
- No Production DB target
- No Production writer
- No Production release registry
- No automatic baseline replacement when document bytes change
- No automatic multimodal DB write
- No change to frozen APP-145 Production code

Production approval and Production promotion remain separate milestones.

## Modes

### Plan mode

```bash
python process_official_source_staging_v1.py SOURCE_ID
```

Plan mode performs read-only checks:

- Staging runtime guard
- official source probe
- baseline comparison
- live document SHA / size verification
- deterministic routing
- Drive Staging state check
- Canonical Current state check
- Staging DB duplicate check

It does not write Drive or DB state.

Success:

```text
STATUS: OFFICIAL_SOURCE_PLAN_READY
```

### Execute mode

```bash
python process_official_source_staging_v1.py SOURCE_ID \
  --execute \
  --confirm-staging-processing
```

Execution may:

1. initialize a missing baseline for a newly onboarded source;
2. create the approved Staging Drive object if missing;
3. create the approved Canonical Current object if missing;
4. use the deterministic router;
5. for `legacy-v1`, reuse the frozen canonical text Staging writer;
6. run the read-only canonical text Staging milestone validator.

Existing matching Drive objects and an existing matching Staging DB document are verified and reused rather than overwritten.

For a validated text source:

```text
STATUS: READY_FOR_PRODUCTION_REVIEW
```

For a multimodal source:

```text
STATUS: MULTIMODAL_STAGING_HANDOFF_REQUIRED
```

The v1 automation deliberately stops there until the official-source multimodal lifecycle is operationalized.

## Source changes

A changed document checksum is not automatically accepted.

```text
SOURCE_CHANGED_REVIEW_REQUIRED
```

A new checksum must go through a controlled review / baseline lifecycle before processing.

An index-page change with unchanged document bytes is reported by the baseline layer but does not alter the approved document checksum.

## Semantic validation profiles

Text sources that participate in the automated Staging lifecycle define source-specific semantic validation hints in `source_registry_v1.yaml`:

```yaml
staging_validation:
  query: "..."
  expect_terms:
    - term-a
    - term-b
```

This keeps the generic orchestrator source-independent while preserving meaningful retrieval validation.

## Qualified examples

- APP-145: legacy-v1; Production milestone already VERIFIED / FROZEN.
- APP-146: multimodal-v2 due to a genuine diagram page; retained as a multimodal candidate.
- APP-149: legacy-v1; Staging document_id 3; 8 chunks; 8 embeddings; 384 dimensions; semantic retrieval VERIFIED.

## Next milestone

After v1 Staging automation is live-verified, the next architecture milestone is Generic Production Promotion v2.

That layer should consume reviewed release contracts rather than create a new candidate-specific Python writer for every source.
