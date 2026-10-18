#!/usr/bin/env python3

import argparse
import json
import re
import subprocess
import sys


DB_CONTAINER = (
    "ai-knowledge-db-jiyckdrlappwgimwebnzxwmr"
)


# ============================================================
# PostgreSQL
# ============================================================

def psql(sql):

    p = subprocess.run(
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
            "-At",
            "-v",
            "ON_ERROR_STOP=1",
        ],
        input=sql,
        text=True,
        capture_output=True,
    )

    if p.returncode != 0:

        if p.stdout.strip():
            print(
                p.stdout,
                file=sys.stderr,
            )

        if p.stderr.strip():
            print(
                p.stderr,
                file=sys.stderr,
            )

        raise RuntimeError(
            "Database query failed."
        )

    return [
        line
        for line in p.stdout.splitlines()
        if line.strip()
    ]


# ============================================================
# Term normalization
# ============================================================

def normalize_term(value):

    return re.sub(
        r"[^a-z0-9]",
        "",
        (value or "").lower(),
    )


def split_definition_names(value):

    if not value:
        return []

    return [
        x.strip()
        for x in value.split(",")
        if x.strip()
    ]


# ============================================================
# Citation context
# ============================================================

def strip_source_document_prefix(
    content,
):

    text = (
        content
        or ""
    ).strip()

    return re.sub(
        r'^Cap\.\s*'
        r'[0-9]+[A-Z]?\s+'
        r'[^.\n]{1,220}\.\s*',
        '',
        text,
        count=1,
        flags=re.I,
    )


def citation_window(
    content,
    target_section_ref,
):

    if (
        not content
        or not target_section_ref
    ):

        return ""


    text = (
        strip_source_document_prefix(
            content
        )
    )


    escaped = re.escape(
        target_section_ref
    )


    # Do not use \b after references ending in ")":
    #
    # section 2(1)
    #
    # ")" and the following whitespace are both non-word
    # characters, so a trailing \b would fail.
    pattern = (
        rf"\bsections?\s+"
        rf"{escaped}"
        rf"(?![0-9A-Za-z(])"
    )


    matches = list(
        re.finditer(
            pattern,
            text,
            re.I,
        )
    )


    if not matches:

        return ""


    windows = []


    for match in matches:

        start = max(
            0,
            match.start() - 240,
        )

        window = text[
            start:match.start()
        ].strip()

        if window:
            windows.append(
                window
            )


    return " ".join(
        windows
    )


# ============================================================
# Candidate matching
# ============================================================

def citation_term_matches(
    source,
    target_candidates,
    target_section_ref,
):

    window = citation_window(
        source.get(
            "content",
            ""
        ),
        target_section_ref,
    )


    if not window:

        return []


    normalized_window = (
        normalize_term(
            window
        )
    )


    raw_matches = []


    for candidate in target_candidates:

        for alias in split_definition_names(
            candidate.get(
                "definition_name"
            )
        ):

            key = normalize_term(
                alias
            )

            if (
                len(key) >= 3
                and key
                in normalized_window
            ):

                raw_matches.append({
                    "candidate":
                        candidate,

                    "alias":
                        alias,

                    "key":
                        key,
                })


    # --------------------------------------------------------
    # Remove nested weaker matches.
    #
    # Example:
    #
    # source citation phrase:
    #   "building works"
    #
    # possible definitions:
    #   Building
    #   BuildingWorks
    #
    # Keep only BuildingWorks.
    # --------------------------------------------------------

    filtered = []


    for item in raw_matches:

        key = item[
            "key"
        ]

        nested = False


        for other in raw_matches:

            other_key = (
                other[
                    "key"
                ]
            )

            if (
                key != other_key
                and len(key)
                < len(other_key)
                and key
                in other_key
            ):

                nested = True
                break


        if not nested:

            filtered.append(
                item
            )


    unique = {}


    for item in filtered:

        candidate = (
            item[
                "candidate"
            ]
        )

        unique[
            int(
                candidate[
                    "chunk_id"
                ]
            )
        ] = candidate


    return list(
        unique.values()
    )


def definition_identity_matches(
    source,
    target_candidates,
):

    source_names = {
        normalize_term(name)

        for name in split_definition_names(
            source.get(
                "definition_name"
            )
        )

        if normalize_term(
            name
        )
    }


    if not source_names:

        return []


    matches = []


    for candidate in target_candidates:

        candidate_names = {
            normalize_term(name)

            for name in split_definition_names(
                candidate.get(
                    "definition_name"
                )
            )

            if normalize_term(
                name
            )
        }


        if (
            source_names
            & candidate_names
        ):

            matches.append(
                candidate
            )


    return matches


# ============================================================
# Database loaders
# ============================================================

def load_edge_by_key(
    edge_key,
):

    safe_key = (
        edge_key.replace(
            "'",
            "''",
        )
    )


    rows = psql(f"""
SELECT json_build_object(

    'edge_id',
        cr.id,

    'edge_key',
        cr.metadata->>'edge_key',

    'source_ref',
        cr.metadata->>'source_ref',

    'target_ref',
        cr.metadata->>'target_ref',

    'target_section_ref',
        cr.metadata->>'target_section_ref',

    'target_document_id',
        cr.target_document_id,

    'target_section_id',
        cr.target_section_id,

    'source_chunk_ids',
        cr.metadata->'source_chunk_ids'

)::text

FROM cross_references cr

WHERE
    cr.relationship =
        'explicit-section-reference'

    AND cr.metadata->>'extractor' =
        'explicit-section-reference-v1'

    AND cr.metadata->>'edge_key' =
        '{safe_key}';
""")


    if not rows:

        return None


    if len(rows) != 1:

        raise RuntimeError(
            "Edge key is not unique."
        )


    return json.loads(
        rows[0]
    )


def load_source_chunk(
    chunk_id,
):

    chunk_id = int(
        chunk_id
    )


    rows = psql(f"""
SELECT json_build_object(

    'chunk_id',
        c.id,

    'section_id',
        c.section_id,

    'semantic_type',
        c.metadata->>'semantic_type',

    'definition_name',
        c.metadata->>'definition_name',

    'content',
        c.content

)::text

FROM chunks c

WHERE
    c.id =
        {chunk_id};
""")


    if not rows:

        return None


    return json.loads(
        rows[0]
    )


def load_target_candidates(
    target_section_id,
):

    target_section_id = int(
        target_section_id
    )


    rows = psql(f"""
SELECT json_build_object(

    'chunk_id',
        c.id,

    'document',
        d.title,

    'source_file_id',
        d.source_file_id,

    'source_url',
        d.source_url,

    'section_id',
        s.id,

    'section_number',
        s.section_number,

    'heading',
        s.heading,

    'semantic_type',
        c.metadata->>'semantic_type',

    'definition_name',
        c.metadata->>'definition_name',

    'content',
        c.content

)::text

FROM chunks c

JOIN sections s
    ON s.id =
        c.section_id

JOIN documents d
    ON d.id =
        c.document_id

WHERE
    c.section_id =
        {target_section_id}

    AND c.metadata->>'retrieval_role'
        = 'legal-semantic'

    AND COALESCE(
        c.metadata->>'operative',
        'true'
    ) = 'true'

ORDER BY
    c.id;
""")


    return [
        json.loads(
            row
        )
        for row in rows
    ]


# ============================================================
# One source provenance mapping
# ============================================================

def resolve_source_mapping(
    source,
    target_candidates,
    target_section_ref,
):

    # --------------------------------------------------------
    # Rule 1:
    # Target provision has only one semantic unit.
    # --------------------------------------------------------

    if len(
        target_candidates
    ) == 1:

        return {
            "mode":
                "single-target",

            "selected":
                [
                    target_candidates[0]
                ],
        }


    # --------------------------------------------------------
    # Rule 2:
    # Resolve the term actually surrounding the statutory
    # citation.
    # --------------------------------------------------------

    selected = (
        citation_term_matches(
            source,
            target_candidates,
            target_section_ref,
        )
    )


    if selected:

        return {
            "mode":
                "citation-term",

            "selected":
                selected,
        }


    # --------------------------------------------------------
    # Rule 3:
    # Exact definition identity.
    # --------------------------------------------------------

    selected = (
        definition_identity_matches(
            source,
            target_candidates,
        )
    )


    if selected:

        return {
            "mode":
                "definition-identity",

            "selected":
                selected,
        }


    # --------------------------------------------------------
    # Rule 4:
    # Fail safe.
    #
    # Do NOT silently use cosine similarity in production.
    # --------------------------------------------------------

    return {
        "mode":
            "needs-fallback",

        "selected":
            [],
    }


# ============================================================
# Resolve complete graph edge
# ============================================================

def resolve_edge(
    edge,
):

    if not edge:

        return {
            "status":
                "edge-not-found",

            "mappings":
                [],

            "selected":
                [],
        }


    target_section_id = (
        edge.get(
            "target_section_id"
        )
    )


    if target_section_id is None:

        return {
            "status":
                "unresolved-target",

            "edge":
                edge,

            "mappings":
                [],

            "selected":
                [],
        }


    target_candidates = (
        load_target_candidates(
            target_section_id
        )
    )


    if not target_candidates:

        return {
            "status":
                "no-target-semantic-candidates",

            "edge":
                edge,

            "mappings":
                [],

            "selected":
                [],
        }


    mappings = []

    selected_by_chunk = {}

    fallback_count = 0


    for source_chunk_id in (
        edge.get(
            "source_chunk_ids"
        )
        or []
    ):

        source = load_source_chunk(
            source_chunk_id
        )


        if source is None:

            fallback_count += 1

            mappings.append({
                "source_chunk_id":
                    int(
                        source_chunk_id
                    ),

                "source_definition":
                    None,

                "mode":
                    "missing-source-chunk",

                "selected":
                    [],
            })

            continue


        resolved = (
            resolve_source_mapping(
                source=source,
                target_candidates=(
                    target_candidates
                ),
                target_section_ref=(
                    edge.get(
                        "target_section_ref"
                    )
                ),
            )
        )


        if (
            resolved[
                "mode"
            ]
            == "needs-fallback"
        ):

            fallback_count += 1


        mapping_targets = []


        for candidate in (
            resolved[
                "selected"
            ]
        ):

            chunk_id = int(
                candidate[
                    "chunk_id"
                ]
            )

            selected_by_chunk[
                chunk_id
            ] = candidate

            mapping_targets.append(
                candidate
            )


        mappings.append({
            "source_chunk_id":
                int(
                    source_chunk_id
                ),

            "source_definition":
                source.get(
                    "definition_name"
                ),

            "mode":
                resolved[
                    "mode"
                ],

            "selected":
                mapping_targets,
        })


    status = (
        "resolved"
        if fallback_count == 0
        else "needs-fallback"
    )


    return {
        "status":
            status,

        "edge":
            edge,

        "target_candidate_count":
            len(
                target_candidates
            ),

        "mapping_count":
            len(
                mappings
            ),

        "fallback_count":
            fallback_count,

        "mappings":
            mappings,

        "selected":
            list(
                selected_by_chunk.values()
            ),
    }


# ============================================================
# CLI report
# ============================================================

def print_report(
    result,
):

    print(
        "=" * 90
    )

    print(
        "SECTION EVIDENCE RESOLVER V1"
    )

    print(
        "=" * 90
    )


    edge = (
        result.get(
            "edge"
        )
        or {}
    )


    print(
        "status:",
        result.get(
            "status"
        ),
    )

    print(
        "edge:",
        edge.get(
            "source_ref"
        ),
        "->",
        edge.get(
            "target_ref"
        ),
    )

    print(
        "target candidates:",
        result.get(
            "target_candidate_count",
            0,
        ),
    )

    print(
        "source mappings:",
        result.get(
            "mapping_count",
            0,
        ),
    )

    print(
        "fallbacks:",
        result.get(
            "fallback_count",
            0,
        ),
    )


    for mapping in (
        result.get(
            "mappings"
        )
        or []
    ):

        print()

        print(
            "source chunk:",
            mapping[
                "source_chunk_id"
            ],
        )

        print(
            "source definition:",
            mapping.get(
                "source_definition"
            )
            or "(none)",
        )

        print(
            "mode:",
            mapping[
                "mode"
            ],
        )


        if not mapping[
            "selected"
        ]:

            print(
                "selected:",
                "(none)"
            )

        else:

            for target in (
                mapping[
                    "selected"
                ]
            ):

                print(
                    "selected:",
                    (
                        f"chunk="
                        f"{target['chunk_id']} "
                        f"type="
                        f"{target.get('semantic_type')} "
                        f"definition="
                        f"{target.get('definition_name')}"
                    ),
                )


    print()

    print(
        "deduplicated target chunks:",
        ", ".join(
            str(
                x[
                    "chunk_id"
                ]
            )
            for x in (
                result.get(
                    "selected"
                )
                or []
            )
        )
        or "(none)",
    )


def main():

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--edge-key",
        required=True,
    )

    parser.add_argument(
        "--json-output",
        action="store_true",
    )

    args = parser.parse_args()


    edge = load_edge_by_key(
        args.edge_key
    )


    result = resolve_edge(
        edge
    )


    if args.json_output:

        print(
            json.dumps(
                result,
                ensure_ascii=False,
            )
        )

    else:

        print_report(
            result
        )


    if (
        result.get(
            "status"
        )
        != "resolved"
    ):

        raise SystemExit(2)


if __name__ == "__main__":
    main()
