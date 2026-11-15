#!/usr/bin/env python3
"""G3-A read-only PDF text-coverage diagnostics for immutable PNBI Staging originals.

This emits review evidence only. It cannot certify tables, printed page numbering,
visual integrity, a PDF signature or legal currentness. No Drive/DB writes.
"""
import argparse
import hashlib
from pathlib import Path
import sys

import pnbi_g1_pdf_probe_v1 as g1
from pnbi_g2_drive_staging_archive_v1 import EXPECTED


MIN_NORMALIZED_NONSPACE_CHARS = 30


def verify_exact_original(number, data):
    expected_sha, expected_size, _ = EXPECTED[number]
    if len(data) != expected_size:
        raise ValueError("G3A_ORIGINAL_BYTE_COUNT_MISMATCH_HOLD")
    if hashlib.sha256(data).hexdigest() != expected_sha:
        raise ValueError("G3A_ORIGINAL_SHA256_MISMATCH_HOLD")
    if not data.startswith(b"%PDF-"):
        raise ValueError("G3A_NOT_PDF_HOLD")


def split_extracted_pages(raw_text, expected_pages):
    parts = raw_text.split("\f")
    # Poppler commonly ends with a final page-break, possibly with whitespace.
    if len(parts) == expected_pages + 1 and not parts[-1].strip():
        parts.pop()
    if len(parts) != expected_pages:
        raise ValueError("G3A_EXTRACTED_PAGE_COUNT_MISMATCH_REVIEW_HOLD")
    return parts


def page_metrics(pages):
    counts = [len("".join(page.split())) for page in pages]
    zero = [idx + 1 for idx, count in enumerate(counts) if count == 0]
    low = [idx + 1 for idx, count in enumerate(counts)
           if 0 < count < MIN_NORMALIZED_NONSPACE_CHARS]
    return {"counts": counts, "zero": zero, "low": low,
            "nonempty": sum(n > 0 for n in counts)}


def inspect(number, data):
    if number not in EXPECTED:
        raise ValueError("G3A_NOT_APPROVED_PNBI_HOLD")
    verify_exact_original(number, data)
    info = g1.run_poppler(["pdfinfo", "-"], data)
    pages = g1.pdf_page_count(info)
    if pages != EXPECTED[number][2]:
        raise ValueError("G3A_PHYSICAL_PAGE_COUNT_CHANGED_HOLD")
    extracted = g1.run_poppler(["pdftotext", "-layout", "-enc", "UTF-8", "-", "-"], data)
    per_page = split_extracted_pages(extracted, pages)
    g1.validate_document_id("\n".join(per_page[:min(3, pages)]), number)
    result = page_metrics(per_page)
    result.update({"number": number, "pages": pages,
                   "sha256": EXPECTED[number][0], "bytes": len(data)})
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pnbi", required=True, type=int, choices=range(1, 11))
    parser.add_argument("--file", required=True, type=Path)
    args = parser.parse_args(argv)
    # Explicit bounded input: only G2-verified originals, at most 25MB.
    with args.file.open("rb") as source:
        data = source.read(g1.MAX_PDF_BYTES + 1)
    if len(data) > g1.MAX_PDF_BYTES:
        raise ValueError("G3A_INPUT_TOO_LARGE_HOLD")
    result = inspect(args.pnbi, data)
    print("G3A_PNBI_{number:02d}_READONLY_DIAGNOSTIC | SHA256={sha256} | BYTES={bytes} | "
          "PHYSICAL_PAGES={pages} | NONEMPTY_TEXT_PAGES={nonempty}".format(**result))
    print("G3A_ZERO_TEXT_PHYSICAL_PAGES=" + repr(result["zero"]))
    print("G3A_LOW_TEXT_PHYSICAL_PAGES=" + repr(result["low"]))
    print("G3A_NONSPACE_CHARS_PER_PHYSICAL_PAGE=" + ",".join(
        f"{i}:{c}" for i, c in enumerate(result["counts"], 1)))
    print("G3A_REVIEW_REQUIRED: physical-to-printed page mapping, tables, figures, "
          "annexes, layout fidelity and legal currentness NOT VERIFIED")
    print("G3A_NO_DRIVE_WRITE; NO_DB_WRITE; NO_REGISTRY; NO_CURRENT; NO_PRODUCTION")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print("G3A_HOLD: " + str(error), file=sys.stderr)
        sys.exit(1)
