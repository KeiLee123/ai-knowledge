#!/usr/bin/env python3
"""M10B-2A: candidate-only, read-only lexical retrieval evidence.

No database, embeddings, network, Drive, timers, filesystem writes or answers.
A lexical smoke test is NOT gold-page, semantic, or answer verification.
"""
import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

from m10_candidate_intake_v1 import STATE_ROOT, valid_sha, sha_file, validate_root
from m10b1_isolated_candidate_v1 import (
    REGISTRY, WORKSPACE_ROOT, CandidateError, digest, locked_reference,
    need, trusted_source, workspace_scope,
)

VERSION = "m10b2a-candidate-lexical-v1"
CASE_VERSION = "registry-canary-v1"
MAX_PDF_BYTES = 50 * 1024 * 1024
MAX_CHUNKS = 5000
WORD_RE = re.compile(r"[a-z0-9]+(?:'[a-z0-9]+)?", re.I)


def canon_hash(payload):
    return digest(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":")).encode("utf-8"))


def words(text):
    return set(WORD_RE.findall(str(text).casefold()))


def compact_text(text):
    return " ".join(str(text or "").casefold().split())


def report_base(source_id, sha):
    return {
        "version": VERSION,
        "source_id": source_id,
        "candidate_id": f"{source_id}:{sha}",
        "candidate_sha256": sha,
        "status": "BLOCKED",
        "reasons": [],
        "environment": "staging",
        "method": "candidate-only-lexical",
        "retrieval_verified": False,
        "gold_page_verified": None,
        "semantic_verified": False,
        "answer_verified": False,
        "production_access": False,
        "production_write": False,
        "write_authorized": False,
        "canonical_promoted": False,
        "accepted_reference_advanced": False,
        "shared_db_access": False,
        "external_vision_api_used": False,
        "proof_written": False,
    }


def candidate_paths(workspace_root, source_id, sha):
    need(re.fullmatch(r"[A-Za-z0-9_.-]+", source_id) is not None,
         "invalid_source_id")
    need(valid_sha(sha), "invalid_candidate_sha")
    root = Path(workspace_root)
    parent = root / "candidates" / source_id / sha
    for node in (root, root / "candidates", root / "candidates" / source_id,
                 parent):
        need(node.is_dir() and not node.is_symlink(), "unsafe_candidate_directory")
    need(parent.resolve(strict=True).is_relative_to(root.resolve(strict=True)),
         "candidate_path_escape")
    pdf = parent / "candidate.pdf"
    evidence = parent / "evidence.json"
    for node in (pdf, evidence):
        need(node.is_file() and not node.is_symlink(), "unsafe_candidate_artifact")
        need(node.resolve(strict=True).parent == parent.resolve(strict=True),
             "candidate_artifact_escape")
    need(not (parent / ".lock").exists(), "candidate_locked")
    return pdf, evidence


def read_evidence(path):
    raw = path.read_bytes()
    need(len(raw) <= 100_000, "oversized_candidate_evidence")
    result = json.loads(raw)
    need(isinstance(result, dict), "invalid_evidence_record")
    return result, digest(raw)


def verify_evidence(e, *, source_id, sha, source, host):
    need(e.get("version") == "m10b1-local-candidate-validation-v1",
         "invalid_m10b1_version")
    need(e.get("status") == "PARSE_VERIFIED" and e.get("route") == "legacy-v1"
         and e.get("policy_decision") == "CANDIDATE_NEW_VERSION",
         "candidate_not_parse_verified")
    need(e.get("source_id") == source_id
         and e.get("candidate_id") == f"{source_id}:{sha}"
         and e.get("candidate_sha256") == sha,
         "evidence_candidate_identity_mismatch")
    for key in ("production_access", "production_write", "write_authorized",
                "canonical_promoted", "accepted_reference_advanced",
                "retrieval_verified"):
        need(e.get(key) is False, "unsafe_evidence_flag:" + key)
    need(e.get("environment") == "staging", "wrong_environment")
    need(e.get("trusted_identity") == {
        "authority_code": source["authority_code"],
        "document_code": source["document_code"],
        "canonical_host": host,
    }, "evidence_trusted_identity_mismatch")
    need(e.get("document_code_in_text") is True,
         "unverified_document_identity")
    for key in ("reference_sha256_before", "reference_sha256_after",
                "manifest_sha256", "monitor_output_sha256"):
        need(valid_sha(e.get(key)), "invalid_evidence_sha:" + key)
    need(e["reference_sha256_before"] == e["reference_sha256_after"],
         "prior_reference_drift")
    need(type(e.get("page_count")) is int and 0 < e["page_count"] <= 500,
         "invalid_page_count")


def rank_lexical(chunks, query, top_k):
    terms = words(query)
    need(terms and len(terms) >= 2, "insufficient_query_terms")
    matches = []
    for chunk in chunks:
        content = chunk["content"]
        overlap = sorted(terms & words(content))
        if not overlap:
            continue
        matches.append({
            "chunk_id": chunk["chunk_index"],
            "page_number": chunk["page_start"],
            "evidence_origin": chunk["metadata"]["evidence_origin"],
            "matched_query_tokens": overlap,
            "score": len(overlap),
            "content_sha256": digest(content.encode("utf-8")),
            "snippet": content[:220],
            "_full_content": content,
        })
    matches.sort(key=lambda c: (-c["score"], c["page_number"], c["chunk_id"]))
    return matches[:top_k]


def evaluate_terms(hits, expected_terms):
    need(isinstance(expected_terms, list) and expected_terms
         and all(isinstance(t, str) and t.strip()
                 and re.fullmatch(r"[a-zA-Z0-9 -]{2,80}", t.strip())
                 for t in expected_terms),
         "invalid_or_empty_expected_terms")
    content = compact_text(" ".join(x["_full_content"] for x in hits))
    matched = [term for term in expected_terms
               if compact_text(term) in content]
    missing = [term for term in expected_terms
               if compact_text(term) not in content]
    return matched, missing


def verify_chunks(manifest, chunks, sha):
    count = manifest["document"]["page_count"]
    units = {x["page_number"]: x for x in manifest["units"]
             if x.get("unit_type") == "page" and type(x.get("page_number")) is int}
    need(len(units) == count and set(units) == set(range(1, count + 1)),
         "partial_or_invalid_page_map")
    need(0 < len(chunks) <= MAX_CHUNKS, "empty_or_excessive_chunks")
    for i, chunk in enumerate(chunks):
        need(chunk.get("chunk_index") == i, "invalid_chunk_order")
        page = chunk.get("page_start")
        meta = chunk.get("metadata") or {}
        need(type(page) is int and 1 <= page <= count
             and chunk.get("page_end") == page and meta.get("page_number") == page,
             "invalid_chunk_page")
        need(meta.get("evidence_origin") == "native_text"
             and meta.get("modality") == "text"
             and meta.get("derived") is False,
             "unsupported_chunk_provenance")
        content = chunk.get("content")
        need(isinstance(content, str) and bool(content.strip()),
             "empty_chunk")
        need(compact_text(content) in compact_text(units[page].get("text")),
             "chunk_not_traceable_to_page")


def run(source_id, sha, *, state_root=STATE_ROOT,
        workspace_root=WORKSPACE_ROOT, top_k=5):
    result = report_base(source_id, sha)
    try:
        need(type(top_k) is int and 1 <= top_k <= 10, "invalid_top_k")
        root = validate_root(state_root)
        workspace = workspace_scope(workspace_root, root)
        source, host = trusted_source(source_id)
        need((source.get("canonical_text_ingestion") or {}).get("language") == "en",
             "unsupported_language")
        config = source.get("staging_validation") or {}
        query = config.get("query")
        expected = config.get("expect_terms")
        need(isinstance(query, str) and query.strip(),
             "missing_registry_test_query")
        need(isinstance(expected, list) and bool(expected),
             "missing_expected_terms")
        pdf, evidence_file = candidate_paths(workspace, source_id, sha)
        evidence, evidence_sha = read_evidence(evidence_file)
        verify_evidence(evidence, source_id=source_id, sha=sha,
                        source=source, host=host)
        need(pdf.stat().st_size <= MAX_PDF_BYTES, "pdf_too_large")
        need(sha_file(pdf) == sha, "candidate_pdf_sha_mismatch")
        reference, previous, before = locked_reference(
            root, source_id, evidence["reference_sha256_before"], source, host)
        result["m10b1_evidence_sha256"] = evidence_sha
        result["reference_sha256_before"] = before
        result["manifest_sha256_expected"] = evidence["manifest_sha256"]
        from extract_document_v2 import build_manifest
        from route_document_v2 import assess_manifest
        from build_multimodal_chunks_v2 import (
            BUILDER_VERSION, build_chunks,
        )
        from version_signal_extractor_v1 import (
            build_version_signal_snapshot, compare_version_snapshots,
        )
        from version_qualification_policy_v1 import evaluate_version_candidate
        manifest = build_manifest(pdf)
        need(manifest.get("source", {}).get("sha256") == sha,
             "manifest_candidate_sha_mismatch")
        need(manifest.get("schema_version") == "document-manifest-v2"
             and manifest.get("selection", {}).get("page_numbers") is None,
             "unsupported_partial_manifest")
        actual_manifest_sha = canon_hash(manifest)
        result["manifest_sha256_actual"] = actual_manifest_sha
        need(actual_manifest_sha == evidence["manifest_sha256"],
             "manifest_hash_or_parser_drift")
        need(manifest["document"]["page_count"] == evidence["page_count"],
             "page_count_drift")
        route = assess_manifest(manifest, allow_partial=False)
        need(route["decision"]["production_decision_valid"] is True
             and route["decision"]["recommended_pipeline"] == "legacy-v1",
             "unsupported_or_partial_route")
        current = build_version_signal_snapshot(
            source_file=pdf, manifest=manifest, source=source)
        signals = compare_version_snapshots(
            previous, current, staging_validation_verified=False,
            deterministic_release=False)
        policy = evaluate_version_candidate(signals)
        need(policy["decision"] == "CANDIDATE_NEW_VERSION"
             and current["normalized_content_fingerprint"]
             == evidence["normalized_content_fingerprint"],
             "version_policy_or_fingerprint_drift")
        chunks = build_chunks(manifest, target_chars=1800, overlap_chars=0)
        verify_chunks(manifest, chunks, sha)
        ranked = rank_lexical(chunks, query, top_k)
        matched, missing = evaluate_terms(ranked, expected)
        need(sha_file(pdf) == sha, "candidate_modified_during_search")
        after = digest(reference.read_bytes())
        need(after == before == evidence["reference_sha256_after"],
             "accepted_reference_changed_during_search")
        need(digest(evidence_file.read_bytes()) == evidence_sha,
             "evidence_changed_during_search")
        result.update({
            "status": ("LEXICAL_CANARY_PASSED" if ranked and not missing
                       else "LEXICAL_CANARY_FAILED"),
            "reasons": ([] if ranked and not missing else
                        ["no_retrieved_evidence_or_missing_expected_terms"]),
            "candidate_page_count": evidence["page_count"],
            "reference_sha256_after": after,
            "chunk_builder_version": BUILDER_VERSION,
            "chunk_count": len(chunks),
            "retrieval_config": {"target_chars": 1800, "overlap_chars": 0,
                                 "top_k": top_k, "case_version": CASE_VERSION},
            "registry_query": query,
            "expected_terms": expected,
            "matched_terms": matched,
            "missing_terms": missing,
            "citation_present": bool(ranked),
            "citation_page_gold_verified": None,
            "ranked_evidence": [
                {k: v for k, v in hit.items() if k != "_full_content"}
                for hit in ranked
            ],
        })
        return result
    except (OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
        result["status"] = "BLOCKED"
        result["reasons"] = [f"candidate_lexical_failed:{type(exc).__name__}:{exc}"]
        return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--candidate-sha", required=True)
    parser.add_argument("--state-root", type=Path, default=STATE_ROOT)
    parser.add_argument("--workspace-root", type=Path, default=WORKSPACE_ROOT)
    parser.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args(argv)
    result = run(args.source, args.candidate_sha, state_root=args.state_root,
                 workspace_root=args.workspace_root, top_k=args.top_k)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 2 if result["status"] == "BLOCKED" else 0


if __name__ == "__main__":
    sys.exit(main())
