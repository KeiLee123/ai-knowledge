#!/usr/bin/env python3
"""KB-01 bounded READ-ONLY operator probe for pinned real APP145/149 PDFs.

This is not a deployment command, not a search-quality test, and does not
assert professional accuracy or legal applicability. Requires a clean existing
Staging checkout, matching approved Registry/baselines, two locally cached PDFs,
and the exact PR verifier module. No DB/Drive/model writes or public network.
"""

import argparse
import hashlib
from pathlib import Path

import beta_ask_staging_v1 as qa
import citation_integrity_staging_v1 as verifier

# Known historic canary identities; a changed edition MUST be a separate review.
PINNED = {
    "BD_PNAP_APP145": "dc3262cc55c5fd79d29f337fd811cdd871543f59d795972d9f30f558e313127c",
    "BD_PNAP_APP149": "a5b4d5a1af5f4a32b43973db33d95436f9390e8e2da77747ee666015077bb1a8",
}
CASES = (
    ("Q01", "BD_PNAP_APP145", 115,
     "According to APP145 who is responsible for enforcement between BD and FSD?"),
    ("Q06", "BD_PNAP_APP145", 116,
     "What happens if complying with the fire safety requirements is difficult?"),
    ("Q09", "BD_PNAP_APP149", 121,
     "How is temporary absence of an authorized signatory dealt with in APP149?"),
    ("Q14", "BD_PNAP_APP149", 124,
     "What does Appendix A to APP149 contain about the authorized signatory?"),
    ("Q15", "BD_PNAP_APP149", 125,
     "What does Appendix B to APP149 contain about temporary absence?"),
)


def checked_original(source_id, filename):
    source = qa.approved_source(source_id)  # Existing trusted Registry/baseline
    if source["checksum"] != PINNED[source_id]:
        raise RuntimeError(source_id + ": BASELINE_DRIFT_HOLD")
    original = Path(filename)
    actual = hashlib.sha256(original.read_bytes()).hexdigest()
    if actual != PINNED[source_id]:
        raise RuntimeError(source_id + ": ORIGINAL_PDF_SHA_MISMATCH_HOLD")
    print(source_id, "APPROVED_SOURCE_AND_ORIGINAL_SHA_MATCH",
          source["checksum"][:16], "currentness=NOT_VERIFIED")
    return source


def select_literal_from_indexed_chunk(packet, source, chunk_id, pdf_path):
    matches = [item for item in packet["evidence"]
               if item.get("chunk_id") == chunk_id]
    if len(matches) != 1:
        raise RuntimeError("CHUNK_ID_MISSING_OR_AMBIGUOUS_HOLD:" + str(chunk_id))
    item = matches[0]
    # Deterministic non-semantic candidate excerpts FROM the indexed Chunk.
    # Try bounded windows, never claim the matching text answers the question.
    words = verifier.normalize(item["content"]).split()
    refusals = []
    for start in range(0, len(words), 5):
        candidate = " ".join(words[start:start + 18])
        if not 45 <= len(candidate) <= 250:
            continue
        try:
            verified = verifier.verify_quote(
                packet, source, item["id"], candidate, pdf_path)
        except verifier.CitationRefused as error:
            refusals.append(str(error))
            continue
        return verified
    raise RuntimeError(
        "NO_LITERAL_PDF_PAGE_OVERLAP_HOLD:" + str(chunk_id)
        + ":reasons=" + ",".join(sorted(set(refusals)))[:200])


def run(pdfs):
    qa.check_checkout()  # Existing staging branch/clean worktree/runtime gate
    sources = {sid: checked_original(sid, path) for sid, path in pdfs.items()}
    for label, sid, chunk_id, question in CASES:
        packet = qa.build_packet(sid, question)
        coverage = packet.get("retrieval_coverage", {})
        if coverage.get("complete_index_coverage") is not True:
            raise RuntimeError(label + ":INCOMPLETE_INDEX_COVERAGE_HOLD")
        if qa.currentness_abstention(packet) is not None:
            raise RuntimeError(label + ":UNEXPECTED_CURRENTNESS_HOLD")
        verified = select_literal_from_indexed_chunk(
            packet, sources[sid], chunk_id, pdfs[sid])
        if verified["semantic_answer_support"] != "NOT_EVALUATED":
            raise RuntimeError(label + ":INVALID_SEMANTIC_SUCCESS_CLAIM")
        print(label, "MECHANICAL_PDF_PAGE_QUOTE_MATCH",
              "chunk=" + str(chunk_id),
              "page=" + str(verified["physical_page"]),
              "evidence=" + verified["evidence_id"],
              "excerpt=" + repr(verified["quote"][:110]))
    # The existing currentness gate must remain the authority for current law.
    currentness = qa.currentness_abstention({
        "question": "截至2026年11月10日，APP149 是否仍然有效？",
        "source": sources["BD_PNAP_APP149"],
    })
    if currentness is None or currentness["status"] != "CURRENTNESS_UNVERIFIED_ABSTAIN":
        raise RuntimeError("CURRENTNESS_NEGATIVE_CASE_HOLD")
    print("Q19", "CURRENTNESS_UNVERIFIED_ABSTAIN", "PASS")
    print("SUMMARY KB01_REAL_PINNED_PDF_MECHANICAL_PROBE_PASS")
    print("SEMANTIC_RELEVANCE_NOT_EVALUATED; CURRENT_LEGAL_EFFECT_NOT_VERIFIED")
    print("NO_DB_WRITE; NO_STAGING_DEPLOY; NO_PRODUCTION_CHANGE")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app145-pdf", required=True)
    parser.add_argument("--app149-pdf", required=True)
    args = parser.parse_args()
    run({"BD_PNAP_APP145": args.app145_pdf,
         "BD_PNAP_APP149": args.app149_pdf})


if __name__ == "__main__":
    main()
