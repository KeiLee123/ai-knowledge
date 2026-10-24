# Source Change Detection v1

Status: OPTIONAL MODULE / DEPLOYMENT DEFERRED

## Architecture

```text
Government / official department websites
        |
        v
shared changedetection.io instance
Detect only: page change / diff / history
        |
        +--> BD profile
        +--> FSD profile
        +--> LandsD profile
        +--> other department profiles
        |
        v
department-specific Jason OS watcher
Interpret code / revision / status / canonical URL
        |
        v
checksum + manifest + Google Drive
        |
        v
Staging validation
        |
        v
Production only after validation
```

changedetection.io is an optional, shared, replaceable detection platform. The adopted MVP is a lightweight Source Registry + HTTP detector first. Deploy changedetection.io only when its UI, diff history, notifications, or manual watch management provide clear value. Do not run one container per department unless isolation is later justified by evidence.

## Responsibilities

The shared detector may:

- watch multiple official URLs;
- keep change history and diffs;
- group watches by department or source;
- indicate that a source page materially changed.

The shared detector must not:

- decide which document version is canonical;
- write to the Knowledge DB;
- hold Google Drive credentials;
- trigger Production ingestion directly;
- interpret department-specific document status without a domain watcher.

## Source profiles

Each department is represented as a logical source profile, not a separate container.

Example conceptual tags:

```text
department:bd
source:pnap
risk:regulatory

department:fsd
source:code-or-circular

department:landsd
source:practice-note
```

Exact tags and watched URLs are configuration data and may evolve without changing the shared detector deployment.

## Deployment boundary

Staging uses `ops/changedetection/docker-compose.staging.yml`.

- Official upstream image, digest-pinned.
- Loopback-only UI on `127.0.0.1:5001`.
- Dedicated persistent datastore.
- Dedicated bridge network.
- No Knowledge DB network.
- No Docker socket.
- No Google Drive credential.
- No Production secret.

BD PNAP is the first source profile used to validate the shared detector. It is not the architectural limit of the detector.

## Promotion gate

Before Production deployment:

1. shared detector starts successfully in Staging;
2. loopback-only exposure is confirmed;
3. at least one simple official page watch works without browser automation;
4. watch grouping/tagging for multiple departments is understood;
5. no privileged credentials are present in the container;
6. department-specific checksum/manifest logic remains outside changedetection.io.

## Principle

```text
One shared Detect platform
+ many department source profiles
+ separate domain logic
```

This keeps the Detect engine replaceable while allowing Jason OS to expand to additional government departments without duplicating infrastructure.
