# HKeL Cap.123 manual Staging watch

Issue #59 / KB-06 bounded engineering delivery. Base staging:
`afefeda2ca22de0d9351b6565a08ae53d2938abe`. **Draft, not deployed; not a
scheduled Continuous Watch, Drive/index integration or legal approval.**

## Real failure and reuse

Read-only VPS/source audit on 2026-11-22 found that `law_watch.py` has useful
bootstrap code but its normal mode is still a placeholder, its paths point to
Production, and Staging has no HKeL baseline. `ingest_hkel.py` also has
Production DB defaults. Neither existing entry point is a safe Staging watch.

`hkel_watch_staging_v1.py` is a replaceable single-chapter adapter, not a new
parser/registry/ingestor: reuse `law_watch.build_chapter_index`,
`get_current_version`, `parse_hkel_xml_v5.walk/deduplicate`, and existing M10B
`safe_mkdir`, `write_candidate_copy`, `atomic_bundle`. The latter uses atomic
hard links: the storage path targets Linux; lack of hard-link support blocks
safely. Existing source files, registries, approved SHAs, M8/M9 and Frozen v1.3
are unchanged.

The audit independently obtained the actual Cap123 XML (795667 bytes, SHA256
`f5f297444f92b43adfaba3accb159e954ea68a230765dc015dd82a831229272b`) from
the current official package. It matches the observed baseline, dated
2026-03-01. The existing parser produces 1925 records and 1883 exact-ref-eligible
records with no duplicate canonical refs. Those are mechanical observations,
not professional semantic/currentness signoff, and the SHA is audit evidence,
not a new pinned canonical-source approval in this adapter.

## Operator modes

The CLI requires the clean `staging` checkout at `/opt/ai-knowledge-staging`.
Chapter is fixed to CAP_123, registry is the existing checkout's legislation
registry, state is `/var/lib/jason-os/hkel-watch-staging`. No caller-supplied
state root, registry, remote or DB endpoint. Functions accept named synthetic
fixture roots/bytes for offline tests; that is not operational authorization.

Default, no network or writes:

```bash
.venv/bin/python -B hkel_watch_staging_v1.py
```

Missing baseline means `BASELINE_REQUIRED`, never `NO_CHANGE`. With an existing
valid baseline but no fresh input, return `READY_FOR_OFFICIAL_CHECK`, not a
claim that the source was checked. Explicit `--fetch-official` reads official
metadata and just the selected XML into memory; it does not create state.
Alternatively a read-only inspection can pass `--manifest` and `--xml` files
under the fixed state `incoming/` directory. These are labelled
`operator-supplied`; offline input cannot authorize CLI storage writes.

Only after separately approving the exact operation, fresh official fetch
plus `--initialize-baseline --confirm-staging-write` can initialize the new
isolated baseline. Only fresh fetch plus
`--save-candidate --confirm-staging-write` can save a changed edition. These
flags describe capability; this Draft does not authorize using them on VPS.

Storage layout:

```text
hkel-watch-staging/
  baseline.json                     # create once; no automatic replacement
  editions/CAP_123/<edition-id>/
    source.xml
    edition.json                    # first observation retained immutably
  .lock                             # exclusive write-mode lock
```

Edition ID hashes XML SHA, publisher identity/version/member, registry bytes
SHA and attribution. A changed weekly catalogue SHA alone does not create a
new edition: the first saved observation is retained and each current JSON
report separately records the freshly read manifest SHA. Reruns verify stored
bytes/record binding; they do not overwrite evidence. Another edition cannot
replace an initialized baseline. Candidate approval/accepted-reference
advancement is deliberately absent and needs its own reviewed workflow.

`state_write_attempted` and `partial_state_may_exist` describe write failures:
an interrupted attempt may leave partial evidence for operator review. Existing
stale locks/artifacts are not deleted automatically. Do not clear history or
retry by replacing a baseline. Per-run locks are removed only when acquired by
that process. Group/world-writable state roots and symlink paths are refused.

## Source, download and output contract

Only the fixed English master JSON and Caps1–300 archive on
`resource.data.one.gov.hk` are requested. Metadata must have one Cap123 and one
current version, matching registry title/chapter, known InEffect/status1,
no pencil mark, fixed member and official web/resource URLs. XML must match
HKLM ordinance and Dublin Core metadata namespaces, chapter, edition date,
publisher, language and rights; DTD/entities are refused. Reuse the existing
parser and hold empty/duplicate canonical-reference output.

Do not infer byte equality from version date. Compare the full XML SHA and
edition fields. A same-date byte change returns `CHANGED_REVIEW_REQUIRED`.
Accepted baseline and registry are rechecked around network/parse/writes.

The official archive is about225MiB; never fall back to downloading it whole.
Use strict HTTP206 ranges, exact Content-Range, strong ETag/If-Match and matching
response ETag; refuse redirects, encrypted/symlink/duplicate members and unknown
compression. Limits:10MiB manifest,2MiB XML,4MiB per range,8MiB range responses,
20 range requests; archive metadata capped at512MiB. A60-second deadline is
checked between reads, with at most15-second per-connection/socket timeout;
it is not an external process kill timer. ZIP CRC/size and extracted XML SHA
are checked; **whole-archive SHA is not verified**.

Reports go to stdout, without XML snippets/raw provider diagnostics. They
include source/edition identity, manifest/registry/XML hashes, parser statistics,
baseline before/after hashes and bounded transport evidence. Current/source
flags are publisher observations, not independent legal applicability. Always
false: Production access/write, Drive write, DB access, model use, scheduled
watch, automatic baseline advancement, legal-currentness/semantic verification.

| Status | Meaning / CLI exit |
| --- | --- |
| `BASELINE_REQUIRED` | No accepted isolated reference, no equality assertion;3 |
| `READY_FOR_OFFICIAL_CHECK` | Local readiness only;0 |
| `NO_CHANGE` | Fresh metadata/XML match the isolated baseline;0 |
| `CHANGED_REVIEW_REQUIRED` | Change held for review, even if explicitly staged;3 |
| `BASELINE_INITIALIZED` / `BASELINE_ALREADY_INITIALIZED` | Explicit isolated initialization/idempotent rerun;0 |
| `BLOCKED` | Unsafe/ambiguous/missing input, drift or transport/storage failure;2 |

## Validation and remaining gates

Focused synthetic HTTP/XML/storage tests run in the existing Validation
workflow: missing baseline, identity/date/namespace mismatch, same/different
edition and bytes, immutable rerun, stale lock/partial write, tamper, reference
and registry drift, symlink/Production-path refusal, transport bounds and CLI
confirmation. No real network/DB/service in CI. Local actual official-source
read-only smoke is separate from synthetic CI and creates no baseline.

Not verified: deployed CLI, real confirmed Staging initialization/candidate
save, actual changed official Cap123 edition, scheduled operation, HKeL Drive
destination/readback, DB/index, independent professional semantics/currentness.
The earlier source audit and PR117 runtime evidence do not deploy this adapter.

Next: review the Draft's exact-head CI and bounded modes. Then separately
approve a fixed-SHA VPS isolated check/initialization, if desired. Do not
auto-merge/deploy, create a timer or send HKeL through the BD-only Drive writer.
Rollback: leave the standalone adapter unused; no active caller/service or
migration. Retain any later explicitly created baseline/candidate history.

Decision/source links: [Beta contract](https://docs.google.com/document/d/1dfIGsY_VDwXS_B-DSlNtAB8SkOsvGkx5b-owgqSgQMQ/edit),
[roadmap KB06/07](https://docs.google.com/document/d/1se_pKQcZPb0ZZxRZIGSOmwH4lDD5rkeK5-FRlMPydxc/edit),
[official catalogue](https://data.gov.hk/en-data/dataset/hk-doj-hkel-list-of-legislation-current),
[JSON dictionary](https://www.elegislation.gov.hk/datagovhk/hkel_list_json-dictionary_en.pdf),
[reuse terms and attribution](https://data.gov.hk/en/terms-and-conditions).

## 2026-11-22 real Linux source-read blocker and proposed fix

Approved VPS sync to PR118 merge `2eae0ad` succeeded; default CLI correctly
returned BASELINE_REQUIRED. Fresh official read was BLOCKED: the selected
central-directory name uses `cap_123_en_c\\cap_123_20260301000000_en_c.xml`,
while metadata uses `/`. Windows ZipInfo.filename silently normalizes this;
Linux does not. Read-only VPS diagnosis found zero literal matches and exactly
one separator-normalized match, with the same manifest SHA/archive ETag.

The feature fix compares ZipInfo.orig_filename, replacing only backslashes
with forward slashes. No case folding, path resolution or traversal collapse;
NUL suffixes remain mismatches. Slash/backslash aliases together are ambiguous
and refused. Continue opening the unique ZipInfo object with existing
CRC/size/ETag/metadata checks. No canonical source/member/hash change.

The fix is a separate Draft, not deployed. Original VPS read failure remains
failed acceptance until corrected code receives separately approved runtime
validation. No baseline was initialized; service/source hashes stayed intact.
