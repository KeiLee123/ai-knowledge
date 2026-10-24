# Jason OS Knowledge — Capability Status v1

Status: AUDIT BASELINE  
Date: 2026-10-24

## Environment snapshot

### Production VPS

- Path: `/opt/ai-knowledge`
- Branch: `main`
- Audited commit: `436e71e98fd60c4e62ffea307d09cbdd26c8a83f`

### Staging VPS

- Path: `/opt/ai-knowledge-staging`
- Branch: `staging`
- Previous audited commit: `f58dc65826266563c55e85d195fe93923611f00d`
- M4 deployed / live-verified commit: `921e899fed7109b526700b470a5eeaa32d4539f2`

### GitHub staging

At the architecture-freeze point, GitHub `staging` was ahead of the live Staging VPS and contained Generic Production Promotion v2.

## Capability matrix

| Capability | Status | Notes |
|---|---|---|
| Graph-aware Retrieval + Answer v1.3 | FROZEN / VERIFIED | Production core; do not change without regression tests |
| `answer_knowledge.py` | ACTIVE / FROZEN | Production answer layer |
| `graph_search_v1.py` | ACTIVE / FROZEN | Graph-aware retrieval |
| `hybrid_search_v3.py` | ACTIVE / FROZEN | Current hybrid retrieval implementation |
| Resolver stack | ACTIVE / FROZEN | query/document/section/structural resolvers |
| Generic legacy ingestion | LEGACY / PROD-CAPABLE | `ingest_document.py`, `ingest_gdrive_auto.py` |
| HKeL ingestion | ACTIVE SPECIALIZED / PROD-CAPABLE | Uses `parse_hkel_xml_v5.py` |
| Graph reference sync | ACTIVE MAINTENANCE / GUARDED | Manual Production-capable maintenance tools |
| Multimodal Document v2 | IMPLEMENTED | Production and Staging core files match |
| Native PDF text | IMPLEMENTED | Existing v2 extraction |
| Table detection | IMPLEMENTED | Structured rows/columns extracted |
| Structured table retrieval evidence | VPS STAGING DEPLOYED / CI VERIFIED | First-class `structured_table` chunks are deployed; APP146 did not emit a table chunk, so table-specific live canary remains unexercised |
| OCR | IMPLEMENTED | Selective candidate-page OCR |
| Vision | IMPLEMENTED | Selective visual understanding |
| Page-aware routing signals | IMPLEMENTED | Final router decision remains document-level |
| Source-page provenance | IMPLEMENTED | Deterministic page render + SHA metadata |
| Region-level figure evidence | LATER GAP | Page-level Vision exists; region evidence does not |
| Official Source Processing v1 | VPS STAGING LIVE VERIFIED | APP146 multimodal-v2 closed loop to semantic validation and READY_FOR_PRODUCTION_REVIEW at commit 921e899 |
| Source registry / baseline / change detection | M5D LIVE / M5E CI VERIFIED | Persisted reference is live-proven; automatic monitor candidate routing is CI-verified and awaits VPS live proof |
| Scheduled official-source monitoring | NOT OPERATIONAL | Policy says daily; no matching timer in audited deployment |
| APP-145 Production Promotion v1 | VERIFIED / FROZEN | Historical Production milestone |
| Generic Production Promotion v2 | M5A LIVE / M5B CI VERIFIED | APP149 deterministic proposal is live-proven; routine human review replaced by policy qualification in GitHub staging; VPS deploy pending |
| Canonical-text-v1 Production profile | LIVE PROPOSAL + POLICY CONTRACT | APP149 deterministic proposal live-verified; M5B initial-release policy is CI-verified; write authorization remains false |
| Multimodal-v2 Production profile | CONTRACT REGISTERED / WRITE BLOCKED | Profile validates multimodal evidence expectations, but Production authorization is explicitly rejected until writer/validator qualification |
| Learning / Anki source provenance | IMPLEMENTED | Read-only source locator |
| Card generation | IMPLEMENTED | Selected chunks only |
| Original-page media | IMPLEMENTED | Media rendering infrastructure exists |
| Anki package export | IMPLEMENTED | Stable GUID/package verification |
| Anki review sync | IMPLEMENTED | Privacy-minimized read-only snapshot |
| Knowledge analytics | IMPLEMENTED + CI | SR-H |
| Periodic assessment | IMPLEMENTED + CI | SR-I |
| Weekly knowledge reporting | PRODUCTION SCHEDULED | systemd timer present |
| Automatic visual-recall card selection | GAP | Media exists, auto visual card decision does not |
| Anki localhost fail-closed enforcement | HARDENING GAP | Normal wrapper is localhost; direct CLI should fail closed |
| HKeL bootstrap baseline | IMPLEMENTED | `law-watch --bootstrap` |
| HKeL continuous watch mode | GAP | Current script explicitly says watch mode is not yet implemented |
| CLI wrapper deployment as code | PARTIAL GAP | Runtime wrappers exist; not all are reproducibly installed from GitHub |
| Pre-Git Production backups | ARCHIVED HISTORY | VPS-only `pre-*` / backup files; not active capability |
| `poc_stress_ingest.py` | EXPERIMENTAL / PROD-WRITE-CAPABLE | Must not be treated as an approved Production entrypoint |

## GitHub reconciliation

### Production VPS-only top-level files

The audited Production VPS had 71 files not present at GitHub `main`.

All 71 were historical `pre-*` / backup artifacts.

No active top-level Python/YAML capability was found to be missing from GitHub `main`.

Largest historical families:

- `hybrid_search_v3`: 23
- `answer_knowledge`: 16
- `ingest_hkel`: 13
- `graph_search_v1`: 5
- `query_normalizer`: 4

These should remain historical audit material rather than be copied into the active repository.

### Staging reconciliation

The audited VPS Staging root had no top-level local-only code.

GitHub `staging` was ahead of VPS Staging with the Generic Production Promotion v2 implementation.

## Current priority gaps

Priority order:

1. deploy/live-verify M5E automatic Source Monitor integration on VPS Staging;
2. connect CANDIDATE_NEW_VERSION to the existing Staging validation lifecycle;
3. live-verify Production v2 through non-writing verify/prepare gates using a policy-qualified contract;
3. qualify a profile-safe multimodal Production artifact path only after the generic text proof;
4. safe CLI/deployment reconciliation;
5. source-monitor scheduling;
6. HKeL watch modernization;
7. cleanup / retirement.

Completed / deployed:

- M1 structured-table retrieval evidence: CI verified and deployed to VPS Staging; table-specific live chunk proof not exercised by APP146;
- M2 official-source multimodal Staging close-loop: VPS LIVE VERIFIED with APP146, document ID 4, 12 chunks and semantic matches `hinge` / `stopper`;
- M3 release artifact profiles: CI verified and code deployed to VPS Staging; Generic Production v2 operational verification pending;
- M4 VPS Staging qualification: LIVE VERIFIED at commit `921e899`, Production write false;
- M5A APP149 Generic Production v2 proposal: LIVE VERIFIED at commit `4936069`; canonical SHA `a5b4d5a1...`, chunks SHA `4accbc06...`, 8 native-text chunks, Production access/write false;
- M5B Automatic Version Qualification Policy v1: GitHub staging / CI VERIFIED at commit `8b095e1`; routine human review removed, exception review retained;
- M5C Version Signal Extraction v1: VPS STAGING LIVE VERIFIED at commit `55c9dff`; APP149 yielded issue/revision date `2010-12`, stable metadata/content fingerprints, deterministic repeated snapshots, AUTO_QUALIFIED, Production access/write false;
- M5D Version Snapshot Persistence / Comparison v1: VPS STAGING LIVE VERIFIED at commit `a7e353f`; APP149 reference initialized, repeated comparison returned `NO_CHANGE`, Production registry/state untouched;
- M5E Automatic Source Monitor Integration v1: GitHub staging / CI VERIFIED at commit `1b04dea`; baseline changes now route to candidate snapshot comparison without bypassing Staging validation.

## Freeze rules

- APP-145 Promotion v1 is frozen.
- Retrieval / Answer v1.3 is frozen.
- Do not remove legacy files until replacement paths are regression-tested and operationally verified.
- Do not interpret "script exists" as "approved operational capability".
- Do not interpret registry cadence as proof that a scheduler is installed.