# Official Source Processing Pipeline v1

Status: GITHUB STAGING / CI VERIFIED; VPS LIVE VERIFICATION PENDING

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
Reusable text       Guarded multimodal-v2
Staging ingestion   Staging ingestion
   |                   |
   v                   v
Text semantic       Multimodal semantic
validation          retrieval validation
   \                  /
    \                /
     v              v
READY_FOR_PRODUCTION_REVIEW
```

## Safety boundary

v1 is Staging-only.

- Fixed Staging DB: `jason-os-knowledge-db-staging`
- No Production DB target
- No Production writer
- No Production release registry
- No automatic baseline replacement when document bytes change
- Multimodal DB writes are permitted only through the fixed Staging canary guard and explicit Staging confirmation
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
6. for `multimodal-v2`, reuse the guarded Multimodal v2 canary path locked to the isolated Staging DB;
7. run the route-appropriate read-only semantic validation;
8. emit `READY_FOR_PRODUCTION_REVIEW` only after the Staging document exists and validation passes.

Existing matching Drive objects and an existing matching Staging DB document are verified and reused rather than overwritten.

For either validated route:

```text
STATUS: READY_FOR_PRODUCTION_REVIEW
```

The multimodal close-loop is implemented and CI-verified in GitHub `staging`. Live VPS Staging verification is still pending.

## Source changes

A changed document checksum is not automatically accepted.

```text
SOURCE_CHANGED_REVIEW_REQUIRED
```

A new checksum must go through a controlled review / baseline lifecycle before processing.

An index-page change with unchanged document bytes is reported by the baseline layer but does not alter the approved document checksum.

## Semantic validation profiles

Sources that participate in the automated Staging lifecycle define source-specific semantic validation hints in `source_registry_v1.yaml`:

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
- APP-146: multimodal-v2 due to a genuine diagram page; GitHub `staging` now contains the guarded Staging write + semantic retrieval validation close-loop. VPS live verification remains pending.
- APP-149: legacy-v1; Staging document_id 3; 8 chunks; 8 embeddings; 384 dimensions; semantic retrieval VERIFIED.

## Next milestone

Deploy the consolidated Staging lifecycle to the VPS and live-verify APP-146 without touching Production.

After that, evolve Generic Production Promotion v2 toward profile-based release artifacts rather than creating a candidate-specific or modality-specific Production writer.