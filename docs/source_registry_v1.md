# Source Registry v1

Status: STAGING MVP / READ-ONLY PROBE

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

This first stage is intentionally read-only. It does not write to Google Drive, PostgreSQL, the Knowledge DB, or a persistent baseline.

Later stages may add:

```text
read-only probe
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
manifest / baseline
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

## Promotion gate for the next phase

Before adding persistent baseline or Drive writes:

1. registry contract test passes in CI;
2. APP-145 live probe succeeds from the Staging VPS;
3. official index and PDF return the expected content types;
4. fingerprints are reproducible across two unchanged probes;
5. no credential or database access is present in the detector;
6. Drive destination mapping is verified independently.

## Principle

```text
先知道「現在官方來源是甚麼」
再處理「和上次有甚麼不同」
最後才處理「要不要入庫」
```

This keeps detection independent from interpretation and storage.
