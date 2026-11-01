#!/usr/bin/env python3
"""Read-only adapter: reconcile existing extractor audit and raster evidence.

Never approves blankness, source semantics, writer access or deployment.
Reports are bounded metadata JSON; no source PDF, network or database access.
"""
import argparse
import json
from pathlib import Path

VERSION = "document-ingest-evidence-reconciliation-v1"
MAX_REPORT_BYTES = 300_000
MAX_CANDIDATES = 150


class EvidenceRefused(RuntimeError):
    pass


def load_report(path):
    p = Path(path)
    if not p.is_file() or p.is_symlink() or not 0 < p.stat().st_size <= MAX_REPORT_BYTES:
        raise EvidenceRefused("report_path_or_size_refused")
    try:
        result = json.loads(p.read_text(encoding="utf-8"))
    except (UnicodeError, ValueError) as e:
        raise EvidenceRefused("report_json_invalid") from e
    if not isinstance(result, dict):
        raise EvidenceRefused("report_shape_invalid")
    return result


def reconcile(audit, render=None):
    """Only exact-source, exact-page, strict 72-DPI evidence counts as matched.

    Matched means evidence agrees; it is NOT release approval.
    """
    issues = set()
    def flag(code):
        issues.add(code)

    if not isinstance(audit, dict) or (render is not None and not isinstance(render, dict)):
        raise EvidenceRefused("report_shape_invalid")
    doc = audit.get("document") or {}
    source = audit.get("source") or {}
    if audit.get("version") != "document-ingest-quality-audit-v1" or (
            audit.get("audit_mode") != "bounded_batches_full_document_coverage"):
        flag("AUDIT_CONTRACT_UNVERIFIED")
    count, covered = doc.get("physical_pages"), doc.get("pages_covered")
    if (type(count) is not int or not 0 < count <= 500
            or covered != count or doc.get("coverage_complete") is not True):
        flag("AUDIT_FULL_PAGE_COVERAGE_UNVERIFIED")
    sha, size = source.get("observed_sha256"), source.get("size_bytes")
    if (not isinstance(sha, str) or len(sha) != 64
            or any(c not in "0123456789abcdef" for c in sha)
            or type(size) is not int or not 100 <= size <= 20_000_000
            or source.get("expected_sha256_matched") is not True):
        flag("AUDIT_SOURCE_IDENTITY_UNVERIFIED")
    if audit.get("status") != "MECHANICAL_CHECKS_PASS_LIMITED" or audit.get("issue_codes") != []:
        flag("AUDIT_ISSUES_OR_UNVERIFIED")
    if audit.get("database_access") is not False or audit.get("production_write") is not False:
        flag("AUDIT_SIDE_EFFECT_CONTRACT_UNVERIFIED")

    candidates = doc.get("extractor_blank_candidate_pages")
    counts = doc.get("no_native_text_class_counts") or {}
    if (not isinstance(candidates, list)
            or any(type(p) is not int for p in candidates)
            or candidates != sorted(set(candidates))
            or any(p < 1 or type(count) is not int or p > count for p in candidates)
            or len(candidates) != counts.get("extractor_blank_candidate")):
        flag("CANDIDATE_PAGE_IDENTITIES_INVALID")
        candidates = []
    if len(candidates) > MAX_CANDIDATES:
        flag("CANDIDATE_RANGE_EXCEEDS_BOUNDED_LIMIT")

    page_diagnostics = []
    if candidates:
        if candidates != list(range(candidates[0], candidates[-1] + 1)):
            flag("CANDIDATES_NONCONTIGUOUS_REQUIRE_SEPARATE_PROBES")
        if render is None:
            flag("RASTER_REPORT_MISSING")
        else:
            rd = render.get("document") or {}
            pages = render.get("pages")
            if (rd.get("source_sha256") != sha or rd.get("source_size_bytes") != size
                    or rd.get("physical_pages") != count):
                flag("RASTER_SOURCE_IDENTITY_MISMATCH")
            if (rd.get("first_page") != candidates[0]
                    or rd.get("last_page") != candidates[-1]
                    or rd.get("pages_rendered") != len(candidates)
                    or not isinstance(pages, list)
                    or len(pages) != len(candidates)
                    or [v.get("page") if isinstance(v, dict) else None
                        for v in pages] != candidates):
                flag("RASTER_PAGE_COVERAGE_MISMATCH")
            if (render.get("version") != "pdf-blank-render-probe-v1"
                    or rd.get("render_scale") != 1.0
                    or rd.get("render_dpi") != 72
                    or rd.get("grayscale") is not True
                    or rd.get("annotations_rendered") is not True
                    or rd.get("higher_resolution_render_verified") is not False
                    or rd.get("independent_pdf_content_semantics_verified") is not False
                    or render.get("database_access") is not False
                    or render.get("production_write") is not False
                    or render.get("ocr_performed") is not False):
                flag("RASTER_METHOD_OR_SIDE_EFFECTS_INVALID")
            if isinstance(pages, list) and len(pages) == len(candidates):
                for expected_page, item in zip(candidates, pages):
                    if not isinstance(item, dict) or item.get("page") != expected_page:
                        flag("RASTER_PAGE_COVERAGE_MISMATCH")
                        continue
                    n, total = item.get("nonwhite_pixels"), item.get("pixel_count")
                    if (type(n) is not int or type(total) is not int
                            or not 0 <= n <= total or total < 1):
                        flag("RASTER_PIXEL_METRICS_INVALID")
                        continue
                    page_diagnostics.append({
                        "page": expected_page,
                        "nonwhite_pixels": n,
                        "diagnostic": ("RASTER_NONWHITE_AUTO_HOLD"
                                       if n else "RASTER_WHITE_LIMITED_NOT_SEMANTIC_PROOF"),
                    })
                if len(page_diagnostics) == len(candidates):
                    nonwhite = [p["page"] for p in page_diagnostics
                                if p["nonwhite_pixels"] > 0]
                    expected_status = ("AUTO_HOLD_RENDERED_NONWHITE" if nonwhite
                                       else "RENDER_NO_NONWHITE_DETECTED_LIMITED")
                    if (rd.get("nonwhite_detected_pages") != nonwhite
                            or rd.get("no_nonwhite_detected_count") != len(candidates) - len(nonwhite)
                            or rd.get("all_rendered_pages_have_no_nonwhite") is not (not nonwhite)
                            or render.get("status") != expected_status):
                        flag("RASTER_AGGREGATE_INCONSISTENT")
    elif render is not None:
        flag("UNEXPECTED_RASTER_REPORT")

    return {
        "version": VERSION,
        "status": "AUTO_HOLD_UNVERIFIED",
        "reconciliation": ("EVIDENCE_MATCHED_LIMITED" if not issues
                           else "EVIDENCE_MISMATCH_OR_MISSING"),
        "reason_codes": sorted(issues),
        "source_sha256": sha if isinstance(sha, str) else None,
        "blank_candidate_count": len(candidates),
        "page_diagnostics": page_diagnostics,
        "semantic_blankness_verified": False,
        "semantic_table_accuracy_verified": False,
        "database_roundtrip_verified": False,
        "staging_database_write_authorized": False,
        "production_write_authorized": False,
        "notice": ("Matched raster metadata remains limited mechanical evidence. "
                   "No automatic blank-page waiver or writer permission."),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit-report-json", required=True)
    parser.add_argument("--render-report-json")
    parser.add_argument("--report-json", required=True)
    args = parser.parse_args()
    audit = load_report(args.audit_report_json)
    render = load_report(args.render_report_json) if args.render_report_json else None
    report = reconcile(audit, render)
    output = Path(args.report_json)
    if (not output.parent.is_dir() or output.is_symlink() or output.exists()):
        raise EvidenceRefused("output_path_refused")
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n",
                      encoding="utf-8")
    print("RECONCILIATION_REPORT_WRITTEN")


if __name__ == "__main__":
    try:
        main()
    except (EvidenceRefused, ValueError, OSError) as exc:
        raise SystemExit("EVIDENCE_RECONCILIATION_REFUSED: " + str(exc)) from None
