#!/usr/bin/env python3

import hashlib
import json
import re
import unicodedata
import urllib.parse

from pathlib import Path


VERSION = "version-signal-snapshot-v1"

MONTHS = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}

LABEL_PATTERNS = {
    "first_issue_date": re.compile(
        r"\bFirst\s+issue\s+([A-Za-z]+)\s+(\d{4})",
        re.IGNORECASE,
    ),
    "last_revision_date": re.compile(
        r"\bLast\s+revision\s+([A-Za-z]+)\s+(\d{4})",
        re.IGNORECASE,
    ),
    "revision_date": re.compile(
        r"\bThis\s+revision\s+([A-Za-z]+)\s+(\d{4})",
        re.IGNORECASE,
    ),
}

FOOTER_REVISION_RE = re.compile(
    r"\((0?[1-9]|1[0-2])/(20\d{2})\)"
)

EDITION_RE = re.compile(
    r"\b(20\d{2})\s+Edition\b",
    re.IGNORECASE,
)


def sha256_text(value: str) -> str:
    return hashlib.sha256(
        value.encode("utf-8")
    ).hexdigest()


def canonical_json_hash(
    payload: dict,
) -> str:
    return sha256_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )


def normalize_content_text(
    text: str,
) -> str:
    text = unicodedata.normalize(
        "NFKC",
        str(text or ""),
    )

    return " ".join(
        text.split()
    ).strip()


def manifest_text(
    manifest: dict,
) -> str:
    parts = []

    for unit in (
        manifest.get("units")
        or []
    ):
        text = normalize_content_text(
            unit.get("text")
        )

        if text:
            parts.append(text)

    return "\n".join(parts)


def month_year(
    month_name: str,
    year: str,
):
    month = MONTHS.get(
        str(month_name or "")
        .strip()
        .lower()
    )

    if not month:
        return None

    return (
        f"{int(year):04d}-"
        f"{month:02d}"
    )


def extract_labeled_date(
    text: str,
    pattern,
):
    match = pattern.search(
        text
    )

    if not match:
        return None

    return month_year(
        match.group(1),
        match.group(2),
    )


def extract_version_dates(
    text: str,
) -> dict:
    text = normalize_content_text(
        text
    )

    result = {
        key:
            extract_labeled_date(
                text,
                pattern,
            )
        for key, pattern
        in LABEL_PATTERNS.items()
    }

    revision_source = (
        "explicit_this_revision"
        if result[
            "revision_date"
        ]
        else None
    )

    footer_dates = sorted(
        {
            (
                f"{int(year):04d}-"
                f"{int(month):02d}"
            )
            for month, year
            in FOOTER_REVISION_RE.findall(
                text
            )
        }
    )

    if (
        result[
            "revision_date"
        ]
        is None
        and footer_dates
    ):
        result[
            "revision_date"
        ] = footer_dates[-1]

        revision_source = (
            "pnap_footer_month_year"
        )

    editions = sorted(
        {
            int(value)
            for value
            in EDITION_RE.findall(
                text
            )
        }
    )

    result["edition"] = (
        str(editions[-1])
        if editions
        else None
    )

    result[
        "issue_date"
    ] = (
        result[
            "revision_date"
        ]
        or result[
            "first_issue_date"
        ]
    )

    result[
        "revision_date_source"
    ] = revision_source

    result[
        "footer_revision_candidates"
    ] = footer_dates

    return result


def read_pdf_metadata(
    path: Path,
) -> dict:
    if (
        path.suffix.lower()
        != ".pdf"
        or not path.exists()
    ):
        return {}

    try:
        import pymupdf
    except ImportError:
        return {}

    doc = pymupdf.open(
        path
    )

    try:
        return dict(
            doc.metadata
            or {}
        )
    finally:
        doc.close()


def stable_pdf_metadata(
    metadata: dict,
) -> dict:
    allowed = (
        "title",
        "author",
        "subject",
        "keywords",
    )

    return {
        key:
            normalize_content_text(
                metadata.get(key)
            )
        for key in allowed
        if normalize_content_text(
            metadata.get(key)
        )
    }


def canonical_host(
    url: str,
):
    try:
        return (
            urllib.parse.urlparse(
                str(url or "")
            ).hostname
        )
    except Exception:
        return None


def build_version_signal_snapshot(
    *,
    source_file: Path,
    manifest: dict,
    source: dict,
    pdf_metadata: dict | None = None,
) -> dict:
    text = manifest_text(
        manifest
    )

    dates = extract_version_dates(
        text
    )

    if pdf_metadata is None:
        pdf_metadata = (
            read_pdf_metadata(
                source_file
            )
        )

    material_metadata = {
        "document_code":
            source.get(
                "document_code"
            ),
        "title":
            source.get(
                "title"
            ),
        "page_count":
            (
                manifest.get(
                    "document"
                )
                or {}
            ).get(
                "page_count"
            ),
        "pdf":
            stable_pdf_metadata(
                pdf_metadata
            ),
        "first_issue_date":
            dates[
                "first_issue_date"
            ],
        "last_revision_date":
            dates[
                "last_revision_date"
            ],
        "revision_date":
            dates[
                "revision_date"
            ],
        "edition":
            dates[
                "edition"
            ],
    }

    normalized = (
        normalize_content_text(
            text
        )
    )

    return {
        "version_signals_version": 1,
        "extractor_version": VERSION,
        "source_family":
            source.get(
                "source_family"
            ),
        "authority_code":
            source.get(
                "authority_code"
            ),
        "document_code":
            source.get(
                "document_code"
            ),
        "canonical_host":
            canonical_host(
                source.get(
                    "canonical_url"
                )
            ),
        "issue_date":
            dates[
                "issue_date"
            ],
        "first_issue_date":
            dates[
                "first_issue_date"
            ],
        "last_revision_date":
            dates[
                "last_revision_date"
            ],
        "revision_date":
            dates[
                "revision_date"
            ],
        "revision_date_source":
            dates[
                "revision_date_source"
            ],
        "edition":
            dates[
                "edition"
            ],
        "page_count":
            material_metadata[
                "page_count"
            ],
        "metadata_fingerprint":
            canonical_json_hash(
                material_metadata
            ),
        "normalized_content_fingerprint":
            sha256_text(
                normalized
            ),
        "normalized_content_chars":
            len(normalized),
        "document_sha256":
            (
                manifest.get(
                    "source"
                )
                or {}
            ).get(
                "sha256"
            ),
        "material_metadata":
            material_metadata,
    }


def compare_version_snapshots(
    previous: dict,
    current: dict,
    *,
    staging_validation_verified: bool,
    deterministic_release: bool,
) -> dict:
    return {
        "authority_match":
            previous.get(
                "authority_code"
            )
            == current.get(
                "authority_code"
            ),
        "document_code_match":
            previous.get(
                "document_code"
            )
            == current.get(
                "document_code"
            ),
        "official_host_match":
            previous.get(
                "canonical_host"
            )
            == current.get(
                "canonical_host"
            ),
        "staging_validation_verified":
            bool(
                staging_validation_verified
            ),
        "deterministic_release":
            bool(
                deterministic_release
            ),
        "checksum_changed":
            previous.get(
                "document_sha256"
            )
            != current.get(
                "document_sha256"
            ),
        "normalized_content_changed":
            previous.get(
                "normalized_content_fingerprint"
            )
            != current.get(
                "normalized_content_fingerprint"
            ),
        "metadata_changed":
            previous.get(
                "metadata_fingerprint"
            )
            != current.get(
                "metadata_fingerprint"
            ),
        "previous_issue_date":
            previous.get(
                "issue_date"
            ),
        "current_issue_date":
            current.get(
                "issue_date"
            ),
        "previous_revision_date":
            previous.get(
                "revision_date"
            ),
        "current_revision_date":
            current.get(
                "revision_date"
            ),
        "edition_changed":
            (
                previous.get(
                    "edition"
                )
                != current.get(
                    "edition"
                )
                and current.get(
                    "edition"
                )
                is not None
            ),
    }
