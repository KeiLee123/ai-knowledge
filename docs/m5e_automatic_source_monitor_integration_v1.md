# M5E — Automatic Source Monitor Integration v1

Status: GITHUB STAGING / CI VERIFIED  
Production impact: NONE  
VPS live verification: pending

## Purpose

M5E connects the existing Source Monitor baseline, M5C version-signal extraction, and M5D stored reference into one Staging-only monitor entrypoint.

Implementation:

```text
monitor_official_source_v1.py
```

## Architecture

```text
Official source probe
        |
        v
Baseline comparison
        |
        +-- UNCHANGED
        |      -> NO_CHANGE
        |
        +-- INDEX_CHANGED
        |      -> NO_CHANGE
        |
        +-- DOCUMENT_CHANGED
               |
               v
        Download candidate
               |
               v
        Verify candidate checksum
               |
               v
        Extract candidate snapshot
               |
               v
        Compare stored reference
               |
               v
        Candidate pre-gate
          CANDIDATE_NEW_VERSION
          REVIEW_REQUIRED
          BLOCKED
          NO_CHANGE
```

## Important safety boundary

`CANDIDATE_NEW_VERSION` is **not** `AUTO_QUALIFIED`.

A candidate has not yet completed Staging ingestion, semantic validation, or deterministic release qualification.

Therefore M5E intentionally uses a pre-gate:

```text
CANDIDATE_NEW_VERSION
-> STAGING_VALIDATION_REQUIRED
```

Only after the candidate completes the existing Staging lifecycle may `official-source-version-policy-v1` evaluate the full `version_update` signals and produce `AUTO_QUALIFIED`.

This prevents Source Monitor metadata alone from bypassing Staging validation.

## Candidate pre-gate

A changed document becomes `CANDIDATE_NEW_VERSION` only when:

```text
authority matches
document code matches
official host matches

AND

issue/revision date moves forward
OR edition changes

AND

checksum changed
metadata fingerprint changed
normalized-content fingerprint changed
```

Ambiguous / packaging-only change:

```text
REVIEW_REQUIRED
```

Identity mismatch or date regression:

```text
BLOCKED
```

## No-change behavior

If the baseline document checksum is unchanged, M5E returns `NO_CHANGE` without downloading a candidate.

An index-page-only change also returns `NO_CHANGE` for the document.

## Race protection

The live candidate is downloaded only after the baseline probe reports `DOCUMENT_CHANGED`.

Its SHA-256 must match the SHA observed by the probe.

If the source changes again between probe and candidate download:

```text
BLOCKED
reason = source_changed_during_monitor_run
```

## Runtime state

M5E reads the M5D reference under:

```text
/var/lib/jason-os/source-monitor-staging/
  version-snapshots/current/<source_id>.json
```

It does not advance the reference.

Reference advance remains a separate M5D operation and is allowed only after full `AUTO_QUALIFIED` version-update qualification.

## Production boundary

M5E contains no Production writer or Production release registry path.

Every result explicitly reports:

```text
production_access = false
production_write = false
```

## CI coverage

Tests verify:

- newer material candidate -> `CANDIDATE_NEW_VERSION`;
- candidate path marks Staging validation as still required;
- packaging/checksum-only changes -> `REVIEW_REQUIRED`;
- date regression -> `BLOCKED`;
- monitor action routing;
- Production write surface absent;
- existing M5B/M5C/M5D and Generic Production v2 contracts remain passing.

## Current boundary

M5E is CI-verified in GitHub `staging` at commit `1b04dea`.

VPS live verification is pending.

The expected APP149 live result, while the official document remains unchanged, is `NO_CHANGE` with no candidate download.
