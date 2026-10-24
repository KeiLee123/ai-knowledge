# M5D — Version Snapshot Persistence / Comparison v1

Status: GITHUB STAGING / CI VERIFIED  
Environment: Staging state only  
Production impact: NONE  
VPS live verification: pending

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

## Current boundary

M5D is CI-verified in GitHub `staging` at commit `0acef1a`.

The first VPS live proof should use APP149 to initialize the current reference and then compare the same proposal, expecting `NO_CHANGE`.

Production remains untouched.
