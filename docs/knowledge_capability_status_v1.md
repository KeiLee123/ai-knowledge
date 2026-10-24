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
- Audited commit: `f58dc65826266563c55e85d195fe93923611f00d`

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
| Structured table retrieval evidence | GITHUB STAGING / CI VERIFIED | First-class `structured_table` chunks with table provenance metadata; VPS deployment pending |
| OCR | IMPLEMENTED | Selective candidate-page OCR |
| Vision | IMPLEMENTED | Selective visual understanding |
| Page-aware routing signals | IMPLEMENTED | Final router decision remains document-level |
| Source-page provenance | IMPLEMENTED | Deterministic page render + SHA metadata |
| Region-level figure evidence | LATER GAP | Page-level Vision exists; region evidence does not |
| Official Source Processing v1 | LIVE-VERIFIED STAGING | Text route closed-loop; multimodal stops at handoff |
| Source registry / baseline / change detection | IMPLEMENTED | New checksum requires review |
| Scheduled official-source monitoring | NOT OPERATIONAL | Policy says daily; no matching timer in audited deployment |
| APP-145 Production Promotion v1 | VERIFIED / FROZEN | Historical Production milestone |
| Generic Production Promotion v2 | GITHUB STAGING / CI VERIFIED | Not deployed to VPS at audited point |
| Generic v2 multimodal promotion | GAP | Current v2 contract is legacy-v1 / text-specific |
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

1. multimodal official-source Staging close-loop;
2. release-artifact profile abstraction;
3. live VPS Staging verification of Generic Production Promotion v2;
4. safe CLI/deployment reconciliation;
5. source-monitor scheduling;
6. HKeL watch modernization;
7. cleanup / retirement.

Completed in GitHub `staging` / CI verified:

- structured-table retrieval evidence (M1); VPS deployment pending.

## Freeze rules

- APP-145 Promotion v1 is frozen.
- Retrieval / Answer v1.3 is frozen.
- Do not remove legacy files until replacement paths are regression-tested and operationally verified.
- Do not interpret "script exists" as "approved operational capability".
- Do not interpret registry cadence as proof that a scheduler is installed.