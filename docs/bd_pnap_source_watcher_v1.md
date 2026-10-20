# BD PNAP Source Watcher v1

Status: DOMAIN DESIGN / CHANGEDETECTION DEPLOYMENT DEFERRED

BD PNAP is the first domain profile on the shared Source Change Detection platform defined in `docs/source_change_detection_v1.md`. The changedetection.io container is shared across departments; BD-specific interpretation remains in this domain watcher.

## Architecture

```text
Buildings Department (BD) official PNAP page
        |
        v
changedetection.io
Detect only: page change / diff / history
        |
        v
Jason OS BD PNAP domain logic
Confirm PNAP code / revision / URL / checksum
        |
        v
Google Drive
Document Source of Truth
        |
        v
Staging ingestion + retrieval validation
        |
        v
Production only after validation
```

The shared detector is deliberately replaceable. It is not the document Source of Truth and it is not allowed to mutate the Knowledge DB. Other departments should reuse the same detector platform with separate source profiles and department-specific domain logic.

## Phase 1 boundary

The first deployment runs only in Staging.

- Official upstream image: `dgtlmoon/changedetection.io`.
- Image is pinned by digest in `ops/changedetection/docker-compose.staging.yml`.
- Web UI is bound to `127.0.0.1:5001` only.
- Persistent state is stored in the named Docker volume `jason-os-changedetection-staging-data`.
- The container uses a dedicated bridge network and is not attached to any Knowledge DB network.
- No Google Drive credential, rclone configuration, database credential, Docker socket, or production secret is supplied to the container.
- No Production Knowledge Brain component is changed by this deployment.

The initial watch target is the official BD PNAP index page:

`https://www.bd.gov.hk/en/resources/codes-and-references/practice-notes-and-circular-letters/index_pnap.html`

changedetection.io should only answer: "Did the official source page materially change?"

It must not decide which PDF is canonical, whether a PNAP is current/obsolete, or whether Production should be updated. Those decisions belong to the later Jason OS domain watcher.

## Staging deployment

Run from the Staging checkout only:

```bash
cd /opt/ai-knowledge-staging

git status --short
git branch --show-current

docker compose \
  -f ops/changedetection/docker-compose.staging.yml \
  pull

docker compose \
  -f ops/changedetection/docker-compose.staging.yml \
  up -d

docker ps \
  --filter name=jason-os-changedetection-staging \
  --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}'

curl -I http://127.0.0.1:5001/
```

Expected branch: `staging`.

Expected exposure: `127.0.0.1:5001->5000/tcp`.

Do not expose port 5001 publicly.

For browser access from a trusted workstation, use an SSH tunnel rather than a public firewall rule:

```bash
ssh -L 5001:127.0.0.1:5001 <vps-host>
```

Then open `http://127.0.0.1:5001` locally.

## Rollback

Stop and remove only the Staging detector container/network:

```bash
cd /opt/ai-knowledge-staging

docker compose \
  -f ops/changedetection/docker-compose.staging.yml \
  down
```

The named data volume is retained by default. Do not add `-v` unless the detector history is intentionally being discarded.

## Promotion gate

Do not deploy a Production detector until all of the following are confirmed:

1. Staging container starts with the pinned official image.
2. UI is loopback-only.
3. BD PNAP index can be watched without browser automation.
4. A harmless test change/diff workflow is understood.
5. No Knowledge DB or Drive credentials are present inside the detector container.
6. The Jason OS PNAP checksum/manifest module is designed and regression-tested.

## Update policy

A changedetection.io software update is treated like any other infrastructure change:

```text
new upstream release
  -> update digest on staging
  -> CI contract test
  -> deploy staging
  -> smoke test
  -> PR staging -> main
  -> production only after approval
```

Do not track `:latest` in the Git-controlled deployment file.
