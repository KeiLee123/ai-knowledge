# Source Registry v1

Status: STAGING MVP / FIRST OFFICIAL DOCUMENT STAGED + ROUNDTRIP VERIFIED / CANONICAL PROMOTION DESIGN NEXT

## Purpose

Source Registry v1 is the small, Git-controlled registry for official upstream sources watched by Jason OS.

It separates three concerns:

```text
Source Registry
    = what should be watched

Detector
    = fetch + fingerprint + report what exists now

Domain resolver
    = decide document identity / revision / current-vs-obsolete meaning
```

The registry is configuration, not a crawler, database, or document archive.

## MVP architecture

```text
Official publisher
      |
      v
Source Registry v1
      |
      v
Lightweight HTTP probe
GET index + selected canonical document
      |
      v
URL / HTTP metadata / byte length / SHA-256
      |
      v
JSON result to stdout
```

The HTTP probe remains read-only. The next layer stores only a small local runtime baseline so unchanged and changed states can be distinguished.

```text
read-only probe
      |
      v
explicit local baseline
      |
      v
compare only
      |
      +--> UNCHANGED
      +--> INDEX_CHANGED
      +--> DOCUMENT_CHANGED
```

The baseline is runtime state, not code or document storage. It belongs on the VPS and must not be committed to GitHub.

The baseline layer does not auto-accept a detected change. A changed fingerprint remains pending human/domain review.

Later stages may add:

```text
detected change
      |
      v
domain resolver
      |
      v
temporary download
      |
      v
verified Drive writer
      |
      v
manifest
      |
      v
Staging ingestion and retrieval validation
```

Each stage remains replaceable.

## First canary

The first enabled source is:

- Authority: Buildings Department (BD)
- Source family: PNAP
- Document code: APP-145
- Index: the official BD PNAP index
- Canonical document: the official APP145 PDF

APP-145 is deliberately used as a small, stable canary. The purpose of this phase is to validate source registration, safe HTTP retrieval, and deterministic fingerprinting before implementing revision parsing or Google Drive writes.

## Registry contract

Each enabled source declares:

- `authority_code`
- `source_family`
- `document_code`
- `publisher`
- `index_url`
- `canonical_url`
- `allowed_hosts`
- expected content types

Only HTTPS URLs are accepted by the detector. The final redirected URL must also remain on an allowed host.

The registry contains no secret, OAuth credential, database credential, or writable Google Drive credential.

## Detector contract

`detect_source_changes_v1.py` may:

- read the YAML registry;
- make HTTPS GET requests to registered official sources;
- record response status and selected HTTP metadata;
- calculate SHA-256 of the fetched bytes;
- print a JSON observation.

It must not:

- write a baseline in this version;
- upload or delete Google Drive files;
- write to PostgreSQL;
- call the Knowledge ingestion pipeline;
- decide that a new revision is canonical;
- promote anything to Production.

## Production / Staging boundary

This module is developed and validated on `staging` first.

Production remains unchanged.

A later writer must not be enabled until the exact Business Google Drive destination and the VPS `gdrive-out:` mapping are verified.

## Live validation

On 2026-10-21 HKT, the Staging VPS ran two consecutive live probes against the official BD PNAP index and APP-145 PDF.

Both probes returned identical fingerprints:

```text
PNAP index SHA-256
720242765e469760bad0cef5c42c401b0a24afec93f4b19ef9c26f0a121b6b4b

APP-145 PDF SHA-256
dc3262cc55c5fd79d29f337fd811cdd871543f59d795972d9f30f558e313127c
```

The official index returned `text/html` and the document returned `application/pdf`, both with HTTP 200. This validates deterministic fingerprinting for the first canary.

## Baseline phase

`source_monitor_baseline_v1.py` adds an explicit local baseline and comparison layer.

The state root must be supplied as an absolute path. Staging uses:

```text
/var/lib/jason-os/source-monitor-staging
```

Initialization is explicit and refuses to overwrite an existing baseline. A normal check is read-only and never updates the baseline.

Change classification:

```text
same index hash + same document hash
    -> UNCHANGED

different index hash + same document hash
    -> INDEX_CHANGED

different document hash
    -> DOCUMENT_CHANGED
```

Document change has priority because the document fingerprint is the canonical content signal for this canary.

## Promotion gate for the next phase

Before adding Google Drive writes:

1. Source Registry and baseline regression tests pass in CI;
2. APP-145 live baseline is initialized in Staging;
3. a second live check returns `UNCHANGED`;
4. baseline overwrite protection is confirmed;
5. no credential or database access is present in detector/baseline code;
6. the exact Business Google Drive destination and VPS `gdrive-out:` mapping are verified independently.

## Principle

```text
先知道「現在官方來源是甚麼」
再處理「和上次有甚麼不同」
最後才處理「要不要入庫」
```

This keeps detection independent from interpretation and storage.


## Live baseline validation

On 2026-10-21 HKT, the Staging VPS initialized the first persistent runtime baseline for `BD_PNAP_APP145` at:

```text
/var/lib/jason-os/source-monitor-staging/baselines/BD_PNAP_APP145.json
```

Regression tests passed before initialization:

```text
Source Registry v1 contract: PASS
Source Monitor baseline v1: PASS
```

The first live check against that baseline returned:

```text
status: UNCHANGED
```

with both the PNAP index and APP-145 PDF fingerprints identical to the baseline:

```text
PNAP index SHA-256
720242765e469760bad0cef5c42c401b0a24afec93f4b19ef9c26f0a121b6b4b

APP-145 PDF SHA-256
dc3262cc55c5fd79d29f337fd811cdd871543f59d795972d9f30f558e313127c
```

This validates the Source Registry + live HTTP probe + persistent baseline + compare path for the first Staging canary.

The next gate is read-only verification of the VPS writable Google Drive remote and its exact mapping to the Business Google Drive canonical BD PNAP tree. No Drive writer should be enabled before that mapping is proven.


## Business Drive mapping validation

On 2026-10-21 HKT, the Staging VPS verified the rclone remotes without exposing configuration secrets.

`gdrive:` is the 5 TiB Business Google Drive remote. Its rclone root is already scoped to the canonical Jason OS knowledge root:

```text
Business Google Drive
Jason OS/
└── 06_Knowledge/
    └── (rclone gdrive: root)
```

The VPS therefore sees:

```text
gdrive:
├── 00_Inbox
├── 10_Building_Surveying
├── 20_Contracting
├── 30_Accounting_Finance
├── 40_Investment
└── ...
```

The folder ID for `gdrive:10_Building_Surveying` matched the canonical Business Drive folder ID, confirming identity and root mapping.

The canonical BD PNAP tree is reachable at:

```text
gdrive:10_Building_Surveying/BD_PNAP
├── Current
│   ├── ADM
│   ├── APP
│   └── ADV
└── Source_ZIP
```

`gdrive-out:` is a separate 15 GiB Drive rooted at `Jason-OS` and is not the canonical BD PNAP document store.

No Source Monitor writer may use `gdrive-out:` for BD PNAP.

The next gate is a tiny Staging-only write/read-back/delete canary under a dedicated temporary folder on `gdrive:`. The canary must not touch `Current/APP` or any real PNAP document.


## Write canary result

On 2026-10-21 HKT, a Staging-only Business Drive write canary attempted to create:

```text
gdrive:10_Building_Surveying/BD_PNAP/_Staging_Write_Canary
```

Google Drive rejected the create request with HTTP 403 and:

```text
ACCESS_TOKEN_SCOPE_INSUFFICIENT
insufficient authentication scopes
```

Because the shell used `set -euo pipefail`, execution stopped at `rclone mkdir`. The canary file was never uploaded.

This confirms:

- `gdrive:` identity and canonical folder mapping are correct;
- the current OAuth token is intentionally/effectively read-only for write operations;
- the failure is an authorization-scope problem, not a path, capacity, or checksum problem.

Do not widen or reconnect the existing `gdrive:` remote in place until frozen consumers are reviewed.

Preferred next architecture:

```text
gdrive:
    read-only Business Drive source

gdrive-business-write:
    separate writable Business Drive remote
    explicit writer path
    used only by approved Staging/Production writer modules
```

The existing read-only remote should remain untouched so current ingestion behavior cannot regress.

Before creating a writable remote, inspect the redacted remote configuration and confirm the existing scope/root settings without exposing tokens.


## Writable BD PNAP remote

On 2026-10-23 HKT, a separate writable rclone remote was configured without modifying the existing read-only `gdrive:` remote.

```text
gdrive:
    scope = drive.readonly
    purpose = existing Knowledge read source
    status = unchanged / frozen

gdrive-bd-write:
    scope = drive
    root_folder_id = BD_PNAP
    purpose = approved BD PNAP writer
```

The writable remote root was verified to expose only:

```text
Current
Source_ZIP
```

This confirms OAuth write scope and root isolation at the BD_PNAP folder boundary.

The next gate is a tiny Staging-only write/read-back/delete canary under `_Staging_Write_Canary`. No real PNAP document or `Current/APP` content should be modified during that test.


## Business Drive write canary validation

On 2026-10-23 HKT, the isolated `gdrive-bd-write:` remote completed a full Staging write/read-back/delete canary under:

```text
BD_PNAP/_Staging_Write_Canary/write-canary.txt
```

The local file SHA-256 and round-trip SHA-256 were identical:

```text
14b832475ce123989cb4e009d46acf0fdcee31386a7336f3ec5c1d7e7aee8903
```

The temporary canary folder was deleted successfully after verification.

This validates:

- writable OAuth scope;
- BD_PNAP root isolation;
- create/upload capability;
- read-back capability;
- byte integrity after round trip;
- cleanup capability.

No real PNAP document, `Current`, `APP`, `ADM`, `ADV`, or `Source_ZIP` content was modified.

The next phase is PNAP Drive Writer v1. Its first implementation must:

1. operate in Staging only;
2. download to a temporary local file;
3. verify SHA-256 before upload;
4. upload only to a registry-approved path under `gdrive-bd-write:`;
5. verify the remote object after upload;
6. refuse destructive overwrite in the first MVP;
7. leave baseline acceptance as an explicit later step;
8. never write directly to Production.


## PNAP writer dry-run validation

On 2026-10-23 HKT, the Staging VPS ran `write_pnap_staging_v1.py` for `BD_PNAP_APP145` without `--execute`.

Regression test:

```text
PNAP staging writer v1: PASS
```

Dry-run status:

```text
READY_TO_STAGE
```

Approved baseline SHA-256 and live re-download SHA-256 matched exactly:

```text
dc3262cc55c5fd79d29f337fd811cdd871543f59d795972d9f30f558e313127c
```

Live document size:

```text
54814 bytes
```

The approved Staging-only target is:

```text
gdrive-bd-write:_Staging_Incoming/APP/APP145.pdf
```

Overwrite remains disabled.

The next gate is the first real official-document Staging upload using `--execute`. The writer must round-trip verify the uploaded PDF and must not update the baseline or canonical `Current/APP` path.


## First official PNAP Staging upload validation

On 2026-10-23 HKT, `BD_PNAP_APP145` completed the first real official-document Staging upload through `write_pnap_staging_v1.py --execute`.

Result:

```text
status = STAGED_AND_VERIFIED
verified = true
baseline_updated = false
canonical_current_updated = false
```

Source, baseline, local download, and round-trip Drive content all matched this SHA-256:

```text
dc3262cc55c5fd79d29f337fd811cdd871543f59d795972d9f30f558e313127c
```

Uploaded size:

```text
54814 bytes
```

Staging destination:

```text
gdrive-bd-write:_Staging_Incoming/APP/APP145.pdf
```

This validates the real-document path:

```text
Official BD source
  -> Staging download
  -> approved baseline SHA-256 gate
  -> isolated Business Drive writer
  -> Staging incoming object
  -> read-back
  -> SHA-256 round-trip verification
```

No `Current/APP`, Production, Knowledge DB, or baseline state was modified.

The next phase is canonical promotion design and regression coverage. Promotion must remain a separate explicit action and must not be merged into the Staging writer without tests.
