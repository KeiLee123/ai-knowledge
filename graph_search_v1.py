#!/usr/bin/env python3

import argparse
import json
import os
import re
import subprocess
import sys


SCRIPT_DIR = os.path.dirname(
    os.path.realpath(__file__)
)

if SCRIPT_DIR not in sys.path:
    sys.path.insert(
        0,
        SCRIPT_DIR,
    )


from section_evidence_resolver_v1 import (
    resolve_edge
    as resolve_section_evidence_edge,
)


DB_CONTAINER = (
    "ai-knowledge-db-jiyckdrlappwgimwebnzxwmr"
)

HYBRID_SEARCH = (
    "/opt/ai-knowledge/"
    "hybrid_search_v3.py"
)

DOC_EXTRACTOR = "explicit-reference-v1"

SECTION_EXTRACTOR = (
    "explicit-section-reference-v1"
)


# ============================================================
# PostgreSQL
# ============================================================

def psql(sql):

    p = subprocess.run(
        [
            "docker", "exec", "-i",
            DB_CONTAINER,
            "psql",
            "-U", "ai_knowledge",
            "-d", "ai_knowledge",
            "-At",
            "-v", "ON_ERROR_STOP=1",
        ],
        input=sql,
        text=True,
        capture_output=True,
    )

    if p.returncode != 0:

        print(
            p.stderr,
            file=sys.stderr,
        )

        raise SystemExit(
            "Database query failed."
        )

    return [
        line
        for line in p.stdout.splitlines()
        if line.strip()
    ]


# ============================================================
# Hybrid reference normalization
# ============================================================

def normalize_hybrid_refs(value):

    if not value:
        return ""

    items = []

    for raw in value.split(","):

        ref = raw.strip()

        if not ref:
            continue

        # Hybrid Search v3 currently resolves canonical
        # statutory references such as:
        #
        #   3(3)
        #   16(3A)
        #
        # but not the display-style form:
        #
        #   s.3(3)
        #
        # Normalize only clear statutory section refs.
        m = re.fullmatch(
            r's\.\s*'
            r'([0-9]+[A-Za-z]*'
            r'(?:\([0-9A-Za-z]+\))*)',
            ref,
            re.I,
        )

        if m:
            ref = m.group(1)

        items.append(ref)

    return ",".join(items)


# ============================================================
# Graph target-query context
# ============================================================

def sanitize_graph_context(
    content,
    source_ref,
):

    text = (
        content
        or ""
    )

    text = re.sub(
        r'\s+',
        ' ',
        text,
    ).strip()


    # --------------------------------------------------------
    # Remove generated source prefix where possible.
    #
    # Example:
    #
    # Cap. 636 Fire Safety ... 3(3).
    # (3)However, ...
    #
    # becomes:
    #
    # (3)However, ...
    # --------------------------------------------------------

    source_section = ""

    if (
        source_ref
        and ":"
        in source_ref
    ):

        source_section = (
            source_ref.split(
                ":",
                1,
            )[1]
        )


    if source_section:

        marker = (
            source_section
            + "."
        )

        pos = text.find(
            marker
        )

        if pos >= 0:

            text = text[
                pos
                + len(marker):
            ].strip()


    # Definition semantic chunks often do not repeat
    # their canonical section number.
    text = re.sub(
        r'^Cap\.\s*'
        r'[0-9]+[A-Z]?\s+'
        r'[^.]{1,180}\.\s*',
        '',
        text,
        count=1,
        flags=re.I,
    )


    text = re.sub(
        r'^Definition:\s*',
        '',
        text,
        count=1,
        flags=re.I,
    )


    # --------------------------------------------------------
    # Remove Cap. identifiers from the target-scoped query.
    #
    # Otherwise a source citation such as Cap.636 can
    # conflict with a target document scope such as Cap.572.
    # --------------------------------------------------------

    text = re.sub(
        r'\(\s*Cap\.?\s*'
        r'[0-9]+[A-Z]?'
        r'(?:\s*,?\s*'
        r'sub\.?\s*leg\.?'
        r'(?:\s*,?\s*'
        r'[A-Z][A-Z0-9]*)?'
        r')?'
        r'\s*\)',
        '',
        text,
        flags=re.I,
    )

    text = re.sub(
        r'\bCap\.?\s*'
        r'[0-9]+[A-Z]?\b',
        '',
        text,
        flags=re.I,
    )


    text = re.sub(
        r'\s+',
        ' ',
        text,
    ).strip()


    return text


# ============================================================
# Hybrid Search v3 subprocess
# ============================================================

def run_hybrid(
    query,
    english_query,
    terms="",
    refs="",
    document_title="",
    limit=5,
    include_synthetic=False,
    strict=True,
):

    cmd = [
        "python3",
        HYBRID_SEARCH,
        "--query",
        query,
        "--english-query",
        english_query,
        "--limit",
        str(limit),
        "--json-output",
    ]

    if terms:
        cmd.extend([
            "--terms",
            terms,
        ])

    normalized_refs = (
        normalize_hybrid_refs(
            refs
        )
    )

    if normalized_refs:
        cmd.extend([
            "--refs",
            normalized_refs,
        ])

    if document_title:
        cmd.extend([
            "--document-title",
            document_title,
        ])

    if include_synthetic:
        cmd.append(
            "--include-synthetic"
        )


    p = subprocess.run(
        cmd,
        text=True,
        capture_output=True,
    )


    if p.returncode != 0:

        if strict:

            if p.stdout.strip():

                print(
                    p.stdout.strip(),
                    file=sys.stderr,
                )

            if p.stderr.strip():

                print(
                    p.stderr.strip(),
                    file=sys.stderr,
                )

            raise SystemExit(
                "Hybrid Search v3 failed."
            )

        return {
            "ok": False,
            "error": (
                p.stderr.strip()
                or p.stdout.strip()
                or "Hybrid retrieval failed."
            ),
        }


    raw = p.stdout.strip()


    try:

        payload = json.loads(
            raw
        )

    except json.JSONDecodeError:

        if strict:

            print(
                raw,
                file=sys.stderr,
            )

            raise SystemExit(
                "Hybrid Search v3 did not "
                "return valid JSON."
            )

        return {
            "ok": False,
            "error": (
                "Scoped retrieval did not "
                "return JSON."
            ),
            "raw_output": raw,
        }


    return {
        "ok": True,
        "payload": payload,
    }


# ============================================================
# Exact-chunk -> graph citation bridge
# ============================================================

def content_mentions_graph_target(
    content,
    link,
):

    """
    Used only for the conservative section fallback.

    A primary legal-exact chunk may have a different chunk_id
    from the legal-semantic chunks stored in graph provenance.

    We allow section-based bridging only when the exact chunk
    itself explicitly contains the graph target citation.
    """

    text = content or ""

    target = (
        link.get("target_document_ref")
        or link.get("target_ref")
        or ""
    )


    # Section-level target_ref may look like:
    #
    #   CAP_123:2(1)
    #
    # target_document_ref is preferred above, but normalize
    # defensively if needed.
    target = target.split(
        ":",
        1,
    )[0]


    # --------------------------------------------------------
    # Principal Ordinance
    #
    # CAP_123
    # --------------------------------------------------------

    m = re.fullmatch(
        r'CAP_([0-9]+[A-Z]?)',
        target,
        re.I,
    )

    if m:

        cap = re.escape(
            m.group(1)
        )

        return bool(
            re.search(
                rf'\bCap\.?\s*{cap}\b',
                text,
                re.I,
            )
        )


    # --------------------------------------------------------
    # Subsidiary legislation
    #
    # CAP_123_SUBLEG_A
    # --------------------------------------------------------

    m = re.fullmatch(
        r'CAP_([0-9]+[A-Z]?)'
        r'_SUBLEG_([A-Z0-9]+)',
        target,
        re.I,
    )

    if m:

        cap = re.escape(
            m.group(1)
        )

        code = re.escape(
            m.group(2)
        )

        return bool(
            re.search(
                rf'\bCap\.?\s*{cap}'
                rf'\s*,?\s*'
                rf'sub\.?\s*leg\.?'
                rf'\s*,?\s*{code}\b',
                text,
                re.I,
            )
        )


    # --------------------------------------------------------
    # Unspecified subsidiary legislation
    # --------------------------------------------------------

    m = re.fullmatch(
        r'CAP_([0-9]+[A-Z]?)'
        r'_SUBLEG_UNSPECIFIED',
        target,
        re.I,
    )

    if m:

        cap = re.escape(
            m.group(1)
        )

        return bool(
            re.search(
                rf'\bCap\.?\s*{cap}'
                rf'\s*,?\s*'
                rf'sub\.?\s*leg\.?',
                text,
                re.I,
            )
        )


    return False


# ============================================================
# Graph lookup
#
# We deliberately use source_chunk_ids from graph provenance
# rather than relying only on chunks.section_id.
#
# This also handles recovered orphan semantic chunks such as
# CAP_51 chunk 12778.
# ============================================================

def load_graph_links(
    primary_results,
):

    seeds = []

    for item in primary_results:

        chunk_id = item.get(
            "chunk_id"
        )

        rank = item.get(
            "rank"
        )

        if chunk_id is None:
            continue

        seeds.append(
            (
                int(chunk_id),
                int(rank),
            )
        )


    if not seeds:
        return []


    values = ",\n".join(
        f"({chunk_id}::bigint,"
        f"{rank}::integer)"
        for chunk_id, rank
        in seeds
    )


    rows = psql(f"""
WITH seeds(
    chunk_id,
    seed_rank
) AS (

    VALUES
    {values}
),

seed_chunks AS (

    SELECT
        seeds.chunk_id,
        seeds.seed_rank,
        c.section_id,
        c.content

    FROM seeds

    JOIN chunks c
        ON c.id =
            seeds.chunk_id
)

SELECT json_build_object(

    'trigger_chunk_id',
        seed_chunks.chunk_id,

    'trigger_rank',
        seed_chunks.seed_rank,

    'trigger_section_id',
        seed_chunks.section_id,

    'trigger_content',
        seed_chunks.content,

    'relationship',
        cr.relationship,

    'edge_key',
        cr.metadata->>'edge_key',

    'parent_edge_key',
        cr.metadata->>'parent_edge_key',

    'source_ref',
        cr.metadata->>'source_ref',

    'source_chunk_ids',
        cr.metadata->'source_chunk_ids',

    'target_ref',
        cr.metadata->>'target_ref',

    'target_document_ref',
        COALESCE(
            cr.metadata->>'target_document_ref',
            cr.metadata->>'target_ref'
        ),

    'target_section_ref',
        cr.metadata->>'target_section_ref',

    'resolution_status',
        cr.metadata->>'resolution_status',

    'target_document_id',
        cr.target_document_id,

    'target_section_id',
        cr.target_section_id,

    'target_document_title',
        td.title,

    'target_section_number',
        ts.section_number,

    'target_heading',
        ts.heading,

    'direct_provenance_match',
        EXISTS (

            SELECT 1

            FROM jsonb_array_elements_text(
                COALESCE(
                    cr.metadata->'source_chunk_ids',
                    '[]'::jsonb
                )
            ) AS source_chunk(value)

            WHERE
                source_chunk.value::bigint =
                    seed_chunks.chunk_id
        )

)::text

FROM seed_chunks

JOIN cross_references cr

    ON (

        EXISTS (

            SELECT 1

            FROM jsonb_array_elements_text(
                COALESCE(
                    cr.metadata->'source_chunk_ids',
                    '[]'::jsonb
                )
            ) AS source_chunk(value)

            WHERE
                source_chunk.value::bigint =
                    seed_chunks.chunk_id
        )

        OR

        (
            seed_chunks.section_id
                IS NOT NULL

            AND cr.source_section_id =
                seed_chunks.section_id
        )
    )

LEFT JOIN documents td
    ON td.id =
        cr.target_document_id

LEFT JOIN sections ts
    ON ts.id =
        cr.target_section_id

WHERE

    (
        cr.relationship =
            'explicit-section-reference'

        AND cr.metadata->>'extractor' =
            '{SECTION_EXTRACTOR}'
    )

    OR

    (
        cr.relationship =
            'explicit-reference'

        AND cr.metadata->>'extractor' =
            '{DOC_EXTRACTOR}'
    )

ORDER BY

    seed_chunks.seed_rank,

    CASE
        WHEN cr.relationship =
            'explicit-section-reference'
        THEN 0
        ELSE 1
    END,

    cr.metadata->>'target_ref',

    cr.id;
""")


    candidates = [
        json.loads(line)
        for line in rows
    ]


    links = []


    for link in candidates:

        if link.get(
            "direct_provenance_match"
        ):

            link[
                "source_match_mode"
            ] = "direct-provenance"

            links.append(
                link
            )

            continue


        # ----------------------------------------------------
        # Section fallback is allowed only when the exact
        # primary chunk itself visibly cites the target.
        #
        # This prevents an Interpretation section from
        # pulling every graph edge attached anywhere in
        # that large section.
        # ----------------------------------------------------

        if content_mentions_graph_target(
            link.get(
                "trigger_content",
                "",
            ),
            link,
        ):

            link[
                "source_match_mode"
            ] = (
                "section-citation-fallback"
            )

            links.append(
                link
            )


    # Remove internal trigger content from output payload.
    for link in links:

        link.pop(
            "trigger_content",
            None,
        )

        link.pop(
            "direct_provenance_match",
            None,
        )


    # --------------------------------------------------------
    # A document-level edge may have both:
    #
    #   explicit-reference
    #
    # and a more precise child:
    #
    #   explicit-section-reference
    #
    # For the same trigger chunk, prefer the precise child.
    # --------------------------------------------------------

    section_coverage = set()


    for link in links:

        if (
            link["relationship"]
            != "explicit-section-reference"
        ):
            continue

        parent_edge_key = (
            link.get(
                "parent_edge_key"
            )
        )

        if not parent_edge_key:
            continue

        section_coverage.add(
            (
                int(
                    link[
                        "trigger_chunk_id"
                    ]
                ),
                parent_edge_key,
            )
        )


    for link in links:

        link[
            "covered_by_section_edge"
        ] = False

        if (
            link["relationship"]
            != "explicit-reference"
        ):
            continue

        key = (
            int(
                link[
                    "trigger_chunk_id"
                ]
            ),
            link[
                "edge_key"
            ],
        )

        if key in section_coverage:

            link[
                "covered_by_section_edge"
            ] = True


    return links


# ============================================================
# Reference formatting for Hybrid Search v3
# ============================================================

def hybrid_section_ref(
    section_ref,
):

    if not section_ref:
        return ""


    # Schedule-style canonical references are left intact.
    if re.match(
        r'^(?:Sch\.|Schedule\b)',
        section_ref,
        re.I,
    ):

        return section_ref


    # Hybrid Search v3 exact-reference resolver
    # currently expects canonical forms such as:
    #
    #   2(1)
    #   17(2)(b)
    #
    # rather than display forms such as s.2(1).
    return section_ref


# ============================================================
# Graph path
# ============================================================

def graph_path(link):

    source = (
        link.get("source_ref")
        or "unknown-source"
    )


    if (
        link["relationship"]
        == "explicit-section-reference"
    ):

        target = (
            link.get(
                "target_document_ref"
            )
            or "unknown-target"
        )

        section_ref = (
            link.get(
                "target_section_ref"
            )
        )

        if section_ref:

            target = (
                target
                + ":"
                + section_ref
            )


    else:

        target = (
            link.get("target_ref")
            or "unknown-target"
        )


    return (
        source
        + " -> "
        + target
    )


# ============================================================
# Graph evidence retrieval
# ============================================================

# ============================================================
# Source Activation v1
# ============================================================

def sanitize_activation_query(
    value,
):

    """
    Source activation must be semantic.

    Remove explicit statutory reference tokens so Hybrid
    Search v3 does not switch back into exact-reference mode.
    """

    text = (
        value
        or ""
    )


    # Cap. 610 / Cap.610
    text = re.sub(
        r'\bCap\.?\s*'
        r'[0-9]+[A-Z]?\b',
        ' ',
        text,
        flags=re.I,
    )


    # s.2(1)
    # section 2(1)
    # sections 2(1)
    text = re.sub(
        r'\b(?:s\.|sections?)\s*'
        r'[0-9]+[A-Za-z]*'
        r'(?:\([0-9A-Za-z]+\))*'
        r'(?![0-9A-Za-z(])',
        ' ',
        text,
        flags=re.I,
    )


    text = re.sub(
        r'\s+',
        ' ',
        text,
    ).strip()


    return text


def deduplicate_graph_links(
    links,
):

    """
    One graph edge may be discovered through multiple coarse
    exact chunks.

    Collapse by relationship + edge_key while preserving all
    trigger provenance.
    """

    grouped = {}


    for link in links:

        key = (
            link.get(
                "relationship"
            ),
            link.get(
                "edge_key"
            ),
        )


        if key not in grouped:

            base = dict(
                link
            )

            base[
                "trigger_matches"
            ] = []

            grouped[
                key
            ] = base


        grouped[
            key
        ][
            "trigger_matches"
        ].append({
            "trigger_rank":
                link.get(
                    "trigger_rank"
                ),

            "trigger_chunk_id":
                link.get(
                    "trigger_chunk_id"
                ),

            "source_match_mode":
                link.get(
                    "source_match_mode"
                ),
        })


    output = []


    for base in grouped.values():

        trigger_matches = (
            base[
                "trigger_matches"
            ]
        )


        trigger_matches.sort(
            key=lambda x: (
                x.get(
                    "trigger_rank"
                )
                if x.get(
                    "trigger_rank"
                )
                is not None
                else 999999,

                x.get(
                    "trigger_chunk_id"
                )
                if x.get(
                    "trigger_chunk_id"
                )
                is not None
                else 999999,
            )
        )


        first = trigger_matches[0]


        base[
            "trigger_rank"
        ] = first.get(
            "trigger_rank"
        )

        base[
            "trigger_chunk_id"
        ] = first.get(
            "trigger_chunk_id"
        )


        match_modes = {
            x.get(
                "source_match_mode"
            )

            for x in trigger_matches
        }


        if (
            "direct-provenance"
            in match_modes
        ):

            base[
                "source_match_mode"
            ] = "direct-provenance"

        else:

            base[
                "source_match_mode"
            ] = (
                "section-citation-fallback"
            )


        output.append(
            base
        )


    output.sort(
        key=lambda x: (
            x.get(
                "trigger_rank"
            )
            if x.get(
                "trigger_rank"
            )
            is not None
            else 999999,

            0
            if x.get(
                "relationship"
            )
            == "explicit-section-reference"
            else 1,

            x.get(
                "edge_key"
            )
            or "",
        )
    )


    return output


def activate_graph_links(
    links,
    primary_results,
    query,
    english_query,
    terms,
    include_synthetic,
    activation_limit,
):

    """
    Decide which candidate graph edges are relevant to the
    current query.

    Direct provenance is always active.

    Coarse exact-chunk fallback requires a secondary semantic
    activation hit against one of the graph edge's own
    source_chunk_ids.
    """

    links = (
        deduplicate_graph_links(
            links
        )
    )


    primary_by_chunk = {
        int(
            item[
                "chunk_id"
            ]
        ): item

        for item in primary_results

        if item.get(
            "chunk_id"
        )
        is not None
    }


    # --------------------------------------------------------
    # Identify source documents that require semantic
    # activation.
    # --------------------------------------------------------

    activation_documents = {}


    for link in links:

        if (
            link.get(
                "source_match_mode"
            )
            != "section-citation-fallback"
        ):

            continue


        titles = []


        for trigger in (
            link.get(
                "trigger_matches"
            )
            or []
        ):

            chunk_id = trigger.get(
                "trigger_chunk_id"
            )


            if chunk_id is None:
                continue


            primary = (
                primary_by_chunk.get(
                    int(
                        chunk_id
                    )
                )
                or {}
            )


            title = primary.get(
                "document"
            )


            if (
                title
                and title not in titles
            ):

                titles.append(
                    title
                )


        if titles:

            link[
                "activation_document_title"
            ] = titles[0]

            activation_documents[
                titles[0]
            ] = None


    # --------------------------------------------------------
    # Semantic activation query:
    # remove statutory reference syntax but retain the
    # substantive concept being asked.
    # --------------------------------------------------------

    activation_query = (
        sanitize_activation_query(
            query
        )
    )

    activation_english = (
        sanitize_activation_query(
            english_query
        )
    )


    if not activation_query:

        activation_query = (
            activation_english
        )


    if not activation_english:

        activation_english = (
            activation_query
        )


    activation_results = {}


    for document_title in (
        activation_documents
    ):

        result = run_hybrid(
            query=activation_query,
            english_query=(
                activation_english
            ),
            terms=terms,
            refs="",
            document_title=(
                document_title
            ),
            limit=activation_limit,
            include_synthetic=(
                include_synthetic
            ),
            strict=False,
        )


        if not result.get(
            "ok"
        ):

            activation_results[
                document_title
            ] = {
                "ok":
                    False,

                "error":
                    result.get(
                        "error"
                    ),
            }

            continue


        items = (
            result[
                "payload"
            ].get(
                "results",
                []
            )
        )


        activation_results[
            document_title
        ] = {
            "ok":
                True,

            "results":
                items,

            "chunk_ranks":
                {
                    int(
                        item[
                            "chunk_id"
                        ]
                    ):
                    int(
                        item[
                            "rank"
                        ]
                    )

                    for item in items

                    if item.get(
                        "chunk_id"
                    )
                    is not None
                },
        }


    # --------------------------------------------------------
    # Activate / suppress candidate edges.
    # --------------------------------------------------------

    for link in links:

        if (
            link.get(
                "source_match_mode"
            )
            == "direct-provenance"
        ):

            link[
                "activation_status"
            ] = "active"

            link[
                "activation_mode"
            ] = "direct-provenance"

            link[
                "activation_chunk_ids"
            ] = [
                int(
                    x
                )
                for x in (
                    link.get(
                        "source_chunk_ids"
                    )
                    or []
                )
                if int(
                    x
                )
                in {
                    int(
                        trigger.get(
                            "trigger_chunk_id"
                        )
                    )

                    for trigger in (
                        link.get(
                            "trigger_matches"
                        )
                        or []
                    )

                    if trigger.get(
                        "trigger_chunk_id"
                    )
                    is not None
                }
            ]

            continue


        document_title = (
            link.get(
                "activation_document_title"
            )
        )


        activation = (
            activation_results.get(
                document_title
            )
            or {}
        )


        if not activation.get(
            "ok"
        ):

            link[
                "activation_status"
            ] = "activation-failed"

            link[
                "activation_mode"
            ] = (
                "semantic-source-activation"
            )

            link[
                "activation_chunk_ids"
            ] = []

            continue


        chunk_ranks = (
            activation.get(
                "chunk_ranks"
            )
            or {}
        )


        source_chunk_ids = {
            int(
                x
            )

            for x in (
                link.get(
                    "source_chunk_ids"
                )
                or []
            )
        }


        matches = sorted(
            source_chunk_ids
            & set(
                chunk_ranks
            ),
            key=lambda chunk_id: (
                chunk_ranks[
                    chunk_id
                ],
                chunk_id,
            )
        )


        link[
            "activation_mode"
        ] = (
            "semantic-source-activation"
        )

        link[
            "activation_chunk_ids"
        ] = matches

        link[
            "activation_ranks"
        ] = {
            str(
                chunk_id
            ):
            chunk_ranks[
                chunk_id
            ]

            for chunk_id in matches
        }


        if matches:

            link[
                "activation_status"
            ] = "active"

        else:

            link[
                "activation_status"
            ] = "inactive"


    # --------------------------------------------------------
    # Recompute document-parent coverage AFTER activation.
    #
    # This avoids inactive section edges suppressing an active
    # document relationship, and removes dependence on which
    # coarse exact chunk happened to discover the edge.
    # --------------------------------------------------------

    active_parent_edge_keys = {
        link.get(
            "parent_edge_key"
        )

        for link in links

        if (
            link.get(
                "activation_status"
            )
            == "active"

            and link.get(
                "relationship"
            )
            == "explicit-section-reference"

            and link.get(
                "parent_edge_key"
            )
        )
    }


    for link in links:

        if (
            link.get(
                "relationship"
            )
            == "explicit-reference"
        ):

            link[
                "covered_by_section_edge"
            ] = (
                link.get(
                    "edge_key"
                )
                in active_parent_edge_keys
            )


    return links


# ============================================================
# Deterministic Graph evidence expansion
# ============================================================

def expand_graph(
    links,
    primary_results,
    query,
    english_query,
    terms,
    include_synthetic,
    graph_limit,
):

    # query / english_query / terms are intentionally
    # retained in the interface for compatibility.
    #
    # Section evidence resolution itself does NOT depend on
    # user wording. It is grounded in:
    #
    #   graph edge
    #   + source provenance
    #   + target semantic units

    primary_chunk_ids = {
        int(item["chunk_id"])
        for item in primary_results
        if item.get("chunk_id")
        is not None
    }


    graph_results = {}

    expansion_failures = []


    for link in links:

        # ----------------------------------------------------
        # Query-relevance activation gate.
        # ----------------------------------------------------

        if (
            link.get(
                "activation_status"
            )
            != "active"
        ):

            if (
                link.get(
                    "activation_status"
                )
                == "activation-failed"
            ):

                link[
                    "evidence_status"
                ] = "activation-failed"

            else:

                link[
                    "evidence_status"
                ] = "inactive-source"

            continue


        # ----------------------------------------------------
        # Unresolved target:
        # preserve relationship only.
        # ----------------------------------------------------

        if (
            link.get(
                "target_document_id"
            )
            is None
        ):

            link[
                "evidence_status"
            ] = "unresolved-target"

            continue


        # ----------------------------------------------------
        # Document-level edge:
        #
        # We know the target document is relevant, but not
        # which target provision supplies the right evidence.
        #
        # Never perform broad document evidence selection
        # automatically in Graph-aware Retrieval v1.
        # ----------------------------------------------------

        if (
            link["relationship"]
            == "explicit-reference"
        ):

            if link.get(
                "covered_by_section_edge"
            ):

                link[
                    "evidence_status"
                ] = (
                    "covered-by-section-edge"
                )

            else:

                link[
                    "evidence_status"
                ] = (
                    "related-document-only"
                )

            continue


        # ----------------------------------------------------
        # Only precise section-level references may generate
        # graph-added legal evidence.
        # ----------------------------------------------------

        if (
            link["relationship"]
            != "explicit-section-reference"
        ):

            link[
                "evidence_status"
            ] = (
                "unsupported-relationship"
            )

            continue


        try:

            resolved = (
                resolve_section_evidence_edge(
                    link
                )
            )

        except Exception as exc:

            link[
                "evidence_status"
            ] = "resolver-failed"

            expansion_failures.append({
                "graph_path":
                    graph_path(link),

                "relationship":
                    link[
                        "relationship"
                    ],

                "error":
                    str(exc),
            })

            continue


        link[
            "resolver_status"
        ] = resolved.get(
            "status"
        )

        link[
            "resolver_mapping_count"
        ] = resolved.get(
            "mapping_count",
            0,
        )

        link[
            "resolver_fallback_count"
        ] = resolved.get(
            "fallback_count",
            0,
        )


        resolver_modes = []

        for mapping in (
            resolved.get(
                "mappings"
            )
            or []
        ):

            mode = mapping.get(
                "mode"
            )

            if (
                mode
                and mode
                not in resolver_modes
            ):

                resolver_modes.append(
                    mode
                )


        link[
            "resolver_modes"
        ] = resolver_modes


        selected = (
            resolved.get(
                "selected"
            )
            or []
        )


        link[
            "resolver_selected_chunk_ids"
        ] = [
            int(
                item[
                    "chunk_id"
                ]
            )
            for item in selected
        ]


        # ----------------------------------------------------
        # Fail safe:
        #
        # if even one source provenance mapping requires
        # fallback, do not partially publish evidence from
        # this edge.
        # ----------------------------------------------------

        if (
            resolved.get(
                "status"
            )
            != "resolved"
        ):

            link[
                "evidence_status"
            ] = (
                resolved.get(
                    "status"
                )
                or "needs-fallback"
            )

            continue


        if not selected:

            link[
                "evidence_status"
            ] = (
                "no-resolved-evidence"
            )

            continue


        # ----------------------------------------------------
        # Work out which selected chunks would actually add
        # new evidence.
        #
        # We apply graph_limit to the whole edge atomically:
        # never publish half of a one-to-many mapping.
        # ----------------------------------------------------

        new_children = []

        for child in selected:

            child_chunk_id = int(
                child[
                    "chunk_id"
                ]
            )

            if (
                child_chunk_id
                in primary_chunk_ids
            ):

                continue

            if (
                child_chunk_id
                in graph_results
            ):

                continue

            new_children.append(
                child
            )


        remaining_slots = (
            graph_limit
            - len(
                graph_results
            )
        )


        if (
            len(new_children)
            > remaining_slots
        ):

            link[
                "evidence_status"
            ] = "graph-limit"

            continue


        added_any = False
        already_primary_count = 0


        for child in selected:

            child_chunk_id = int(
                child[
                    "chunk_id"
                ]
            )


            # ------------------------------------------------
            # Preserve exact source->target mapping provenance
            # for this selected target chunk.
            # ------------------------------------------------

            mapping_provenance = []


            for mapping in (
                resolved.get(
                    "mappings"
                )
                or []
            ):

                selected_ids = {
                    int(
                        target[
                            "chunk_id"
                        ]
                    )

                    for target in (
                        mapping.get(
                            "selected"
                        )
                        or []
                    )
                }


                if (
                    child_chunk_id
                    not in selected_ids
                ):

                    continue


                mapping_provenance.append({
                    "source_chunk_id":
                        mapping.get(
                            "source_chunk_id"
                        ),

                    "source_definition":
                        mapping.get(
                            "source_definition"
                        ),

                    "resolution_mode":
                        mapping.get(
                            "mode"
                        ),
                })


            path_info = {
                "relationship":
                    link[
                        "relationship"
                    ],

                "graph_path":
                    graph_path(link),

                "trigger_rank":
                    link[
                        "trigger_rank"
                    ],

                "trigger_chunk_id":
                    link[
                        "trigger_chunk_id"
                    ],

                "source_match_mode":
                    link.get(
                        "source_match_mode"
                    ),

                "source_ref":
                    link.get(
                        "source_ref"
                    ),

                "target_ref":
                    link.get(
                        "target_ref"
                    ),

                "parent_edge_key":
                    link.get(
                        "parent_edge_key"
                    ),

                "edge_key":
                    link.get(
                        "edge_key"
                    ),

                "evidence_resolver":
                    (
                        "section-evidence-"
                        "resolver-v1"
                    ),

                "source_mappings":
                    mapping_provenance,
            }


            if (
                child_chunk_id
                in primary_chunk_ids
            ):

                already_primary_count += 1

                continue


            if (
                child_chunk_id
                not in graph_results
            ):

                child = dict(
                    child
                )

                child[
                    "retrieval_origin"
                ] = (
                    "graph-section-semantic"
                )

                child[
                    "graph_relationship_confidence"
                ] = "high"

                child[
                    "graph_evidence_selection"
                ] = "deterministic"

                child[
                    "graph_paths"
                ] = [
                    path_info
                ]

                graph_results[
                    child_chunk_id
                ] = child


            else:

                graph_results[
                    child_chunk_id
                ][
                    "graph_paths"
                ].append(
                    path_info
                )


            added_any = True


        if added_any:

            link[
                "evidence_status"
            ] = "added"

        elif (
            already_primary_count
            == len(selected)
        ):

            link[
                "evidence_status"
            ] = "already-primary"

        else:

            link[
                "evidence_status"
            ] = "resolved-no-new-evidence"


    output = list(
        graph_results.values()
    )


    for rank, item in enumerate(
        output,
        1,
    ):

        item[
            "graph_rank"
        ] = rank


    return (
        output,
        expansion_failures,
    )


# ============================================================
# Human-readable report
# ============================================================

def print_report(
    base_payload,
    links,
    graph_results,
    failures,
):

    primary = (
        base_payload.get(
            "results",
            []
        )
    )


    unresolved = [
        x for x in links
        if x.get(
            "evidence_status"
        ) == "unresolved-target"
    ]


    print("=" * 86)
    print(
        "GRAPH-AWARE RETRIEVAL V1"
    )
    print("=" * 86)


    print(
        "Primary hybrid results :",
        len(primary),
    )

    print(
        "Graph links discovered :",
        len(links),
    )

    print(
        "Graph links activated  :",
        sum(
            1
            for link in links
            if link.get(
                "activation_status"
            )
            == "active"
        ),
    )

    print(
        "Graph evidence added   :",
        len(graph_results),
    )

    print(
        "Unresolved graph links :",
        len(unresolved),
    )

    print(
        "Expansion failures     :",
        len(failures),
    )


    print()
    print("=" * 86)
    print("PRIMARY RESULTS")
    print("=" * 86)


    for item in primary:

        print()

        print(
            f"{item['rank']}. "
            f"{item.get('document', '')}"
        )

        if item.get(
            "section_number"
        ):

            print(
                "   section:",
                item[
                    "section_number"
                ],
                item.get(
                    "heading",
                    "",
                ),
            )

        print(
            "   chunk:",
            item["chunk_id"],
        )

        print(
            "   content:",
            item.get(
                "content",
                "",
            )[:300],
        )


    print()
    print("=" * 86)
    print("GRAPH LINKS")
    print("=" * 86)


    for link in links:

        print()

        print(
            f"trigger #{link['trigger_rank']} "
            f"chunk={link['trigger_chunk_id']}"
        )

        print(
            "   path:",
            graph_path(link),
        )

        print(
            "   relationship:",
            link[
                "relationship"
            ],
        )

        print(
            "   source match:",
            link.get(
                "source_match_mode",
                "unknown",
            ),
        )

        print(
            "   activation:",
            (
                f"{link.get('activation_status', 'unknown')} "
                f"via "
                f"{link.get('activation_mode', 'unknown')}"
            ),
        )

        if link.get(
            "activation_chunk_ids"
        ):

            print(
                "   activation chunks:",
                ", ".join(
                    str(x)
                    for x in link[
                        "activation_chunk_ids"
                    ]
                ),
            )

        if link.get(
            "activation_ranks"
        ):

            print(
                "   activation ranks:",
                ", ".join(
                    f"{chunk_id}=#{rank}"
                    for chunk_id, rank
                    in link[
                        "activation_ranks"
                    ].items()
                ),
            )

        print(
            "   status:",
            link.get(
                "evidence_status",
                "not-expanded",
            ),
        )

        if (
            link.get(
                "resolver_status"
            )
            is not None
        ):

            print(
                "   resolver:",
                (
                    f"status="
                    f"{link.get('resolver_status')} "
                    f"mappings="
                    f"{link.get('resolver_mapping_count')} "
                    f"fallbacks="
                    f"{link.get('resolver_fallback_count')}"
                ),
            )

            print(
                "   resolver modes:",
                (
                    ", ".join(
                        link.get(
                            "resolver_modes"
                        )
                        or []
                    )
                    or "(none)"
                ),
            )

            print(
                "   resolved chunks:",
                (
                    ", ".join(
                        str(x)
                        for x in (
                            link.get(
                                "resolver_selected_chunk_ids"
                            )
                            or []
                        )
                    )
                    or "(none)"
                ),
            )



    print()
    print("=" * 86)
    print("GRAPH-ADDED EVIDENCE")
    print("=" * 86)


    if not graph_results:

        print()
        print(
            "(no additional evidence)"
        )


    for item in graph_results:

        print()

        print(
            f"G{item['graph_rank']}. "
            f"{item.get('document', '')}"
        )

        if item.get(
            "section_number"
        ):

            print(
                "   section:",
                item[
                    "section_number"
                ],
                item.get(
                    "heading",
                    "",
                ),
            )

        print(
            "   chunk:",
            item["chunk_id"],
        )

        for path in item[
            "graph_paths"
        ]:

            print(
                "   via:",
                path[
                    "graph_path"
                ],
                f"({path['relationship']})",
            )

        print(
            "   content:",
            item.get(
                "content",
                "",
            )[:400],
        )


    if failures:

        print()
        print("=" * 86)
        print("EXPANSION FAILURES")
        print("=" * 86)

        for item in failures:

            print()
            print(
                item[
                    "graph_path"
                ]
            )

            print(
                "   error:",
                item[
                    "error"
                ][:500],
            )


# ============================================================
# Main
# ============================================================

def main():

    parser = argparse.ArgumentParser(
        description=(
            "Run Hybrid Search v3 and "
            "expand retrieved evidence "
            "through deterministic "
            "Knowledge Graph links."
        )
    )


    parser.add_argument(
        "--query",
        required=True,
    )

    parser.add_argument(
        "--english-query",
        required=True,
    )

    parser.add_argument(
        "--terms",
        default="",
        help=(
            "Comma-separated English "
            "technical terms."
        ),
    )

    parser.add_argument(
        "--refs",
        default="",
        help=(
            "Comma-separated exact "
            "references."
        ),
    )

    parser.add_argument(
        "--document-title",
        default="",
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=5,
        help=(
            "Primary Hybrid Search v3 "
            "result limit."
        ),
    )

    parser.add_argument(
        "--graph-limit",
        type=int,
        default=8,
        help=(
            "Maximum number of unique "
            "graph-added evidence chunks."
        ),
    )


    parser.add_argument(
        "--activation-limit",
        type=int,
        default=10,
        help=(
            "Maximum semantic source results "
            "used to activate coarse graph edges."
        ),
    )

    parser.add_argument(
        "--include-synthetic",
        action="store_true",
    )

    parser.add_argument(
        "--json-output",
        action="store_true",
    )


    args = parser.parse_args()


    base = run_hybrid(
        query=args.query,
        english_query=(
            args.english_query
        ),
        terms=args.terms,
        refs=args.refs,
        document_title=(
            args.document_title
        ),
        limit=args.limit,
        include_synthetic=(
            args.include_synthetic
        ),
        strict=True,
    )


    base_payload = (
        base["payload"]
    )

    primary_results = (
        base_payload.get(
            "results",
            []
        )
    )


    links = load_graph_links(
        primary_results
    )


    links = activate_graph_links(
        links=links,
        primary_results=(
            primary_results
        ),
        query=args.query,
        english_query=(
            args.english_query
        ),
        terms=args.terms,
        include_synthetic=(
            args.include_synthetic
        ),
        activation_limit=(
            args.activation_limit
        ),
    )


    (
        graph_results,
        failures,
    ) = expand_graph(
        links=links,
        primary_results=(
            primary_results
        ),
        query=args.query,
        english_query=(
            args.english_query
        ),
        terms=args.terms,
        include_synthetic=(
            args.include_synthetic
        ),
        graph_limit=(
            args.graph_limit
        ),
    )


    payload = {
        "query":
            args.query,

        "english_query":
            args.english_query,

        "technical_terms":
            base_payload.get(
                "technical_terms",
                [],
            ),

        "references":
            base_payload.get(
                "references",
                [],
            ),

        "retrieval":
            {
                "primary_engine":
                    "hybrid-search-v3",

                "graph_engine":
                    "graph-search-v1",

                "graph_hops":
                    1,

                "primary_limit":
                    args.limit,

                "graph_limit":
                    args.graph_limit,

                "activation_limit":
                    args.activation_limit,
            },

        "primary_results":
            primary_results,

        "graph_links":
            links,

        "graph_results":
            graph_results,

        "graph_expansion_failures":
            failures,
    }


    if args.json_output:

        print(
            json.dumps(
                payload,
                ensure_ascii=False,
            )
        )

        return


    print_report(
        base_payload=base_payload,
        links=links,
        graph_results=(
            graph_results
        ),
        failures=failures,
    )


if __name__ == "__main__":
    main()
