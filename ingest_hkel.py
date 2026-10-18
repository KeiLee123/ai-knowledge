#!/usr/bin/env python3

import argparse
import hashlib
import json
import re
import sys
import subprocess
import urllib.request
import xml.etree.ElementTree as ET

from collections import Counter
from pathlib import Path

import yaml


sys.path.insert(
    0,
    "/opt/ai-knowledge"
)

from parse_hkel_xml_v5 import (
    walk,
    deduplicate,
    local,
    clean_text,
)


REGISTRY = Path(
    "/opt/ai-knowledge/"
    "legislation_registry.yaml"
)

BASELINE = Path(
    "/opt/ai-knowledge/watch/"
    "legislation/baseline_manifest.json"
)

WATCH_ROOT = Path(
    "/opt/ai-knowledge/watch/"
    "legislation/current"
)


DB_CONTAINER = (
    "ai-knowledge-db-jiyckdrlappwgimwebnzxwmr"
)

EMBED_URL = (
    "http://127.0.0.1:8088/embed"
)

EMBED_PROVIDER = "local"
EMBED_MODEL = "multilingual-e5-small"
EMBED_DIMENSIONS = 384

EMBED_BATCH_SIZE = 32



LEGAL_TAGS = {
    "section",
    "subsection",
    "paragraph",
    "subparagraph",
}


def normalize_cap(value):

    value = (
        value.strip()
        .upper()
        .replace("CAP.", "CAP_")
        .replace("CAP ", "CAP_")
        .replace("-", "_")
    )

    if re.fullmatch(
        r"\d+",
        value
    ):
        value = (
            f"CAP_{value}"
        )

    return value


def load_yaml(path):

    with path.open(
        "r",
        encoding="utf-8"
    ) as f:

        return yaml.safe_load(
            f
        )


def resolve_legislation_metadata(
    registry,
    cap_key
):

    laws = registry.get(
        "legislation",
        {}
    )

    if cap_key not in laws:

        raise SystemExit(
            f"{cap_key} not found "
            "in legislation registry."
        )

    law_cfg = laws[
        cap_key
    ]

    defaults = registry.get(
        "defaults",
        {}
    )

    authorities = registry.get(
        "authorities",
        {}
    )

    # ----------------------------------------------------
    # Mapping status
    # ----------------------------------------------------

    mapping_status = (
        law_cfg.get(
            "mapping_status"
        )
    )

    if (
        not mapping_status
        or mapping_status
        == "pending-verification"
    ):

        raise SystemExit(
            f"{cap_key} authority mapping "
            "is not production-ready: "
            f"{mapping_status!r}"
        )

    # ----------------------------------------------------
    # Core classification
    # ----------------------------------------------------

    domain = law_cfg.get(
        "domain"
    )

    topic = law_cfg.get(
        "topic"
    )

    if not domain:

        raise SystemExit(
            f"{cap_key} domain is missing "
            "from legislation registry."
        )

    if not topic:

        raise SystemExit(
            f"{cap_key} topic is missing "
            "from legislation registry."
        )

    # ----------------------------------------------------
    # Authority mode
    # ----------------------------------------------------

    authority_mode = (
        law_cfg.get(
            "authority_mode"
        )
    )

    if authority_mode not in {
        "single",
        "multi",
    }:

        raise SystemExit(
            f"{cap_key} has invalid or "
            "missing authority_mode: "
            f"{authority_mode!r}"
        )

    # ----------------------------------------------------
    # Resolve responsible authorities
    # ----------------------------------------------------

    links = (
        law_cfg.get(
            "responsible_authorities",
            []
        )
        or []
    )

    responsible_authorities = []

    for item in links:

        code = item.get(
            "authority_code"
        )

        if not code:

            raise SystemExit(
                f"{cap_key} has a "
                "responsible authority "
                "without authority_code."
            )

        cfg = authorities.get(
            code
        )

        if not cfg:

            raise SystemExit(
                f"{cap_key} references "
                "unknown authority code: "
                f"{code}"
            )

        name = cfg.get(
            "name"
        )

        if not name:

            raise SystemExit(
                "Authority catalogue entry "
                f"{code} has no name."
            )

        if (
            name
            not in responsible_authorities
        ):
            responsible_authorities.append(
                name
            )

    if not responsible_authorities:

        raise SystemExit(
            f"{cap_key} has no resolved "
            "responsible authorities."
        )

    # ----------------------------------------------------
    # Resolve legacy document.authority field
    #
    # The machine-readable authority relationship remains
    # responsible_authorities.
    #
    # single:
    #   one designated primary authority
    #
    # multi:
    #   joined display value without inventing a primary
    # ----------------------------------------------------

    if authority_mode == "single":

        primary_code = law_cfg.get(
            "primary_authority_code"
        )

        if not primary_code:

            raise SystemExit(
                f"{cap_key} uses single "
                "authority mode but has no "
                "primary_authority_code."
            )

        primary_cfg = authorities.get(
            primary_code
        )

        if not primary_cfg:

            raise SystemExit(
                f"{cap_key} references "
                "unknown primary authority "
                f"code: {primary_code}"
            )

        authority = primary_cfg.get(
            "name"
        )

        if not authority:

            raise SystemExit(
                "Authority catalogue entry "
                f"{primary_code} has no name."
            )

        if (
            authority
            not in responsible_authorities
        ):

            raise SystemExit(
                f"{cap_key} primary authority "
                "is not included in "
                "responsible_authorities."
            )

    else:

        if len(
            responsible_authorities
        ) < 2:

            raise SystemExit(
                f"{cap_key} uses multi "
                "authority mode but fewer "
                "than two authorities "
                "were resolved."
            )

        authority = "; ".join(
            responsible_authorities
        )

    # ----------------------------------------------------
    # Registry defaults
    # ----------------------------------------------------

    source_publisher = (
        defaults.get(
            "source_publisher"
        )
    )

    jurisdiction = (
        defaults.get(
            "jurisdiction"
        )
    )

    if not source_publisher:

        raise SystemExit(
            "defaults.source_publisher "
            "is missing from registry."
        )

    if not jurisdiction:

        raise SystemExit(
            "defaults.jurisdiction "
            "is missing from registry."
        )

    return {
        "domain":
            domain,

        "topic":
            topic,

        "authority":
            authority,

        "authority_mode":
            authority_mode,

        "responsible_authorities":
            responsible_authorities,

        "source_publisher":
            source_publisher,

        "jurisdiction":
            jurisdiction,

        "mapping_status":
            mapping_status,
    }



def load_json(path):

    with path.open(
        "r",
        encoding="utf-8"
    ) as f:

        return json.load(
            f
        )


def sha256_file(path):

    h = hashlib.sha256()

    with path.open(
        "rb"
    ) as f:

        for block in iter(
            lambda:
                f.read(
                    1024 * 1024
                ),
            b""
        ):
            h.update(
                block
            )

    return h.hexdigest()


def normalize_space(value):

    return " ".join(
        (value or "").split()
    )


def atomic_text(elem):

    """
    Extract the current provision's own text
    without recursively duplicating nested
    legal provisions.

    Definitions are handled separately.
    """

    pieces = []

    def visit(node):

        if node.text:
            pieces.append(
                node.text
            )

        for child in node:

            tag = local(
                child.tag
            )

            if tag in LEGAL_TAGS:

                # Child legal provision:
                # exclude subtree from this
                # parent's semantic unit.
                pass

            elif tag == "def":

                # Definitions become their
                # own semantic units.
                pass

            else:

                visit(
                    child
                )

            if child.tail:
                pieces.append(
                    child.tail
                )

    visit(
        elem
    )

    return normalize_space(
        "".join(
            pieces
        )
    )


def build_parent_map(root):

    return {
        child: parent
        for parent in root.iter()
        for child in parent
    }


def nearest_legal_record(
    elem,
    parent_map,
    record_by_xml_id
):

    current = parent_map.get(
        elem
    )

    while current is not None:

        xml_id = current.attrib.get(
            "id"
        )

        if (
            xml_id
            and xml_id
            in record_by_xml_id
        ):
            return record_by_xml_id[
                xml_id
            ]

        current = parent_map.get(
            current
        )

    return None


def percentile(
    values,
    pct
):

    if not values:
        return 0

    values = sorted(
        values
    )

    index = round(
        (len(values) - 1)
        * pct
    )

    return values[
        index
    ]



EXACT_CHUNK_MAX_CHARS = 6000

SEMANTIC_CHUNK_MAX_CHARS = 1800
SEMANTIC_CHUNK_OVERLAP_CHARS = 180


def split_exact_text(
    text,
    max_chars=EXACT_CHUNK_MAX_CHARS
):

    text = normalize_space(
        text
    )

    if not text:
        return []

    if len(text) <= max_chars:
        return [text]

    parts = []
    remaining = text

    while len(remaining) > max_chars:

        cut = remaining.rfind(
            " ",
            0,
            max_chars + 1
        )

        # Avoid extremely short split caused
        # by unusual long tokens.
        if cut < int(
            max_chars * 0.60
        ):
            cut = max_chars

        part = remaining[
            :cut
        ].strip()

        if part:
            parts.append(
                part
            )

        remaining = remaining[
            cut:
        ].strip()

    if remaining:
        parts.append(
            remaining
        )

    return parts



def split_text_with_overlap(
    text,
    max_chars,
    overlap_chars
):

    text = normalize_space(
        text
    )

    if not text:
        return []

    if len(text) <= max_chars:
        return [text]

    parts = []
    start = 0
    text_len = len(text)

    while start < text_len:

        target_end = min(
            start + max_chars,
            text_len
        )

        if target_end < text_len:

            cut = text.rfind(
                " ",
                start,
                target_end + 1
            )

            if cut <= start + int(
                max_chars * 0.60
            ):
                cut = target_end

        else:
            cut = text_len

        part = text[
            start:cut
        ].strip()

        if part:
            parts.append(
                part
            )

        if cut >= text_len:
            break

        next_start = max(
            0,
            cut - overlap_chars
        )

        # Move forward to a word boundary
        # where possible.
        if next_start > 0:

            space = text.find(
                " ",
                next_start
            )

            if (
                space != -1
                and space < cut
            ):
                next_start = (
                    space + 1
                )

        # Safety against accidental
        # non-progress loops.
        if next_start <= start:
            next_start = cut

        start = next_start

    return parts


def semantic_context_prefix(
    unit,
    chapter,
    title
):

    base = (
        f"Cap. {chapter} "
        f"{title}. "
    )

    reference = unit.get(
        "reference"
    )

    if reference:

        return (
            base
            + f"{reference}. "
        )

    definition_name = unit.get(
        "definition_name"
    )

    if definition_name:

        return (
            base
            + "Definition "
            + f"{definition_name}. "
        )

    parent_reference = unit.get(
        "parent_reference"
    )

    if parent_reference:

        return (
            base
            + f"{parent_reference}. "
        )

    return base


def split_semantic_units(
    units,
    chapter,
    title
):

    output = []

    split_units = 0
    max_parts = 0

    for unit in units:

        content = normalize_space(
            unit.get(
                "content"
            )
        )

        if not content:
            continue

        prefix = semantic_context_prefix(
            unit,
            chapter,
            title
        )

        # Reserve enough room so continuation
        # parts can carry legal context while
        # remaining inside the 1800-char cap.
        payload_limit = max(
            500,
            SEMANTIC_CHUNK_MAX_CHARS
            - len(prefix)
        )

        parts = split_text_with_overlap(
            content,
            payload_limit,
            SEMANTIC_CHUNK_OVERLAP_CHARS
        )

        if len(parts) > 1:
            split_units += 1

        max_parts = max(
            max_parts,
            len(parts)
        )

        for index, part in enumerate(
            parts,
            start=1
        ):

            # Part 1 already contains the original
            # context prefix. Continuation parts
            # receive explicit legal context.
            if (
                index > 1
                and not part.startswith(
                    prefix
                )
            ):
                part = normalize_space(
                    prefix
                    + part
                )

            new_unit = dict(
                unit
            )

            new_unit[
                "content"
            ] = part

            new_unit[
                "semantic_part"
            ] = index

            new_unit[
                "semantic_parts"
            ] = len(parts)

            output.append(
                new_unit
            )

    return (
        output,
        split_units,
        max_parts
    )


def build_plan(
    cap_key
):

    registry = load_yaml(
        REGISTRY
    )

    baseline = load_json(
        BASELINE
    )

    laws = registry.get(
        "legislation",
        {}
    )

    if cap_key not in laws:

        raise SystemExit(
            f"{cap_key} not found "
            "in legislation registry."
        )

    manifest_laws = (
        baseline.get(
            "legislation",
            {}
        )
    )

    if cap_key not in manifest_laws:

        raise SystemExit(
            f"{cap_key} not found "
            "in baseline manifest."
        )

    law_cfg = laws[
        cap_key
    ]

    resolved_metadata = (
        resolve_legislation_metadata(
            registry,
            cap_key
        )
    )

    source = manifest_laws[
        cap_key
    ]

    xml_path = (
        WATCH_ROOT
        / cap_key
        / "machine"
        / "current.xml"
    )

    if not xml_path.exists():

        raise SystemExit(
            f"XML not found: "
            f"{xml_path}"
        )

    tree = ET.parse(
        xml_path
    )

    root = tree.getroot()

    records = deduplicate(
        walk(root)
    )

    canonical = [
        r
        for r in records
        if r.get(
            "canonical_reference"
        )
    ]

    canonical_by_ref = {
        r["canonical_reference"]: r
        for r in canonical
    }

    canonical_children = (
        Counter()
    )

    for r in canonical:

        parent = r.get(
            "parent_canonical_reference"
        )

        if parent:
            canonical_children[
                parent
            ] += 1

    id_map = {
        elem.attrib["id"]: elem
        for elem in root.iter()
        if elem.attrib.get(
            "id"
        )
    }

    record_by_xml_id = {
        r["xml_id"]: r
        for r in records
        if r.get(
            "xml_id"
        )
    }

    parent_map = build_parent_map(
        root
    )

    # --------------------------------------------------------
    # Canonical section layer
    # --------------------------------------------------------

    section_units = []

    for sort_order, r in enumerate(
        canonical,
        start=1
    ):

        section_units.append({

            "reference":
                r[
                    "canonical_reference"
                ],

            "parent_reference":
                r.get(
                    "parent_canonical_reference"
                ),

            "heading":
                r.get(
                    "heading"
                )
                or "",

            "content":
                normalize_space(
                    r.get(
                        "content"
                    )
                    or ""
                ),

            "sort_order":
                sort_order,

            "raw_reference":
                r.get(
                    "raw_reference"
                ),

            "level":
                r.get(
                    "level"
                ),

            "xml_id":
                r.get(
                    "xml_id"
                ),

            "temporal_id":
                r.get(
                    "temporal_id"
                ),

            "operative":
                r.get(
                    "operative",
                    True
                ),

            "repealed":
                r.get(
                    "repealed",
                    False
                ),

            "not_in_operation":
                r.get(
                    "not_in_operation",
                    False
                ),

            "omitted_as_spent":
                r.get(
                    "omitted_as_spent",
                    False
                ),

            "schedule_number":
                r.get(
                    "schedule_number"
                ),

            "part_name":
                r.get(
                    "part_name"
                ),

            "embedded_quote":
                r.get(
                    "embedded_quote",
                    False
                ),
        })

    # --------------------------------------------------------
    # Exact layer
    #
    # One canonical legal provision may produce
    # multiple bounded exact chunks. All parts will
    # later point to the same section_id.
    # --------------------------------------------------------

    exact_units = []

    split_exact_provisions = 0
    max_exact_parts = 0

    for r in canonical:

        full_content = normalize_space(
            r.get(
                "content"
            )
            or ""
        )

        # Every canonical reference must remain
        # reachable through the chunk-based exact
        # retrieval system.
        if not full_content:

            full_content = (
                normalize_space(
                    r.get(
                        "heading"
                    )
                    or ""
                )
                or r[
                    "canonical_reference"
                ]
            )

        parts = split_exact_text(
            full_content
        )

        if len(parts) > 1:
            split_exact_provisions += 1

        max_exact_parts = max(
            max_exact_parts,
            len(parts)
        )

        for part_index, part in enumerate(
            parts,
            start=1
        ):

            exact_units.append({

                "reference":
                    r[
                        "canonical_reference"
                    ],

                "heading":
                    r.get(
                        "heading"
                    ) or "",

                "content":
                    part,

                "exact_part":
                    part_index,

                "exact_parts":
                    len(parts),

                "full_length":
                    len(
                        full_content
                    ),

                "operative":
                    r.get(
                        "operative",
                        True
                    ),

                "repealed":
                    r.get(
                        "repealed",
                        False
                    ),

                "not_in_operation":
                    r.get(
                        "not_in_operation",
                        False
                    ),

                "omitted_as_spent":
                    r.get(
                        "omitted_as_spent",
                        False
                    ),

                "level":
                    r.get(
                        "level"
                    ),

                "xml_id":
                    r.get(
                        "xml_id"
                    ),

                "temporal_id":
                    r.get(
                        "temporal_id"
                    ),
            })

    # --------------------------------------------------------
    # Semantic canonical units
    # --------------------------------------------------------

    semantic_units = []

    for r in canonical:

        # Do not push historical / future provisions
        # into default semantic retrieval.
        if not r.get(
            "operative",
            True
        ):
            continue

        if r.get(
            "embedded_quote",
            False
        ):
            continue

        elem = None

        xml_id = r.get(
            "xml_id"
        )

        if xml_id:
            elem = id_map.get(
                xml_id
            )

        text = ""

        if elem is not None:

            text = atomic_text(
                elem
            )

        # If it is a leaf provision and atomic
        # extraction gives little text, using its
        # full text does not create descendant
        # duplication.
        if (
            len(text) < 20
            and canonical_children.get(
                r[
                    "canonical_reference"
                ],
                0
            ) == 0
        ):
            text = normalize_space(
                r.get(
                    "content"
                )
            )

        if len(text) < 20:
            continue

        heading = (
            r.get(
                "heading"
            )
            or ""
        )

        context = (
            f"Cap. "
            f"{law_cfg['chapter']} "
            f"{source['title']}. "
            f"{r['canonical_reference']}. "
        )

        if heading:
            context += (
                f"{heading}. "
            )

        content = normalize_space(
            context
            + text
        )

        semantic_units.append({
            "semantic_type":
                "canonical-atomic",

            "reference":
                r[
                    "canonical_reference"
                ],

            "content":
                content,

            "source_xml_id":
                xml_id,

            "operative":
                r.get(
                    "operative",
                    True
                ),

            "repealed":
                r.get(
                    "repealed",
                    False
                ),

            "not_in_operation":
                r.get(
                    "not_in_operation",
                    False
                ),

            "omitted_as_spent":
                r.get(
                    "omitted_as_spent",
                    False
                ),
        })

    # --------------------------------------------------------
    # Definition semantic units
    # --------------------------------------------------------

    definitions = {}

    for elem in root.iter():

        if local(
            elem.tag
        ) != "def":
            continue

        name = (
            elem.attrib.get(
                "name"
            )
            or ""
        ).strip()

        text = normalize_space(
            clean_text(
                elem
            )
        )

        if not text:
            continue

        nearest = nearest_legal_record(
            elem,
            parent_map,
            record_by_xml_id
        )

        if (
            nearest
            and not nearest.get(
                "operative",
                True
            )
        ):
            continue

        key = (
            name,
            text
        )

        definitions[
            key
        ] = {
            "semantic_type":
                "definition",

            "definition_name":
                name,

            "parent_reference":
                (
                    (
                        nearest.get(
                            "canonical_reference"
                        )
                        or nearest.get(
                            "parent_canonical_reference"
                        )
                    )
                    if nearest
                    else None
                ),

            "content":
                normalize_space(
                    f"Cap. "
                    f"{law_cfg['chapter']} "
                    f"{source['title']}. "
                    f"Definition: "
                    f"{text}"
                ),

            "operative":
                (
                    nearest.get(
                        "operative",
                        True
                    )
                    if nearest
                    else True
                ),

            "repealed":
                (
                    nearest.get(
                        "repealed",
                        False
                    )
                    if nearest
                    else False
                ),

            "not_in_operation":
                (
                    nearest.get(
                        "not_in_operation",
                        False
                    )
                    if nearest
                    else False
                ),

            "omitted_as_spent":
                (
                    nearest.get(
                        "omitted_as_spent",
                        False
                    )
                    if nearest
                    else False
                ),
        }

    semantic_units.extend(
        definitions.values()
    )

    # --------------------------------------------------------
    # Deduplicate semantic units
    # --------------------------------------------------------

    semantic_seen = set()
    semantic_clean = []

    for unit in semantic_units:

        key = hashlib.sha256(
            unit[
                "content"
            ].encode(
                "utf-8"
            )
        ).hexdigest()

        if key in semantic_seen:
            continue

        semantic_seen.add(
            key
        )

        semantic_clean.append(
            unit
        )

    semantic_units = (
        semantic_clean
    )

    (
        semantic_units,
        split_semantic_units_count,
        max_semantic_parts
    ) = split_semantic_units(
        semantic_units,
        law_cfg["chapter"],
        source["title"]
    )

    # --------------------------------------------------------
    # Source metadata
    # --------------------------------------------------------

    version_date = (
        source[
            "version_date"
        ].split(
            "T",
            1
        )[0]
    )

    language = "en"

    source_file_id = (
        f"hkel:"
        f"{cap_key}:"
        f"{language}:"
        f"{version_date}"
    )

    exact_sizes = [
        len(
            u["content"]
        )
        for u in exact_units
    ]

    semantic_sizes = [
        len(
            u["content"]
        )
        for u in semantic_units
    ]

    largest_exact = sorted(
        exact_units,
        key=lambda x:
            len(
                x["content"]
            ),
        reverse=True
    )[:10]

    return {
        "cap_key":
            cap_key,

        "chapter":
            law_cfg[
                "chapter"
            ],

        "title":
            source[
                "title"
            ],

        "domain":
            resolved_metadata[
                "domain"
            ],

        "document_type":
            "legislation",

        "authority":
            resolved_metadata[
                "authority"
            ],

        "responsible_authorities":
            resolved_metadata[
                "responsible_authorities"
            ],

        "source_publisher":
            resolved_metadata[
                "source_publisher"
            ],

        "topic":
            resolved_metadata[
                "topic"
            ],

        "jurisdiction":
            resolved_metadata[
                "jurisdiction"
            ],

        "language":
            language,

        "version_date":
            version_date,

        "source_type":
            "hkel",

        "source_file_id":
            source_file_id,

        "source_url":
            source.get(
                "web_url"
            ),

        "checksum_sha256":
            sha256_file(
                xml_path
            ),

        "xml_path":
            str(
                xml_path
            ),

        "parser_version":
            "v5",

        "records_total":
            len(
                records
            ),

        "canonical_sections":
            len(
                canonical
            ),

        "section_units":
            section_units,

        "exact_units":
            exact_units,

        "exact_chunk_max_chars":
            EXACT_CHUNK_MAX_CHARS,

        "split_exact_provisions":
            split_exact_provisions,

        "max_exact_parts":
            max_exact_parts,

        "semantic_units":
            semantic_units,

        "semantic_chunk_max_chars":
            SEMANTIC_CHUNK_MAX_CHARS,

        "semantic_chunk_overlap_chars":
            SEMANTIC_CHUNK_OVERLAP_CHARS,

        "split_semantic_units":
            split_semantic_units_count,

        "max_semantic_parts":
            max_semantic_parts,

        "definitions":
            len(
                definitions
            ),

        "repealed_exact":
            sum(
                1
                for r in canonical
                if r.get(
                    "repealed"
                )
            ),

        "not_in_operation_exact":
            sum(
                1
                for r in canonical
                if r.get(
                    "not_in_operation"
                )
            ),

        "omitted_as_spent_exact":
            sum(
                1
                for r in canonical
                if r.get(
                    "omitted_as_spent"
                )
            ),

        "embedded_quote_records":
            sum(
                1
                for r in records
                if r.get(
                    "embedded_quote"
                )
            ),

        "exact_size_stats": {
            "median":
                percentile(
                    exact_sizes,
                    0.50
                ),

            "p95":
                percentile(
                    exact_sizes,
                    0.95
                ),

            "max":
                max(
                    exact_sizes
                )
                if exact_sizes
                else 0,
        },

        "semantic_size_stats": {
            "median":
                percentile(
                    semantic_sizes,
                    0.50
                ),

            "p95":
                percentile(
                    semantic_sizes,
                    0.95
                ),

            "max":
                max(
                    semantic_sizes
                )
                if semantic_sizes
                else 0,
        },

        "largest_exact":
            largest_exact,
    }


def show_plan(plan):

    print("=" * 76)
    print("HKeL INGESTION DRY RUN")
    print("=" * 76)

    print()
    print(
        "Legislation:",
        plan["cap_key"]
    )

    print(
        "Title:",
        plan["title"]
    )

    print(
        "Version:",
        plan["version_date"]
    )

    print(
        "Language:",
        plan["language"]
    )

    print(
        "Domain:",
        plan["domain"]
    )

    print(
        "Source ID:",
        plan[
            "source_file_id"
        ]
    )

    print(
        "XML SHA256:",
        plan[
            "checksum_sha256"
        ]
    )

    print()

    print(
        "Parser records:",
        plan[
            "records_total"
        ]
    )

    print(
        "Canonical sections:",
        plan[
            "canonical_sections"
        ]
    )

    print(
        "Legal-exact chunks:",
        len(
            plan[
                "exact_units"
            ]
        )
    )

    print(
        "Exact chunk cap:",
        plan[
            "exact_chunk_max_chars"
        ],
        "chars"
    )

    print(
        "Exact provisions split:",
        plan[
            "split_exact_provisions"
        ]
    )

    print(
        "Max exact parts/provision:",
        plan[
            "max_exact_parts"
        ]
    )

    print(
        "Legal-semantic chunks:",
        len(
            plan[
                "semantic_units"
            ]
        )
    )

    print(
        "Embeddings required:",
        len(
            plan[
                "semantic_units"
            ]
        )
    )

    print(
        "Semantic chunk cap:",
        plan[
            "semantic_chunk_max_chars"
        ],
        "chars"
    )

    print(
        "Semantic overlap:",
        plan[
            "semantic_chunk_overlap_chars"
        ],
        "chars"
    )

    print(
        "Semantic units split:",
        plan[
            "split_semantic_units"
        ]
    )

    print(
        "Max semantic parts/unit:",
        plan[
            "max_semantic_parts"
        ]
    )

    print(
        "Definitions:",
        plan[
            "definitions"
        ]
    )

    print(
        "Repealed canonical:",
        plan[
            "repealed_exact"
        ]
    )

    print(
        "Not-in-operation canonical:",
        plan[
            "not_in_operation_exact"
        ]
    )

    print(
        "Omitted-as-spent canonical:",
        plan[
            "omitted_as_spent_exact"
        ]
    )

    print(
        "Embedded quote records:",
        plan[
            "embedded_quote_records"
        ]
    )

    print()
    print(
        "Exact chunk size "
        "(characters):"
    )

    print(
        "  median:",
        plan[
            "exact_size_stats"
        ]["median"]
    )

    print(
        "  p95:",
        plan[
            "exact_size_stats"
        ]["p95"]
    )

    print(
        "  max:",
        plan[
            "exact_size_stats"
        ]["max"]
    )

    print()
    print(
        "Semantic chunk size "
        "(characters):"
    )

    print(
        "  median:",
        plan[
            "semantic_size_stats"
        ]["median"]
    )

    print(
        "  p95:",
        plan[
            "semantic_size_stats"
        ]["p95"]
    )

    print(
        "  max:",
        plan[
            "semantic_size_stats"
        ]["max"]
    )

    print()
    print("=" * 76)
    print(
        "10 LARGEST EXACT CHUNKS"
    )
    print("=" * 76)

    for item in plan[
        "largest_exact"
    ]:

        part_label = (
            f"{item.get('exact_part', 1)}/"
            f"{item.get('exact_parts', 1)}"
        )

        print(
            f"{item['reference']:<28}"
            f"part {part_label:<7}"
            f"{len(item['content']):>7} chars "
            f"| operative="
            f"{item['operative']}"
        )

    print()
    print("=" * 76)
    print(
        "SEMANTIC SAMPLE"
    )
    print("=" * 76)

    for item in plan[
        "semantic_units"
    ][:15]:

        label = (
            item.get(
                "reference"
            )
            or item.get(
                "definition_name"
            )
            or "-"
        )

        print()
        part_label = (
            f"{item.get('semantic_part', 1)}/"
            f"{item.get('semantic_parts', 1)}"
        )

        print(
            item[
                "semantic_type"
            ],
            "|",
            label,
            "| part",
            part_label
        )

        print(
            item[
                "content"
            ][:300]
        )

    print()
    print(
        "DRY RUN ONLY — "
        "no database rows written, "
        "no embeddings generated."
    )



def sql_quote(value):

    return (
        str(value)
        .replace("\x00", "")
        .replace("'", "''")
    )


def sql_literal(value):

    if value is None:
        return "NULL"

    return (
        "'"
        + sql_quote(value)
        + "'"
    )


def json_literal(value):

    text = json.dumps(
        value,
        ensure_ascii=False,
        separators=(
            ",",
            ":"
        )
    )

    return (
        "'"
        + sql_quote(text)
        + "'::jsonb"
    )


def psql_query(sql):

    result = subprocess.run(
        [
            "docker",
            "exec",
            "-i",
            DB_CONTAINER,
            "psql",
            "-U",
            "ai_knowledge",
            "-d",
            "ai_knowledge",
            "-qAt",
            "-v",
            "ON_ERROR_STOP=1",
            "-c",
            sql,
        ],
        text=True,
        capture_output=True,
    )

    if result.returncode != 0:

        raise RuntimeError(
            "PostgreSQL query failed:\n"
            + result.stderr
        )

    return result.stdout.strip()


def embed_semantic_units(
    semantic_units
):

    texts = [
        (
            "passage: "
            + unit["content"]
        )
        for unit
        in semantic_units
    ]

    vectors = []

    total = len(
        texts
    )

    print()
    print(
        "Precomputing embeddings..."
    )

    print(
        "Model:",
        EMBED_MODEL
    )

    print(
        "Semantic chunks:",
        total
    )

    for start in range(
        0,
        total,
        EMBED_BATCH_SIZE
    ):

        batch = texts[
            start:
            start + EMBED_BATCH_SIZE
        ]

        payload = json.dumps({
            "inputs":
                batch
        }).encode(
            "utf-8"
        )

        req = urllib.request.Request(
            EMBED_URL,
            data=payload,
            headers={
                "Content-Type":
                    "application/json"
            },
            method="POST"
        )

        try:

            with urllib.request.urlopen(
                req,
                timeout=180
            ) as response:

                result = json.loads(
                    response
                    .read()
                    .decode(
                        "utf-8"
                    )
                )

        except Exception as exc:

            raise RuntimeError(
                "Embedding batch failed "
                f"at item {start + 1}: "
                f"{exc}"
            ) from exc

        if (
            not isinstance(
                result,
                list
            )
            or len(result)
            != len(batch)
        ):

            raise RuntimeError(
                "Unexpected embedding "
                "batch response."
            )

        for vector in result:

            if (
                not isinstance(
                    vector,
                    list
                )
                or len(vector)
                != EMBED_DIMENSIONS
            ):

                raise RuntimeError(
                    "Unexpected embedding "
                    "dimension."
                )

            vectors.append(
                vector
            )

        done = min(
            start
            + len(batch),
            total
        )

        print(
            f"  {done}/{total}"
        )

    if len(vectors) != total:

        raise RuntimeError(
            "Embedding count mismatch."
        )

    print(
        "Embedding precompute: PASS"
    )

    return vectors


def build_commit_sql(
    plan,
    vectors,
    replace_document_id=None
):

    section_units = plan[
        "section_units"
    ]

    exact_units = plan[
        "exact_units"
    ]

    semantic_units = plan[
        "semantic_units"
    ]

    if (
        len(vectors)
        != len(
            semantic_units
        )
    ):

        raise RuntimeError(
            "Vector count does not match "
            "semantic chunk count."
        )

    legislation_id = plan[
        "cap_key"
    ]

    version_date = plan[
        "version_date"
    ]

    language = plan[
        "language"
    ]

    document_title = (
        f"{plan['title']} "
        f"(Cap. {plan['chapter']})"
    )

    document_metadata = {
        "synthetic":
            False,

        "ingestion_version":
            "legal-v1",

        "parser_version":
            plan[
                "parser_version"
            ],

        "retrieval_schema":
            "legal-v1",

        "legislation_id":
            legislation_id,

        "chapter":
            plan[
                "chapter"
            ],

        "hkel_version_date":
            version_date,

        "source_format":
            "xml",

        "source_publisher":
            plan[
                "source_publisher"
            ],

        "responsible_authorities":
            plan[
                "responsible_authorities"
            ],

        "current_version":
            True,
    }

    sql = []

    sql.append(
        r"""
\set ON_ERROR_STOP on
BEGIN;
SET LOCAL statement_timeout = 0;
"""
    )

    # --------------------------------------------------------
    # Transaction-level duplicate / replacement guards
    # --------------------------------------------------------

    source_id = sql_quote(
        plan[
            "source_file_id"
        ]
    )

    checksum = sql_quote(
        plan[
            "checksum_sha256"
        ]
    )

    if replace_document_id is None:

        sql.append(
            f"""
DO $$
BEGIN

    IF EXISTS (
        SELECT 1
        FROM documents
        WHERE source_file_id =
            '{source_id}'
    ) THEN

        RAISE EXCEPTION
            'source_file_id already exists: %',
            '{source_id}';

    END IF;

    IF EXISTS (
        SELECT 1
        FROM documents
        WHERE checksum_sha256 =
            '{checksum}'
    ) THEN

        RAISE EXCEPTION
            'checksum already exists: %',
            '{checksum}';

    END IF;

END
$$;
"""
        )

    else:

        replace_document_id = int(
            replace_document_id
        )

        sql.append(
            f"""
DO $$
DECLARE
    v_cross_refs BIGINT;
    v_knowledge_items BIGINT;
BEGIN

    -- Lock the exact production document being replaced.
    PERFORM 1
    FROM documents
    WHERE
        id = {replace_document_id}
        AND source_file_id =
            '{source_id}'
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION
            'replacement target disappeared or changed: document_id=%',
            {replace_document_id};
    END IF;

        -- Incoming references do not block replacement:
    -- target foreign keys use ON DELETE SET NULL and can
    -- be re-resolved after the replacement.
    --
    -- Regenerable outgoing references also do not block:
    -- they are deleted with the old source document and
    -- rebuilt by their deterministic extractor.
    --
    -- Any outgoing reference that is curated, unknown, or
    -- otherwise non-regenerable blocks replacement.
    SELECT COUNT(*)
    INTO v_cross_refs
    FROM cross_references
    WHERE
        source_document_id =
            {replace_document_id}
        AND NOT (
            COALESCE(
                metadata->>'regenerable',
                'false'
            ) = 'true'
            AND COALESCE(
                metadata->>'extractor',
                ''
            ) <> ''
        );


    IF v_cross_refs <> 0 THEN
        RAISE EXCEPTION
            'replacement blocked: document_id=% has % non-regenerable outgoing cross_references',
            {replace_document_id},
            v_cross_refs;
    END IF;

    SELECT COUNT(*)
    INTO v_knowledge_items
    FROM knowledge_items
    WHERE source_document_id =
        {replace_document_id};

    IF v_knowledge_items <> 0 THEN
        RAISE EXCEPTION
            'replacement blocked: document_id=% has % knowledge_items',
            {replace_document_id},
            v_knowledge_items;
    END IF;

    -- Same checksum on the replacement target is expected.
    -- The same checksum on another document is not.
    IF EXISTS (
        SELECT 1
        FROM documents
        WHERE
            checksum_sha256 =
                '{checksum}'
            AND id <>
                {replace_document_id}
    ) THEN

        RAISE EXCEPTION
            'replacement blocked: checksum exists on another document';

    END IF;

END
$$;

DELETE FROM documents
WHERE
    id = {replace_document_id}
    AND source_file_id =
        '{source_id}';
"""
        )

    # --------------------------------------------------------
    # Document
    # --------------------------------------------------------

    sql.append(
        f"""
INSERT INTO documents (
    title,
    domain,
    topic,
    document_type,
    authority,
    jurisdiction,
    edition,
    version,
    effective_date,
    superseded,
    source_type,
    source_file_id,
    source_url,
    checksum_sha256,
    language,
    metadata
)
VALUES (
    {sql_literal(document_title)},
    {sql_literal(plan['domain'])},
    {sql_literal(plan['topic'])},
    'legislation',
    {sql_literal(plan['authority'])},
    'HK',
    NULL,
    {sql_literal(version_date)},
    NULL,
    FALSE,
    'hkel',
    {sql_literal(plan['source_file_id'])},
    {sql_literal(plan['source_url'])},
    {sql_literal(plan['checksum_sha256'])},
    {sql_literal(language)},
    {json_literal(document_metadata)}
);
"""
    )

    # --------------------------------------------------------
    # Sections
    #
    # Insert first with parent_section_id NULL.
    # Resolve hierarchy afterwards.
    # --------------------------------------------------------

    for unit in section_units:

        metadata = {
            "synthetic":
                False,

            "retrieval_schema":
                "legal-v1",

            "parser_version":
                plan[
                    "parser_version"
                ],

            "legislation_id":
                legislation_id,

            "version_date":
                version_date,

            "language":
                language,

            "raw_reference":
                unit.get(
                    "raw_reference"
                ),

            "parent_reference":
                unit.get(
                    "parent_reference"
                ),

            "level":
                unit.get(
                    "level"
                ),

            "xml_id":
                unit.get(
                    "xml_id"
                ),

            "temporal_id":
                unit.get(
                    "temporal_id"
                ),

            "operative":
                unit.get(
                    "operative"
                ),

            "repealed":
                unit.get(
                    "repealed"
                ),

            "not_in_operation":
                unit.get(
                    "not_in_operation"
                ),

            "omitted_as_spent":
                unit.get(
                    "omitted_as_spent"
                ),

            "schedule_number":
                unit.get(
                    "schedule_number"
                ),

            "part_name":
                unit.get(
                    "part_name"
                ),

            "embedded_quote":
                unit.get(
                    "embedded_quote"
                ),
        }

        sql.append(
            f"""
INSERT INTO sections (
    document_id,
    parent_section_id,
    section_number,
    heading,
    page_start,
    page_end,
    content,
    sort_order,
    metadata
)
VALUES (
    currval('documents_id_seq'),
    NULL,
    {sql_literal(unit['reference'])},
    {sql_literal(unit['heading'])},
    NULL,
    NULL,
    {sql_literal(unit['content'])},
    {int(unit['sort_order'])},
    {json_literal(metadata)}
);
"""
        )

    # Resolve parent hierarchy.
    sql.append(
        """
UPDATE sections AS child
SET parent_section_id =
    parent.id
FROM sections AS parent
WHERE
    child.document_id =
        currval('documents_id_seq')
    AND parent.document_id =
        child.document_id
    AND NULLIF(
        child.metadata
        ->> 'parent_reference',
        ''
    ) IS NOT NULL
    AND parent.section_number =
        child.metadata
        ->> 'parent_reference';
"""
    )

    # --------------------------------------------------------
    # Exact chunks
    # --------------------------------------------------------

    chunk_index = 0

    for unit in exact_units:

        metadata = {
            "synthetic":
                False,

            "retrieval_role":
                "legal-exact",

            "retrieval_schema":
                "legal-v1",

            "legislation_id":
                legislation_id,

            "version_date":
                version_date,

            "language":
                language,

            "reference":
                unit[
                    "reference"
                ],

            "exact_part":
                unit.get(
                    "exact_part",
                    1
                ),

            "exact_parts":
                unit.get(
                    "exact_parts",
                    1
                ),

            "full_length":
                unit.get(
                    "full_length"
                ),

            "operative":
                unit.get(
                    "operative"
                ),

            "repealed":
                unit.get(
                    "repealed"
                ),

            "not_in_operation":
                unit.get(
                    "not_in_operation"
                ),

            "omitted_as_spent":
                unit.get(
                    "omitted_as_spent"
                ),

            "level":
                unit.get(
                    "level"
                ),

            "xml_id":
                unit.get(
                    "xml_id"
                ),

            "temporal_id":
                unit.get(
                    "temporal_id"
                ),
        }

        ref = sql_quote(
            unit[
                "reference"
            ]
        )

        sql.append(
            f"""
INSERT INTO chunks (
    document_id,
    section_id,
    chunk_index,
    content,
    token_count,
    page_start,
    page_end,
    metadata
)
VALUES (
    currval('documents_id_seq'),

    (
        SELECT id
        FROM sections
        WHERE
            document_id =
                currval(
                    'documents_id_seq'
                )
            AND section_number =
                '{ref}'
        LIMIT 1
    ),

    {chunk_index},

    {sql_literal(unit['content'])},

    NULL,
    NULL,
    NULL,

    {json_literal(metadata)}
);
"""
        )

        chunk_index += 1

    # --------------------------------------------------------
    # Semantic chunks
    # --------------------------------------------------------

    semantic_chunk_indices = []

    for unit in semantic_units:

        reference = (
            unit.get(
                "reference"
            )
            or unit.get(
                "parent_reference"
            )
        )

        metadata = {
            "synthetic":
                False,

            "retrieval_role":
                "legal-semantic",

            "retrieval_schema":
                "legal-v1",

            "legislation_id":
                legislation_id,

            "version_date":
                version_date,

            "language":
                language,

            "semantic_type":
                unit.get(
                    "semantic_type"
                ),

            "reference":
                unit.get(
                    "reference"
                ),

            "parent_reference":
                unit.get(
                    "parent_reference"
                ),

            "definition_name":
                unit.get(
                    "definition_name"
                ),

            "semantic_part":
                unit.get(
                    "semantic_part",
                    1
                ),

            "semantic_parts":
                unit.get(
                    "semantic_parts",
                    1
                ),

            "source_xml_id":
                unit.get(
                    "source_xml_id"
                ),

            "operative":
                unit.get(
                    "operative",
                    True
                ),

            "repealed":
                unit.get(
                    "repealed",
                    False
                ),

            "not_in_operation":
                unit.get(
                    "not_in_operation",
                    False
                ),

            "omitted_as_spent":
                unit.get(
                    "omitted_as_spent",
                    False
                ),
        }

        if reference:

            section_sql = f"""
(
    SELECT id
    FROM sections
    WHERE
        document_id =
            currval(
                'documents_id_seq'
            )
        AND section_number =
            {sql_literal(reference)}
    LIMIT 1
)
"""

        else:

            section_sql = "NULL"

        sql.append(
            f"""
INSERT INTO chunks (
    document_id,
    section_id,
    chunk_index,
    content,
    token_count,
    page_start,
    page_end,
    metadata
)
VALUES (
    currval('documents_id_seq'),
    {section_sql},
    {chunk_index},
    {sql_literal(unit['content'])},
    NULL,
    NULL,
    NULL,
    {json_literal(metadata)}
);
"""
        )

        semantic_chunk_indices.append(
            chunk_index
        )

        chunk_index += 1

    # --------------------------------------------------------
    # Embeddings
    # --------------------------------------------------------

    for (
        target_chunk_index,
        vector
    ) in zip(
        semantic_chunk_indices,
        vectors
    ):

        vector_literal = (
            "["
            + ",".join(
                format(
                    float(x),
                    ".9g"
                )
                for x in vector
            )
            + "]"
        )

        sql.append(
            f"""
INSERT INTO embeddings (
    chunk_id,
    provider,
    model,
    dimensions,
    embedding
)
VALUES (
    (
        SELECT id
        FROM chunks
        WHERE
            document_id =
                currval(
                    'documents_id_seq'
                )
            AND chunk_index =
                {target_chunk_index}
        LIMIT 1
    ),
    'local',
    'multilingual-e5-small',
    384,
    '{vector_literal}'::vector
);
"""
        )

    expected_sections = len(
        section_units
    )

    expected_chunks = (
        len(
            exact_units
        )
        + len(
            semantic_units
        )
    )

    expected_embeddings = len(
        semantic_units
    )

    expected_exact = len(
        exact_units
    )

    expected_semantic = len(
        semantic_units
    )

    # --------------------------------------------------------
    # Transaction validation
    # --------------------------------------------------------

    sql.append(
        f"""
DO $$
DECLARE
    v_document_id BIGINT;
    v_sections BIGINT;
    v_chunks BIGINT;
    v_embeddings BIGINT;
    v_exact BIGINT;
    v_semantic BIGINT;
    v_dangling_parents BIGINT;
    v_null_exact_sections BIGINT;
BEGIN

    v_document_id :=
        currval(
            'documents_id_seq'
        );

    SELECT COUNT(*)
    INTO v_sections
    FROM sections
    WHERE document_id =
        v_document_id;

    SELECT COUNT(*)
    INTO v_chunks
    FROM chunks
    WHERE document_id =
        v_document_id;

    SELECT COUNT(*)
    INTO v_embeddings
    FROM embeddings e
    JOIN chunks c
        ON c.id = e.chunk_id
    WHERE c.document_id =
        v_document_id;

    SELECT COUNT(*)
    INTO v_exact
    FROM chunks
    WHERE
        document_id =
            v_document_id
        AND metadata
            ->> 'retrieval_role'
            = 'legal-exact';

    SELECT COUNT(*)
    INTO v_semantic
    FROM chunks
    WHERE
        document_id =
            v_document_id
        AND metadata
            ->> 'retrieval_role'
            = 'legal-semantic';

    SELECT COUNT(*)
    INTO v_dangling_parents
    FROM sections
    WHERE
        document_id =
            v_document_id
        AND NULLIF(
            metadata
            ->> 'parent_reference',
            ''
        ) IS NOT NULL
        AND parent_section_id
            IS NULL;

    SELECT COUNT(*)
    INTO v_null_exact_sections
    FROM chunks
    WHERE
        document_id =
            v_document_id
        AND metadata
            ->> 'retrieval_role'
            = 'legal-exact'
        AND section_id
            IS NULL;

    IF v_sections <> {expected_sections}
    THEN
        RAISE EXCEPTION
            'section validation failed: %',
            v_sections;
    END IF;

    IF v_chunks <> {expected_chunks}
    THEN
        RAISE EXCEPTION
            'chunk validation failed: %',
            v_chunks;
    END IF;

    IF v_embeddings <>
        {expected_embeddings}
    THEN
        RAISE EXCEPTION
            'embedding validation failed: %',
            v_embeddings;
    END IF;

    IF v_exact <> {expected_exact}
    THEN
        RAISE EXCEPTION
            'exact chunk validation failed: %',
            v_exact;
    END IF;

    IF v_semantic <>
        {expected_semantic}
    THEN
        RAISE EXCEPTION
            'semantic chunk validation failed: %',
            v_semantic;
    END IF;

    IF v_dangling_parents <> 0
    THEN
        RAISE EXCEPTION
            'dangling parent validation failed: %',
            v_dangling_parents;
    END IF;

    IF v_null_exact_sections <> 0
    THEN
        RAISE EXCEPTION
            'exact chunk section mapping failed: %',
            v_null_exact_sections;
    END IF;

END
$$;

COMMIT;
"""
    )

    return "\n".join(
        sql
    )


def commit_plan(
    plan,
    replace_existing=False
):

    # --------------------------------------------------------
    # Shared pre-flight validation
    # --------------------------------------------------------

    source_file_id = sql_quote(
        plan[
            "source_file_id"
        ]
    )

    checksum = sql_quote(
        plan[
            "checksum_sha256"
        ]
    )

    if not plan.get(
        "source_url"
    ):

        raise SystemExit(
            "ABORT: source_url is empty."
        )

    if not plan.get(
        "authority"
    ):

        raise SystemExit(
            "ABORT: authority is empty."
        )

    existing_source = psql_query(
        f"""
SELECT id
FROM documents
WHERE source_file_id =
    '{source_file_id}'
LIMIT 1;
"""
    )

    replace_document_id = None

    # --------------------------------------------------------
    # Normal ingestion
    # --------------------------------------------------------

    if not replace_existing:

        if existing_source:

            raise SystemExit(
                "ABORT: this HKeL version "
                "is already ingested as "
                f"document_id={existing_source}"
            )

        existing_checksum = psql_query(
            f"""
SELECT id
FROM documents
WHERE checksum_sha256 =
    '{checksum}'
LIMIT 1;
"""
        )

        if existing_checksum:

            raise SystemExit(
                "ABORT: identical source "
                "checksum already exists as "
                f"document_id={existing_checksum}"
            )

    # --------------------------------------------------------
    # Explicit replacement mode
    # --------------------------------------------------------

    else:

        if not existing_source:

            raise SystemExit(
                "ABORT: --replace-existing requires "
                "an existing document with the same "
                "source_file_id."
            )

        try:

            replace_document_id = int(
                existing_source
                .strip()
                .splitlines()[0]
            )

        except Exception:

            raise SystemExit(
                "ABORT: could not resolve the "
                "existing document id."
            )

        other_checksum = psql_query(
            f"""
SELECT id
FROM documents
WHERE
    checksum_sha256 =
        '{checksum}'
    AND id <>
        {replace_document_id}
LIMIT 1;
"""
        )

        if other_checksum:

            raise SystemExit(
                "ABORT: identical checksum exists "
                "on another document_id="
                f"{other_checksum}"
            )

        cross_refs = psql_query(
            f"""
SELECT COUNT(*)
FROM cross_references
WHERE
    source_document_id =
        {replace_document_id}
    AND NOT (
        COALESCE(
            metadata->>'regenerable',
            'false'
        ) = 'true'
        AND COALESCE(
            metadata->>'extractor',
            ''
        ) <> ''
    );
"""
        )

        knowledge_items = psql_query(
            f"""
SELECT COUNT(*)
FROM knowledge_items
WHERE source_document_id =
    {replace_document_id};
"""
        )

        try:
            cross_ref_count = int(
                cross_refs.strip()
                if cross_refs
                else "0"
            )

            knowledge_item_count = int(
                knowledge_items.strip()
                if knowledge_items
                else "0"
            )

        except ValueError:

            raise SystemExit(
                "ABORT: could not validate "
                "replacement dependencies."
            )

        if cross_ref_count != 0:

            raise SystemExit(
                "ABORT: replacement blocked; "
                f"document_id={replace_document_id} "
                f"has {cross_ref_count} "
                "non-regenerable outgoing "
                "cross_references."
            )

        if knowledge_item_count != 0:

            raise SystemExit(
                "ABORT: replacement blocked; "
                f"document_id={replace_document_id} "
                f"has {knowledge_item_count} "
                "knowledge_items."
            )

    # --------------------------------------------------------
    # Summary
    # --------------------------------------------------------

    print("=" * 76)

    if replace_existing:
        print(
            "HKEL PRODUCTION REPLACEMENT"
        )
    else:
        print(
            "HKEL PRODUCTION INGESTION"
        )

    print("=" * 76)

    print(
        "Legislation:",
        plan[
            "cap_key"
        ]
    )

    print(
        "Version:",
        plan[
            "version_date"
        ]
    )

    if replace_existing:

        print(
            "Replacing document_id:",
            replace_document_id
        )

    print(
        "Sections:",
        len(
            plan[
                "section_units"
            ]
        )
    )

    print(
        "Exact chunks:",
        len(
            plan[
                "exact_units"
            ]
        )
    )

    print(
        "Semantic chunks:",
        len(
            plan[
                "semantic_units"
            ]
        )
    )

    print(
        "Embeddings:",
        len(
            plan[
                "semantic_units"
            ]
        )
    )

    # --------------------------------------------------------
    # All vectors are built before touching PostgreSQL.
    # --------------------------------------------------------

    vectors = embed_semantic_units(
        plan[
            "semantic_units"
        ]
    )

    print()
    print(
        "Building PostgreSQL transaction..."
    )

    sql_script = build_commit_sql(
        plan,
        vectors,
        replace_document_id=
            replace_document_id
    )

    print(
        "Executing atomic transaction..."
    )

    result = subprocess.run(
        [
            "docker",
            "exec",
            "-i",
            DB_CONTAINER,
            "psql",
            "-U",
            "ai_knowledge",
            "-d",
            "ai_knowledge",
            "-q",
            "-v",
            "ON_ERROR_STOP=1",
        ],
        input=sql_script,
        text=True,
        capture_output=True,
    )

    if result.returncode != 0:

        print()
        print(
            "INGESTION FAILED."
        )

        print(
            "PostgreSQL transaction "
            "was not committed."
        )

        print()

        print(
            result.stderr.strip()
        )

        raise SystemExit(
            result.returncode
        )

    # --------------------------------------------------------
    # Post-commit verification
    # --------------------------------------------------------

    source_id = sql_quote(
        plan[
            "source_file_id"
        ]
    )

    verification = psql_query(
        f"""
SELECT
    d.id,
    (
        SELECT COUNT(*)
        FROM sections s
        WHERE s.document_id = d.id
    ),
    (
        SELECT COUNT(*)
        FROM chunks c
        WHERE c.document_id = d.id
    ),
    (
        SELECT COUNT(*)
        FROM embeddings e
        JOIN chunks c
            ON c.id = e.chunk_id
        WHERE c.document_id = d.id
    )
FROM documents d
WHERE d.source_file_id =
    '{source_id}';
"""
    )

    print()
    print("=" * 76)

    if replace_existing:
        print(
            "REPLACEMENT COMMITTED"
        )
    else:
        print(
            "INGESTION COMMITTED"
        )

    print("=" * 76)

    print(
        "document_id | sections | "
        "chunks | embeddings"
    )

    print(
        verification
    )

    print()
    print(
        "Source ID:",
        plan[
            "source_file_id"
        ]
    )

    print(
        "Post-commit validation: PASS"
    )


def main():

    parser = argparse.ArgumentParser(
        description=(
            "Plan or ingest HKeL "
            "structured legislation."
        )
    )

    parser.add_argument(
        "legislation",
        help=(
            "e.g. CAP_123, "
            "Cap.123 or 123"
        )
    )

    mode = (
        parser
        .add_mutually_exclusive_group(
            required=True
        )
    )

    mode.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Analyze ingestion plan "
            "without writing anything."
        )
    )

    mode.add_argument(
        "--commit",
        action="store_true",
        help=(
            "Perform production "
            "transactional ingestion."
        )
    )

    mode.add_argument(
        "--replace-existing",
        action="store_true",
        help=(
            "Atomically replace an existing "
            "HKeL source version. Replacement "
            "is blocked by non-regenerable "
            "outgoing cross-references or "
            "knowledge items."
        )
    )

    args = parser.parse_args()

    cap_key = normalize_cap(
        args.legislation
    )

    plan = build_plan(
        cap_key
    )

    if args.dry_run:

        show_plan(
            plan
        )

        return

    commit_plan(
        plan,
        replace_existing=
            args.replace_existing
    )


if __name__ == "__main__":
    main()
