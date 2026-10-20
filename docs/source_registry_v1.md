# Source Registry v1

Status: STAGING MVP / BASELINE VALIDATED / DRIVE MAPPING NEXT

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
