# VPS Storage Policy v1

Status: ADOPTED ARCHITECTURE / STAGING IMPLEMENTATION

## Purpose

Jason OS treats the 100 GB VPS as a compute/runtime node, not as a long-term document archive.

The Business Google Drive (5 TB) is the capacity storage layer for durable documents and archives.

GitHub remains the code/configuration Source of Truth.

## Storage roles

```text
GitHub
  = code + configuration Source of Truth

VPS
  = compute + runtime + database + temporary working storage

Business Google Drive
  = document + archive + report + durable file Source of Truth
```

## VPS: keep local

The VPS should keep data that benefits from low latency, frequent reads/writes, transactions, or active runtime access:

- PostgreSQL / pgvector data
- Docker runtime state and required images
- embedding runtime/model files
- Production and Staging Git checkouts
- small application state
- recent operational logs
- temporary ingestion/OCR/rendering workspace
- lightweight personal services

## Google Drive: keep durable

Capacity-heavy or long-lived files should be stored in Business Google Drive:

- official PDFs and source documents
- historical document revisions
- ZIP archives
- generated reports
- exports
- long-term source archives
- large images and generated artifacts that need retention
- backups that are appropriate for file storage

## Temporary processing rule

All document processing jobs should use disposable local working directories, for example:

```text
/tmp/jason-os/<job-id>/
```

Preferred lifecycle:

```text
download to temporary workdir
  -> process / checksum / validate
  -> upload canonical result to Google Drive
  -> verify durable copy
  -> delete successful temporary workdir
```

Failed jobs may retain temporary artifacts briefly for debugging, but those artifacts must have a TTL and must not become a permanent archive.

## Capacity budget

This is a soft operational budget, not a disk partitioning scheme.

Target normal long-term VPS usage:

- preferred used space: about 40-55 GB
- preferred free space: at least 30 GB
- remaining headroom is reserved for growth and unexpected workloads

Health bands:

```text
< 60% used   Healthy
60-70%       Observe
70-80%       Warning
80-85%       Cleanup required
> 85%        Critical
```

## Separation

Production, Staging, shared infrastructure, and personal services should remain logically isolated.

A personal service must not automatically gain access to:

- Production PostgreSQL
- Jason OS Production secrets
- Production application directories
- Knowledge Brain database networks

Isolation may use separate Docker networks, directories, and credentials.

## Service policy

Persistent services may use Docker when containerization improves isolation or lifecycle management.

Short-lived scheduled jobs do not need Docker by default. A small Python or shell job plus systemd is acceptable when it is simpler.

Examples:

- PostgreSQL / pgvector: persistent local service
- changedetection.io: optional persistent service, only if its UI/diff/history is useful
- source registry detector: may be a lightweight scheduled job
- crawler/browser stack: add only when a source cannot be handled reliably by simple HTTP parsing

## Source-monitoring storage rule

A source-monitoring workflow must not build a permanent document corpus on the VPS.

Preferred flow:

```text
official source
  -> detect change
  -> temporary download
  -> checksum / parse
  -> Google Drive Current / Archive / Manifest
  -> local cleanup
```

## Change control

This policy does not modify any frozen Knowledge Brain or Spaced Repetition layer.

Infrastructure changes still follow:

```text
staging
  -> regression / smoke test
  -> PR staging -> main
  -> Production only after validation
```
