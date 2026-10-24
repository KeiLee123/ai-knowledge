# Canonical Promotion v1

Status: VERIFIED + FROZEN / FIRST CANONICAL PROMOTION COMPLETE

## Purpose

Canonical Promotion v1 is a separate release gate between a verified Staging document and the canonical Business Google Drive `Current` tree.

It answers one question only:

> May this already-staged and verified document become the current canonical document?

It does not detect upstream changes, download from the publisher, update the source baseline, ingest into the Knowledge DB, or deploy anything to Production.

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
_Staging_Incoming/APP/APP145.pdf
      |
      v
Canonical Promotion v1
      |
      v
Current/APP/APP145.pdf
      |
      v
separate future ingestion / Production gate
```

The verified PNAP Staging Writer v1 remains frozen. Canonical Promotion must be implemented as a separate module.

## Source of truth

- GitHub is the Source of Truth for promotion code and configuration.
- Business Google Drive is the Source of Truth for durable canonical documents.
- The VPS runtime baseline is approval state used as a fingerprint gate.
- `Current` is the canonical document layer; it is not the Production database.

## MVP contract

The promotion configuration must come from `source_registry_v1.yaml`.

For each promoted source it declares:

- the isolated writable remote;
- the exact Staging source path;
- the exact canonical `Current` destination;
- overwrite policy;
- whether the Staging source is retained;
- whether baseline update is allowed;
- whether ingestion is triggered.

For v1:

```text
remote = gdrive-bd-write:
source = _Staging_Incoming/APP/APP145.pdf
destination = Current/APP/APP145.pdf
allow_overwrite = false
retain_staging_source = true
update_baseline = false
trigger_ingestion = false
```

## Promotion gates

Before any write to `Current`, the module must verify:

1. the configured source is under `_Staging_Incoming/`;
2. the configured destination is under `Current/`;
3. the remote is exactly `gdrive-bd-write:`;
4. the staged source exists;
5. the staged source is a PDF;
6. the staged source byte size matches the approved baseline when baseline size is available;
7. the staged source SHA-256 matches the approved baseline SHA-256;
8. the canonical destination does not already exist;
9. the canonical parent folder already exists;
10. execution is explicitly requested.

If any gate fails, promotion stops before writing `Current`.

## Execute behavior

Dry-run is the default.

An explicit `--execute` may:

1. download the staged Drive object to a temporary VPS file;
2. verify SHA-256 against the approved baseline;
3. upload those verified bytes to the exact registry-approved `Current` destination;
4. read the new canonical object back;
5. verify the round-trip SHA-256;
6. report the result.

The Staging object remains in place.

## Forbidden behavior in v1

Canonical Promotion v1 must not:

- overwrite an existing `Current` document;
- delete or move the Staging source;
- create arbitrary canonical paths;
- use `gdrive:` or `gdrive-out:`;
- fetch the official BD website;
- update or replace the source-monitor baseline;
- write PostgreSQL;
- invoke Knowledge ingestion;
- modify Production;
- silently continue after permission, network, or checksum errors.

## Failure policy

Any error before the canonical upload leaves `Current` unchanged.

If the upload completes but round-trip verification fails, the command must fail loudly and leave the new object in place for manual inspection. v1 deliberately avoids automatic delete/rollback because destructive cleanup is outside this first promotion contract.

## Production / Staging boundary

The module is developed and validated only on the `staging` branch first.

A successful canonical promotion means only that Business Google Drive `Current` contains an accepted canonical document.

It does not mean:

```text
Production ingestion complete
Knowledge DB updated
Production deployment approved
baseline changed
```

Those remain separate later gates.

## MVP principle

```text
Staging proves the bytes.
Promotion accepts the bytes.
Ingestion consumes the accepted bytes.
```

Keep those responsibilities separate.


## Implementation validation

Canonical Promotion v1 is implemented on the `staging` branch as:

```text
promote_pnap_canonical_v1.py
test_promote_pnap_canonical_v1.py
```

GitHub Actions Validation #196 completed successfully. The Canonical Promotion regression test passed together with the existing PNAP Staging Writer, multimodal ingestion, source provenance, retrieval, and spaced-repetition regression checks.

No canonical promotion has been executed yet. `Current/APP` remains unchanged until an explicit Staging dry-run passes and a later `--execute` command is intentionally run.


## Live dry-run validation

On 2026-10-23 HKT, the Staging VPS ran Canonical Promotion v1 without `--execute` for `BD_PNAP_APP145`.

Result:

```text
mode = dry-run
status = READY_TO_PROMOTE
```

The approved baseline and staged Drive object matched exactly:

```text
SHA-256
dc3262cc55c5fd79d29f337fd811cdd871543f59d795972d9f30f558e313127c

Bytes
54814
```

The approved canonical destination is:

```text
gdrive-bd-write:Current/APP/APP145.pdf
```

Dry-run confirmed:

```text
overwrite_allowed = false
staging_source_retained = true
baseline_changed = false
ingestion_triggered = false
```

A read-only check after the dry-run confirmed `Current/APP` remained empty.

The next gate is the first explicit canonical promotion using `--execute`.


## First canonical promotion verification

The first explicit canonical promotion for `BD_PNAP_APP145` completed successfully.

Read-only Google Drive inspection confirmed both objects exist:

```text
gdrive-bd-write:Current/APP/APP145.pdf
gdrive-bd-write:_Staging_Incoming/APP/APP145.pdf
```

Both objects reported:

```text
Size: 54814 bytes
MimeType: application/pdf
```

A separate byte-level verification using `rclone cat | sha256sum` produced the same SHA-256 for the canonical Current object, the retained Staging object, and the approved baseline:

```text
dc3262cc55c5fd79d29f337fd811cdd871543f59d795972d9f30f558e313127c
```

Therefore Canonical Promotion v1 is considered VERIFIED and FROZEN for this milestone.

Verified properties:

```text
Current canonical object created
Staging source retained
Byte size matched
SHA-256 matched
Overwrite protection retained
Baseline unchanged
Knowledge ingestion not triggered
Production not modified
```

Future changes to Canonical Promotion v1 require regression coverage before use.
