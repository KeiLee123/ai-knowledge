# M9 — Source Readiness Audit v1

Status: VPS READ-ONLY VERIFIED / APP145 PREPARATION TARGET SELECTED

## Purpose

This audit evaluates candidate sources for the first M9 expansion beyond the autonomously verified APP149 canary.

Candidates reviewed:

```text
BD_PNAP_APP145
BD_PNAP_APP146
```

This audit does not schedule either source and does not initialize or advance any version reference.

## Admission criteria

The M9 architecture requires a candidate source to satisfy all of the following before scheduling:

1. source exists in the GitHub Source Registry;
2. source is enabled;
3. canonical source URL / host / content-type contracts exist;
4. source has an existing current Staging version reference;
5. source can run through the generic M5E monitor without Production access/write;
6. source is explicitly admitted to the M9 schedule allowlist.

Registry readiness alone is insufficient.

## BD_PNAP_APP145

Repository evidence:

```text
registry enabled                       yes
official-document source               yes
canonical URL defined                  yes
allowed host defined                   yes
expected PDF content type              yes
Staging Drive writer                   configured
Staging canonical promotion            configured
Staging canonical ingestion            configured
Staging canonical-text ingestion       configured
Production Promotion v1                historically verified / frozen
Production write authorization         false
```

Operational maturity is high.

APP145 also has a frozen Production promotion history, which provides strong deterministic artifact evidence. M9 monitoring must remain completely separate from that frozen Production layer.

Repository evidence does not prove that the following runtime file currently exists:

```text
/var/lib/jason-os/source-monitor-staging/version-snapshots/current/BD_PNAP_APP145.json
```

Therefore APP145 is:

```text
M9 candidate readiness = CONDITIONAL
blocking item = current Staging version-reference proof
```

## BD_PNAP_APP146

Repository evidence:

```text
registry enabled                       yes
official-document source               yes
canonical URL defined                  yes
allowed host defined                   yes
expected PDF content type              yes
Staging Drive writer                   configured
Staging canonical promotion            configured
Staging multimodal-v2 ingestion        configured
canonical-text ingestion               disabled
Production source-monitor write        forbidden
```

APP146 has prior Staging live-verification through the multimodal official-source lifecycle.

Repository evidence does not prove that the following runtime file currently exists:

```text
/var/lib/jason-os/source-monitor-staging/version-snapshots/current/BD_PNAP_APP146.json
```

Therefore APP146 is:

```text
M9 candidate readiness = CONDITIONAL
blocking item = current Staging version-reference proof
```

## Preliminary comparison

| Criterion | APP145 | APP146 |
|---|---|---|
| Registry enabled | PASS | PASS |
| Official URL/host/content contract | PASS | PASS |
| Staging lifecycle configuration | PASS | PASS |
| Prior live lifecycle evidence | strong | strong |
| Existing version-reference proof in repository evidence | NOT PROVEN | NOT PROVEN |
| Production-write safety | guarded/frozen | guarded |
| Complexity for first M9 expansion | lower | higher |
| Preliminary MVP preference | FIRST | SECOND |

## Preliminary recommendation

If the VPS reference audit shows both sources are equally ready, prefer:

```text
first expansion source = BD_PNAP_APP145
```

Reason:

- APP145 has the most mature deterministic lifecycle evidence;
- it already has a frozen verified Production history without requiring M9 to touch that Production layer;
- it exercises a second source while keeping the first M9 multi-source proof operationally simple;
- APP146 can then be the next expansion source to add multimodal-route diversity after the orchestration layer is proven.

This is an MVP sequencing recommendation, not an admission authorization.

## Required VPS read-only audit

Before source selection is finalized, verify the runtime reference directory without writing state.

Required evidence:

```text
/var/lib/jason-os/source-monitor-staging/version-snapshots/current/
```

For APP145 and APP146 record:

- whether the reference file exists;
- SHA-256 of the reference file if present;
- stored source_id;
- stored release_id;
- artifact_profile;
- qualification status / decision;
- document_sha256 from the stored snapshot.

Do not initialize, advance, or modify a reference during this audit.

## Decision rule after VPS audit

```text
APP145 reference valid + APP146 reference absent
    -> select APP145

APP146 reference valid + APP145 reference absent
    -> select APP146

both valid
    -> select APP145 for MVP simplicity

neither valid
    -> select APP145 as preparation target,
       then create its reference through a separate explicit Staging milestone
```

## Safety boundary

This readiness audit authorizes none of the following:

- M9 implementation;
- schedule allowlist changes;
- systemd changes;
- timer activation;
- reference initialization;
- reference advancement;
- Production database access or writes.


## VPS read-only verification result

Observed runtime state:

```text
BD_PNAP_APP145
reference_exists=false

BD_PNAP_APP146
reference_exists=false

BD_PNAP_APP149
reference_exists=true
reference_sha256=4514531e59caf76782120cf83377bcea6ad8a23f076e6b03b2247b193ae8682c
source_id=BD_PNAP_APP149
release_id=bd_pnap_app149-a5b4d5a1af5f
artifact_profile=canonical-text-v1
qualification_status=qualified
qualification_decision=AUTO_QUALIFIED
document_sha256=a5b4d5a1af5f4a32b43973db33d95436f9390e8e2da77747ee666015077bb1a8
```

M8 timer safety check during the audit:

```text
enabled
active
```

Audit side effects:

```text
Reference writes performed = false
Production DB modified = false
```

## Selection decision

Because neither APP145 nor APP146 currently has a Staging version reference, neither source is eligible for M9 scheduling.

Per the architecture decision rule, the first preparation target is:

```text
BD_PNAP_APP145
```

APP145 is selected for preparation before APP146 because it provides the simpler first expansion path and has the most mature deterministic lifecycle history.

This selection authorizes only preparation of a Staging reference. It does not authorize scheduling, timer changes, Production access, Production writes, or changes to the frozen M8 scheduler.

## Next milestone

The next milestone is:

```text
M9A — APP145 Staging Reference Preparation
```

M9A should:

1. derive a deterministic APP145 version-signal proposal using existing guarded Staging tooling;
2. verify the proposal is source/profile consistent;
3. initialize the APP145 reference only through the explicit Staging reference-write gate;
4. record the resulting reference SHA and stored metadata;
5. prove Production access/write remain false;
6. leave the M8 timer unchanged;
7. stop before adding APP145 to any M9 schedule allowlist.

M9A is a prerequisite for the first multi-source M9 monitor proof.
