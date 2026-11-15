#!/usr/bin/env python3
"""G1: in-memory official PNBI PDF provenance + structure probe; no archive or DB write.

Not a PDF signature verifier and not a legal-currentness assertion.
Requires installed pdfinfo and pdftotext (Poppler); fails closed if absent.
"""
import argparse
import hashlib
import re
import subprocess
import sys
from urllib.request import Request, build_opener

from pnbi_g0_readonly_probe_v1 import INDEX, NoRedirect, extract, extract_detail

MAX_INDEX_BYTES = 2_000_000
MAX_PDF_BYTES = 25_000_000


def fetch_official_index(opener, source="detail"):
    request = Request(
        INDEX,
        headers={"Accept": "text/html", "User-Agent": "JasonOS-PNBI-G1-ReadOnly/1.0"},
    )
    with opener.open(request, timeout=25) as response:
        if response.geturl() != INDEX:
            raise ValueError("INDEX_REDIRECT_HOLD")
        if response.headers.get_content_type() != "text/html":
            raise ValueError("INDEX_MIME_HOLD")
        body = response.read(MAX_INDEX_BYTES + 1)
    if len(body) > MAX_INDEX_BYTES:
        raise ValueError("INDEX_SIZE_HOLD")
    html = body.decode("utf-8-sig", errors="strict")
    if source == "detail":
        return extract_detail(html)
    if source == "signed":
        return extract(html)
    raise ValueError("UNRECOGNIZED_SOURCE_MODE_HOLD")


def fetch_pdf(opener, url):
    request = Request(
        url,
        headers={"Accept": "application/pdf", "User-Agent": "JasonOS-PNBI-G1-ReadOnly/1.0"},
    )
    with opener.open(request, timeout=45) as response:
        if response.geturl() != url:
            raise ValueError("PDF_REDIRECT_HOLD")
        if response.headers.get_content_type() != "application/pdf":
            raise ValueError("PDF_MIME_HOLD")
        length = response.headers.get("Content-Length")
        if length is not None:
            try:
                declared = int(length)
            except ValueError as error:
                raise ValueError("PDF_BAD_CONTENT_LENGTH_HOLD") from error
            if not 0 < declared <= MAX_PDF_BYTES:
                raise ValueError("PDF_DECLARED_SIZE_HOLD")
        data = response.read(MAX_PDF_BYTES + 1)
    if not data or len(data) > MAX_PDF_BYTES:
        raise ValueError("PDF_ACTUAL_SIZE_HOLD")
    if length is not None and len(data) != declared:
        raise ValueError("PDF_TRUNCATED_OR_LENGTH_MISMATCH_HOLD")
    if not data.startswith(b"%PDF-"):
        raise ValueError("NOT_PDF_HEADER_HOLD")
    return data


def run_poppler(argv, data):
    try:
        result = subprocess.run(
            argv, input=data, capture_output=True, timeout=35, check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as error:
        raise ValueError("POPPLER_UNAVAILABLE_OR_TIMEOUT_HOLD") from error
    if result.returncode != 0:
        raise ValueError("PDF_POPPLER_PARSE_HOLD")
    return result.stdout.decode("utf-8", errors="replace")


def pdf_page_count(info):
    encrypted = re.search(r"^Encrypted:\s*(\S+)", info, re.I | re.M)
    if not encrypted or encrypted.group(1).lower() != "no":
        raise ValueError("PDF_ENCRYPTED_OR_UNKNOWN_HOLD")
    page_text = re.search(r"^Pages:\s*(\d+)\s*$", info, re.I | re.M)
    if not page_text:
        raise ValueError("PDF_NO_PAGES_HOLD")
    pages = int(page_text.group(1))
    if not 1 <= pages <= 1000:
        raise ValueError("PDF_INVALID_PAGE_COUNT_HOLD")
    return pages


def validate_document_id(text, number):
    # Match the PNBI identity, not a substring of e.g. PNBI-10 when looking for 1.
    identity = re.compile(r"\bPNBI\s*[-–—:]?\s*0*" + str(number) + r"\b", re.I)
    if not identity.search(text):
        raise ValueError("PNBI_SOURCE_ID_TEXT_UNVERIFIED_REVIEW_HOLD")


def inspect_one(number, opener=None, source="detail"):
    opener = opener or build_opener(NoRedirect)
    official = fetch_official_index(opener, source=source)  # Re-check official index each run.
    url = official[number]
    data = fetch_pdf(opener, url)
    info = run_poppler(["pdfinfo", "-"], data)
    pages = pdf_page_count(info)
    text = run_poppler(["pdftotext", "-f", "1", "-l", str(min(3, pages)), "-", "-"], data)
    validate_document_id(text, number)
    return {
        "number": number,
        "source": source,
        "url": url,
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "pages": pages,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pnbi", required=True, type=int, choices=range(1, 11), metavar="1..10")
    parser.add_argument("--source", choices=("detail", "signed"), default="detail",
                        help="detail=standard official PDF (default); signed=optional visual-copy source")
    args = parser.parse_args(argv)
    result = inspect_one(args.pnbi, source=args.source)
    print("PNBI-{number:02d} | G1_PDF_CANDIDATE_PASS | SOURCE={source} | SHA256={sha256} | BYTES={bytes} | PAGES={pages} | URL={url}".format(**result))
    print("G1_PDF_SOURCE_ID_TEXT_PASS; SIGNATURE_CRYPTO_NOT_TESTED; NO_DRIVE_WRITE; NO_DB_WRITE")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print("G1_HOLD:", str(error), file=sys.stderr)
        sys.exit(1)
