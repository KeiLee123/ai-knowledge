# M5C — Version Signal Extraction v1

Status: GITHUB STAGING / CI VERIFIED  
Production impact: NONE  
VPS live verification: pending

## Purpose

M5C supplies the evidence required by `official-source-version-policy-v1`.

The new extractor converts a verified canonical artifact into a stable version snapshot.

## Snapshot model

```text
Canonical artifact + manifest + source identity
        |
        v
VersionSignalSnapshot
  authority_code
  document_code
  canonical_host

  issue_date
  first_issue_date
  last_revision_date
  revision_date
  edition

  metadata_fingerprint
  normalized_content_fingerprint
  document_sha256
```

Implementation:

```text
version_signal_extractor_v1.py
```

## PNAP date extraction

For Buildings Department PNAP-style documents, v1 recognizes explicit labels such as:

```text
First issue      January 2020
Last revision    May 2024
This revision    September 2025
```

If an explicit `This revision` label is absent, a PNAP-style footer `(M/YYYY)` may be used as a revision-date fallback.

Missing dates are left as null. They are never invented.

## Content fingerprint

The normalized-content fingerprint:

- uses extracted document text;
- applies Unicode NFKC normalization;
- collapses whitespace;
- hashes the normalized text with SHA-256.

Formatting-only whitespace changes therefore do not count as content changes.

## Material metadata fingerprint

The material metadata fingerprint includes:

- source document code;
- configured title;
- page count;
- stable PDF metadata fields:
  - title
  - author
  - subject
  - keywords
- extracted first/revision dates;
- edition.

Packaging fields such as PDF producer and creation timestamp are deliberately excluded.

This prevents simple PDF repackaging from appearing as a meaningful metadata revision.

## Snapshot comparison

`compare_version_snapshots()` converts previous/current snapshots into the exact policy inputs:

```text
authority_match
document_code_match
official_host_match
checksum_changed
normalized_content_changed
metadata_changed
previous/current issue_date
previous/current revision_date
edition_changed
staging_validation_verified
deterministic_release
```

These signals can be passed directly into `evaluate_version_update()`.

## Release proposal integration

The Staging release proposal now embeds the current snapshot under:

```yaml
release_v2:
  version_signals:
    ...
```

The same snapshot is also printed at the proposal top level for inspection.

This gives the future update lifecycle a stable prior-version reference once a release contract is recorded.

## CI coverage

Regression tests cover:

- explicit PNAP issue/revision extraction;
- PNAP footer date fallback;
- whitespace-stable normalized-content hashing;
- ignoring volatile PDF packaging metadata;
- detecting material metadata changes;
- snapshot comparison driving AUTO_QUALIFIED;
- packaging/checksum-only changes driving REVIEW_REQUIRED.

## Current boundary

M5C is implemented and CI-verified in GitHub `staging`.

It is not yet live-verified against the actual APP149 canonical file on the VPS.

Production is untouched.
