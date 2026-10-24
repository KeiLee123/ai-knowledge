# M5B — Automatic Version Qualification Policy v1

Status: GITHUB STAGING / CI VERIFIED  
Production impact: NONE  
VPS deployment: pending

## Purpose

M5B removes routine human approval from official-source release qualification.

The policy classifies a candidate as:

- `AUTO_QUALIFIED`
- `REVIEW_REQUIRED`
- `BLOCKED`
- `NO_CHANGE`

Human review is exception-only.

## Policy

Implementation:

```text
version_qualification_policy_v1.py
```

Policy version:

```text
official-source-version-policy-v1
```

### Initial release

Auto-qualify only if all are true:

```text
official_source_identity        = true
staging_validation_verified     = true
deterministic_release           = true
canonical_checksum_locked       = true
chunks_checksum_locked          = true
```

Explicit failure -> `BLOCKED`.

Missing required signals -> `REVIEW_REQUIRED`.

### Version update

Auto-qualify only if identity and safety signals pass:

```text
authority_match                 = true
document_code_match             = true
official_host_match             = true
staging_validation_verified     = true
deterministic_release           = true
checksum_changed                = true
normalized_content_changed      = true
metadata_changed                = true
```

And at least one forward version signal exists:

```text
issue_date is newer
OR revision_date is newer
OR edition_changed = true
```

Date regression or identity mismatch -> `BLOCKED`.

Checksum-only / packaging-only or incomplete version metadata -> `REVIEW_REQUIRED`.

No material change -> `NO_CHANGE`.

## Source Registry

Default lifecycle:

```yaml
lifecycle:
  production_write: false
  qualification_policy: official-source-version-policy-v1
  exception_review: true
```

Routine `require_human_review` is removed.

## Release contract

Generic Production v2 now requires:

```yaml
qualification:
  method: policy
  policy_version: official-source-version-policy-v1
  mode: initial_release
  status: qualified
  decision: AUTO_QUALIFIED
  signals:
    official_source_identity: true
    staging_validation_verified: true
    deterministic_release: true
    canonical_checksum_locked: true
    chunks_checksum_locked: true

write_authorized: false
```

The contract validator recomputes the outcome from `signals`; a manually edited `status: qualified` is not enough.

## Proposal behavior

The Staging proposal generator now:

1. validates the Staging milestone;
2. checksum-verifies the canonical source;
3. builds the release artifact twice;
4. refuses if the two artifact representations differ;
5. locks canonical/chunks hashes;
6. evaluates initial-release policy;
7. emits `write_authorized: false`.

It performs no Production access or write.

## Current integration gap

The policy engine is implemented and CI-verified.

Automatic version-update signal acquisition is not yet complete. The Source Monitor still needs reliable extraction of:

- issue date;
- revision date;
- edition/version metadata;
- material metadata fingerprint;
- normalized-content fingerprint.

Missing signals must not be guessed. They correctly produce `REVIEW_REQUIRED`.

## Production boundary

M5B does not enable Production write.

`write_authorized` remains a separate gate until automatic Production promotion itself is separately qualified.

APP-145 Production Promotion v1 remains frozen.
