#!/usr/bin/env python3
"""Read-only G0: list official linked signed English PNBI PDFs. No file writes."""
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit
from urllib.request import build_opener, Request, HTTPRedirectHandler
import re
import sys

INDEX = "https://www.bd.gov.hk/en/resources/codes-and-references/practice-notes-and-circular-letters/index_pnbi.html"
PREFIX = "/doc/en/resources/codes-and-references/practice-notes-and-circular-letters/pnbi/"
SIGNED_PREFIX = PREFIX + "signed/"

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("REDIRECT_HOLD")

class Links(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.current = None
        self.links = []
    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.current = {"href": dict(attrs).get("href", ""), "text": ""}
    def handle_data(self, data):
        if self.current is not None:
            self.current["text"] += data
    def handle_endtag(self, tag):
        if tag == "a" and self.current is not None:
            self.links.append(self.current)
            self.current = None

def extract(html):
    parser = Links()
    parser.feed(html)
    found = {}
    for link in parser.links:
        label = " ".join(link["text"].split()).casefold()
        if "signed copy" not in label:
            continue
        url = urljoin(INDEX, link["href"])
        parts = urlsplit(url)
        if parts.scheme != "https" or parts.netloc != "www.bd.gov.hk" or parts.query or parts.fragment:
            raise ValueError("UNSAFE_SIGNED_COPY_LINK_HOLD")
        if parts.path.lower().rsplit("/", 1)[0] != SIGNED_PREFIX.rstrip("/"):
            raise ValueError("NON_ENGLISH_OR_WRONG_SIGNED_PATH_HOLD")
        filename = parts.path.rsplit("/", 1)[-1]
        m = re.fullmatch(r"PNBI0*(\d{1,2})se\.pdf", filename, re.I)
        if not m:
            raise ValueError("UNRECOGNIZED_SIGNED_FILENAME_HOLD")
        number = int(m.group(1))
        if number not in range(1, 11):
            raise ValueError("OUT_OF_SCOPE_PNBI_HOLD")
        if number in found:
            raise ValueError(f"DUPLICATE_PNBI_{number}_HOLD")
        found[number] = url
    if sorted(found) != list(range(1, 11)):
        missing = sorted(set(range(1, 11)) - found.keys())
        raise ValueError("INCOMPLETE_SIGNED_COPY_LINKS_HOLD missing=" + str(missing))
    return found


def extract_detail(html):
    """Bounded official-index discovery of PNBI-number-labeled standard PDFs.

    Signed Copy and Obsolete Versions are ignored, not substituted.
    Fail closed on missing, duplicate, off-host, bad-language or wrong-path links.
    """
    parser = Links()
    parser.feed(html)
    found = {}
    for link in parser.links:
        # The official "More details" anchor is a javascript:; row expander,
        # NOT a PDF URL. Standard PDFs have exact link labels PNBI-1..PNBI-10.
        label = " ".join(link["text"].split())
        identity = re.fullmatch(r"PNBI\s*[-–—]\s*0*(\d{1,2})", label, re.I)
        if not identity:
            continue
        number = int(identity.group(1))
        if number not in range(1, 11):
            raise ValueError("OUT_OF_SCOPE_PNBI_DETAIL_HOLD")
        url = urljoin(INDEX, link["href"])
        parts = urlsplit(url)
        if parts.scheme != "https" or parts.netloc != "www.bd.gov.hk" or parts.query or parts.fragment:
            raise ValueError("UNSAFE_DETAIL_LINK_HOLD")
        if parts.path.lower().rsplit("/", 1)[0] != PREFIX.rstrip("/"):
            raise ValueError("NON_ENGLISH_OR_WRONG_DETAIL_PATH_HOLD")
        filename = parts.path.rsplit("/", 1)[-1]
        match = re.fullmatch(r"PNBI0*(\d{1,2})\.pdf", filename, re.I)
        if not match:
            raise ValueError("UNRECOGNIZED_DETAIL_FILENAME_HOLD")
        if int(match.group(1)) != number:
            raise ValueError("DETAIL_LABEL_FILENAME_MISMATCH_HOLD")
        if number in found:
            raise ValueError(f"DUPLICATE_PNBI_DETAIL_{number}_HOLD")
        found[number] = url
    if sorted(found) != list(range(1, 11)):
        missing = sorted(set(range(1, 11)) - found.keys())
        raise ValueError("INCOMPLETE_DETAIL_LINKS_HOLD missing=" + str(missing))
    return found


def main():
    req = Request(INDEX, headers={"Accept": "text/html", "User-Agent": "JasonOS-PNBI-G0-ReadOnly/1.0"})
    opener = build_opener(NoRedirect)
    with opener.open(req, timeout=25) as response:
        if response.geturl() != INDEX:
            raise ValueError("INDEX_URL_CHANGED_HOLD")
        if response.headers.get_content_type() != "text/html":
            raise ValueError("INDEX_NOT_HTML_HOLD")
        body = response.read(2_000_001)
    if len(body) > 2_000_000:
        raise ValueError("INDEX_TOO_LARGE_HOLD")
    urls = extract(body.decode("utf-8-sig", errors="strict"))
    for number, url in sorted(urls.items()):
        print(f"PNBI-{number:02d} | LINKED_SIGNED_PDF_CANDIDATE | {url}")
    print("G0_OFFICIAL_INDEX_SIGNED_LINKS_PASS; DOWNLOAD_NONE; DRIVE_WRITE_NONE; DB_WRITE_NONE")

if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print("G0_HOLD:", str(error), file=sys.stderr)
        sys.exit(1)
