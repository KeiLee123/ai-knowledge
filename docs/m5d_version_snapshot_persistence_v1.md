# M5D — Version Snapshot Persistence / Comparison v1

Status: VPS STAGING LIVE VERIFIED  
Environment: Staging state only  
Production impact: NONE  
VPS live verification: COMPLETE

## Purpose

M5D stores the previously accepted version-signal snapshot and compares future snapshots against that reference.

## Runtime state

```text
/var/lib/jason-os/source-monitor-staging/
└── version-snapshots/
    ├── current/<source_id>.json
    └── history/<source_id>/<document_sha256>.json
```

This is operational state. GitHub remains the code Source of Truth, and Google Drive remains the canonical document Source of Truth.

## Module

`version_snapshot_store_v1.py` supports:

- `initialize`: create the first accepted Staging reference;
- `compare`: read-only comparison against the stored reference;
- `advance`: move the reference only after a policy-qualified version update.

## Safety contract

A proposal used by the snapshot store must remain Staging-only and must have:

```text
production_access = false
production_write = false
write_authorized = false
```

The proposal's top-level version snapshot must match the release-contract snapshot.

State-changing operations require `--confirm-staging-state-write`.

A Production Source Monitor state root is explicitly rejected.

## Comparison behavior

The stored reference and current snapshot are converted to policy inputs by `compare_version_snapshots()`, then evaluated by `official-source-version-policy-v1`.

Possible outcomes:

```text
AUTO_QUALIFIED
REVIEW_REQUIRED
BLOCKED
NO_CHANGE
```

Only `AUTO_QUALIFIED` may advance the current reference.

## History

Before a qualified advance replaces the current reference, the previous record is archived by its document SHA-256.

This keeps a simple audit trail without changing the canonical document or Production database.

## CI coverage

Regression tests verify:

- initial reference persistence;
- same snapshot -> `NO_CHANGE`;
- newer material version -> `AUTO_QUALIFIED`;
- qualified advance archives the prior reference;
- packaging-only ambiguity -> `REVIEW_REQUIRED`;
- ambiguous updates cannot advance;
- Production state-root exclusion.

## Live verification record

Verified on 2026-10-24 using APP149 on VPS Staging.

- deployed commit: `a7e353f0037e17a1e5d7e46a37f0a58cfc449091`
- source ID: `BD_PNAP_APP149`
- reference path: `/var/lib/jason-os/source-monitor-staging/version-snapshots/current/BD_PNAP_APP149.json`
- release ID: `bd_pnap_app149-a5b4d5a1af5f`
- issue date: `2010-12`
- revision date: `2010-12`
- document SHA-256: `a5b4d5a1af5f4a32b43973db33d95436f9390e8e2da77747ee666015077bb1a8`
- metadata fingerprint: `e562a224e3f14f92a08ccd6129c857f6364c4355f61404fb6b50ac1247cb0aa3`
- normalized-content fingerprint: `6204cefef72c45e11942eabab04a87b9d89d6002f8c12fb26af5254f1c8c0358`
- initial reference status: `REFERENCE_INITIALIZED`
- same-snapshot comparison decision: `NO_CHANGE`
- `checksum_changed = false`
- `metadata_changed = false`
- `normalized_content_changed = false`
- `write_authorized = false`
- `production_access = false`
- `production_write = false`
- Production release registry remained empty
- no Production version-snapshot state was created
- Git worktree remained clean
- command block exit code: `0`

## Current boundary

M5D is live-verified on VPS Staging.

The remaining gap is automatic Source Monitor integration: when a source changes, generate a candidate snapshot, compare it with the stored reference, and route the policy decision without manually running the snapshot store.

Production remains untouched.