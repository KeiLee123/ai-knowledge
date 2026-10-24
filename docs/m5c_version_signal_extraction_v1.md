# M5C — Version Signal Extraction v1

Status: VPS STAGING LIVE VERIFIED  
Production impact: NONE  
VPS live verification: COMPLETE

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

## Live verification record

Verified on 2026-10-24 using APP149 on VPS Staging.

- deployed commit: `55c9dffcd203e8e06297f6068f06a9fce08f7c6f`
- source ID: `BD_PNAP_APP149`
- authority: `BD`
- document code: `APP-149`
- canonical host: `www.bd.gov.hk`
- issue date: `2010-12`
- first issue date: `2010-12`
- revision date: `2010-12`
- revision source: `pnap_footer_month_year`
- page count: `5`
- metadata fingerprint: `e562a224e3f14f92a08ccd6129c857f6364c4355f61404fb6b50ac1247cb0aa3`
- normalized-content fingerprint: `6204cefef72c45e11942eabab04a87b9d89d6002f8c12fb26af5254f1c8c0358`
- document SHA-256: `a5b4d5a1af5f4a32b43973db33d95436f9390e8e2da77747ee666015077bb1a8`
- two independent proposal runs produced identical version snapshots
- two independent proposal runs produced identical chunk hashes
- initial-release policy decision: `AUTO_QUALIFIED`
- `write_authorized = false`
- `production_access = false`
- `production_write = false`
- Production release registry remained empty
- Git worktree remained clean
- command block exit code: `0`

## Current boundary

M5C is live-verified on VPS Staging.

The remaining gap is not signal extraction. It is persistence and comparison of the previous accepted snapshot so future source changes can automatically enter the `version_update` policy path.

Production is untouched.