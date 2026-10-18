#!/usr/bin/env python3

import argparse
import json
import re
import subprocess
from collections import Counter
from pathlib import Path

DB_CONTAINER = "ai-knowledge-db-jiyckdrlappwgimwebnzxwmr"

EXTRACTOR = "explicit-reference-v1"
RELATIONSHIP = "explicit-reference"
SCHEMA_VERSION = 1


# ============================================================
# Reference patterns
# ============================================================

REF_RE = re.compile(
    r'''
    \bCap\.?\s*
    (?P<cap>[0-9]+[A-Z]?)
    (?P<subleg>
        \s*,?\s*
        sub\.?\s*leg\.?
        (?:
            \s*,?\s*
            (?P<subleg_code>[A-Z][A-Z0-9]*)
        )?
    )?
    ''',
    re.I | re.X,
)

SOURCE_CAP_RE = re.compile(
    r'hkel:CAP_([0-9A-Z]+):',
    re.I,
)


# ============================================================
# PostgreSQL helpers
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
        print(p.stderr)
        raise SystemExit(
            "Database operation failed."
        )

    return [
        line
        for line in p.stdout.splitlines()
        if line.strip()
    ]


def sql_quote(value):
    if value is None:
        return "NULL"

    return "'" + str(value).replace(
        "'",
        "''"
    ) + "'"


# ============================================================
# Current production documents
# ============================================================

def load_known_caps():

    known = {}

    rows = psql("""
SELECT json_build_object(
    'id', id,
    'title', title,
    'source_file_id', source_file_id
)::text
FROM documents
WHERE source_file_id LIKE 'hkel:CAP_%';
""")

    for line in rows:

        obj = json.loads(line)

        m = SOURCE_CAP_RE.search(
            obj["source_file_id"]
        )

        if not m:
            continue

        cap = m.group(1).upper()

        known[cap] = {
            "document_id": obj["id"],
            "title": obj["title"],
        }

    return known


# ============================================================
# Atomic legal-semantic corpus
# ============================================================

def load_semantic_chunks():

    rows = psql("""
SELECT json_build_object(
    'document_id', d.id,
    'title', d.title,
    'source_file_id', d.source_file_id,
    'section_id', s.id,
    'section_number', s.section_number,
    'chunk_id', c.id,
    'semantic_type',
        c.metadata->>'semantic_type',
    'definition_name',
        c.metadata->>'definition_name',
    'content', c.content
)::text
FROM chunks c
JOIN documents d
    ON d.id = c.document_id
LEFT JOIN sections s
    ON s.id = c.section_id
WHERE
    d.source_file_id LIKE 'hkel:CAP_%'
    AND c.metadata->>'retrieval_role'
        = 'legal-semantic'
    AND COALESCE(
        c.metadata->>'operative',
        'true'
    ) = 'true'
ORDER BY
    d.id,
    s.sort_order,
    c.id;
""")

    return [
        json.loads(x)
        for x in rows
    ]


# ============================================================
# Orphan semantic source recovery
# ============================================================

def normalize_match_text(value):

    return re.sub(
        r'\s+',
        ' ',
        value or '',
    ).strip()


def load_exact_chunks():

    rows = psql("""
SELECT json_build_object(
    'document_id', d.id,
    'section_id', s.id,
    'section_number', s.section_number,
    'chunk_id', c.id,
    'content', c.content
)::text
FROM chunks c
JOIN documents d
    ON d.id = c.document_id
JOIN sections s
    ON s.id = c.section_id
WHERE
    d.source_file_id LIKE 'hkel:CAP_%'
    AND c.metadata->>'retrieval_role'
        = 'legal-exact'
ORDER BY
    d.id,
    s.sort_order,
    c.id;
""")

    by_document = {}

    for line in rows:

        obj = json.loads(line)

        obj["normalized_content"] = (
            normalize_match_text(
                obj["content"]
            )
        )

        by_document.setdefault(
            obj["document_id"],
            [],
        ).append(obj)

    return by_document


def recover_orphan_section(
    obj,
    exact_by_document,
):

    """
    Recover a section mapping for a legal-semantic
    chunk that has no section_id.

    Recovery is deliberately conservative:

    1. Remove the generated "Definition:" prefix.
    2. Look only inside legal-exact chunks from the
       same document.
    3. Require exactly one unique matching section.
    4. Abort if a Cap. reference exists but the
       source cannot be mapped unambiguously.
    """

    content = obj["content"] or ""

    if not REF_RE.search(content):
        return None


    body = content

    if "Definition:" in body:
        body = body.split(
            "Definition:",
            1,
        )[1]


    body = normalize_match_text(body)

    if len(body) < 40:

        raise SystemExit(
            "Orphan semantic chunk contains a "
            "statutory reference but has too "
            "little text for safe recovery: "
            f"chunk_id={obj['chunk_id']}"
        )


    matches = {}

    for exact in exact_by_document.get(
        obj["document_id"],
        [],
    ):

        if body not in exact[
            "normalized_content"
        ]:
            continue

        key = (
            exact["section_id"],
            exact["section_number"],
        )

        matches[key] = exact


    if len(matches) != 1:

        candidates = [
            f"{section_id}:{section_number}"
            for (
                section_id,
                section_number,
            ) in matches
        ]

        raise SystemExit(
            "Could not uniquely recover orphan "
            "semantic source mapping: "
            f"chunk_id={obj['chunk_id']} "
            f"matches={len(matches)} "
            f"candidates={candidates}"
        )


    (
        section_id,
        section_number,
    ) = next(iter(matches))


    return {
        "section_id": section_id,
        "section_number": section_number,
        "mapping": "recovered-from-exact",
    }


# ============================================================
# Deterministic extraction
# ============================================================

def build_edges():

    known_caps = load_known_caps()
    chunks = load_semantic_chunks()
    exact_by_document = load_exact_chunks()

    edges = {}

    for obj in chunks:

        source_match = SOURCE_CAP_RE.search(
            obj["source_file_id"]
        )

        if not source_match:
            continue

        source_cap = (
            source_match
            .group(1)
            .upper()
        )

        content = obj["content"] or ""

        source_section_id = (
            obj["section_id"]
        )

        source_section = (
            obj["section_number"]
            or ""
        )

        source_mapping = (
            "direct-section"
        )

        if (
            not source_section
            or source_section_id is None
        ):

            recovered = (
                recover_orphan_section(
                    obj,
                    exact_by_document,
                )
            )

            if recovered is None:
                continue

            source_section_id = (
                recovered["section_id"]
            )

            source_section = (
                recovered[
                    "section_number"
                ]
            )

            source_mapping = (
                recovered["mapping"]
            )

        for match in REF_RE.finditer(
            content
        ):

            target_cap = (
                match.group("cap")
                .upper()
            )

            has_subleg = bool(
                match.group("subleg")
            )

            subleg_code = (
                match.group("subleg_code")
                or ""
            ).upper()

            if has_subleg:

                if subleg_code:
                    target_ref = (
                        f"CAP_{target_cap}"
                        f"_SUBLEG_{subleg_code}"
                    )
                else:
                    target_ref = (
                        f"CAP_{target_cap}"
                        "_SUBLEG_UNSPECIFIED"
                    )

                target_kind = (
                    "subsidiary-legislation"
                )

                resolution_status = (
                    "unresolved"
                )

                target_document_id = None
                target_title = None

            else:

                target_ref = (
                    f"CAP_{target_cap}"
                )

                target_kind = (
                    "principal-ordinance"
                )

                if target_cap in known_caps:

                    resolution_status = (
                        "resolved"
                    )

                    target_document_id = (
                        known_caps[target_cap]
                        ["document_id"]
                    )

                    target_title = (
                        known_caps[target_cap]
                        ["title"]
                    )

                else:

                    resolution_status = (
                        "unresolved"
                    )

                    target_document_id = None
                    target_title = None


            # Genuine principal-Ordinance
            # self references are not graph edges.
            #
            # Same-Cap subsidiary legislation is
            # NOT a self reference.
            if (
                not has_subleg
                and target_cap
                == source_cap
            ):
                continue


            context = content[
                max(
                    0,
                    match.start() - 70
                ):
                min(
                    len(content),
                    match.end() + 90
                )
            ]

            historical = bool(
                re.search(
                    r'\b(?:18|19|20)'
                    r'\d{2}\s*Ed\.',
                    context,
                    re.I,
                )
            )


            edge_key = (
                f"{RELATIONSHIP}|"
                f"CAP_{source_cap}|"
                f"{source_section}|"
                f"{target_ref}"
            )

            if edge_key not in edges:

                edges[edge_key] = {
                    "edge_key": edge_key,

                    "source_document_id":
                        obj["document_id"],

                    "source_section_id":
                        source_section_id,

                    "source_cap":
                        source_cap,

                    "source_section":
                        source_section,

                    "target_ref":
                        target_ref,

                    "target_cap":
                        target_cap,

                    "target_document_id":
                        target_document_id,

                    "target_kind":
                        target_kind,

                    "target_title":
                        target_title,

                    "resolution_status":
                        resolution_status,

                    "historical_edition_context":
                        historical,

                    "source_chunk_ids": set(),

                    "semantic_types": set(),

                    "definition_names": set(),

                    "source_mappings": set(),

                    "recovered_source_chunk_ids":
                        set(),

                    "mention_count": 0,
                }


            edge = edges[edge_key]

            edge["mention_count"] += 1

            edge["source_chunk_ids"].add(
                obj["chunk_id"]
            )

            edge["source_mappings"].add(
                source_mapping
            )

            if (
                source_mapping
                == "recovered-from-exact"
            ):

                edge[
                    "recovered_source_chunk_ids"
                ].add(
                    obj["chunk_id"]
                )

            if obj["semantic_type"]:

                edge[
                    "semantic_types"
                ].add(
                    obj["semantic_type"]
                )

            if obj["definition_name"]:

                edge[
                    "definition_names"
                ].add(
                    obj["definition_name"]
                )

            if historical:

                edge[
                    "historical_edition_context"
                ] = True


    results = []

    for edge in edges.values():

        edge["source_chunk_ids"] = (
            sorted(
                edge["source_chunk_ids"]
            )
        )

        edge["semantic_types"] = (
            sorted(
                edge["semantic_types"]
            )
        )

        edge["definition_names"] = (
            sorted(
                edge["definition_names"]
            )
        )

        edge["source_mappings"] = (
            sorted(
                edge["source_mappings"]
            )
        )

        edge[
            "recovered_source_chunk_ids"
        ] = sorted(
            edge[
                "recovered_source_chunk_ids"
            ]
        )

        results.append(edge)


    results.sort(
        key=lambda x: (
            int(x["source_cap"])
            if x["source_cap"].isdigit()
            else 999999,

            x["source_section"],

            x["target_ref"],
        )
    )

    return results


# ============================================================
# Existing managed edges
# ============================================================

def load_existing():

    rows = psql(f"""
SELECT json_build_object(
    'id', id,
    'edge_key',
        metadata->>'edge_key',
    'source_document_id',
        source_document_id,
    'source_section_id',
        source_section_id,
    'target_document_id',
        target_document_id,
    'target_section_id',
        target_section_id,
    'relationship',
        relationship,
    'metadata',
        metadata
)::text
FROM cross_references
WHERE
    relationship =
        '{RELATIONSHIP}'
    AND metadata->>'extractor' =
        '{EXTRACTOR}';
""")

    existing = {}

    for line in rows:

        obj = json.loads(line)

        edge_key = obj.get(
            "edge_key"
        )

        if not edge_key:
            raise SystemExit(
                "Managed edge without edge_key "
                f"detected: id={obj['id']}"
            )

        if edge_key in existing:
            raise SystemExit(
                "Duplicate managed edge_key "
                f"detected: {edge_key}"
            )

        existing[edge_key] = obj

    return existing


# ============================================================
# Metadata representation
# ============================================================

def metadata_for(edge):

    return {
        "schema_version":
            SCHEMA_VERSION,

        "edge_key":
            edge["edge_key"],

        "source_ref":
            (
                f"CAP_{edge['source_cap']}:"
                f"{edge['source_section']}"
            ),

        "target_ref":
            edge["target_ref"],

        "target_kind":
            edge["target_kind"],

        "resolution_status":
            edge["resolution_status"],

        "regenerable":
            True,

        "extractor":
            EXTRACTOR,

        "historical_edition_context":
            edge[
                "historical_edition_context"
            ],

        "source_chunk_ids":
            edge["source_chunk_ids"],

        "source_mappings":
            edge["source_mappings"],

        "recovered_source_chunk_ids":
            edge[
                "recovered_source_chunk_ids"
            ],

        "semantic_types":
            edge["semantic_types"],

        "definition_names":
            edge["definition_names"],

        "mention_count":
            edge["mention_count"],
    }


# ============================================================
# Change planning
# ============================================================

def plan_changes(edges, existing):

    desired = {
        x["edge_key"]: x
        for x in edges
    }

    desired_keys = set(desired)
    existing_keys = set(existing)

    inserts = sorted(
        desired_keys
        - existing_keys
    )

    deletes = sorted(
        existing_keys
        - desired_keys
    )

    updates = sorted(
        desired_keys
        & existing_keys
    )

    return (
        desired,
        inserts,
        updates,
        deletes,
    )


# ============================================================
# Transactional synchronization
# ============================================================

def sync_database(
    desired,
    deletes,
):

    values = []

    for edge in desired.values():

        metadata = json.dumps(
            metadata_for(edge),
            ensure_ascii=False,
            separators=(",", ":"),
        )

        description = (
            "Explicit statutory reference "
            f"from CAP_{edge['source_cap']} "
            f"{edge['source_section']} "
            f"to {edge['target_ref']}."
        )

        values.append(
            "("
            + ", ".join([
                sql_quote(
                    edge["edge_key"]
                ),
                str(
                    edge[
                        "source_document_id"
                    ]
                ),
                str(
                    edge[
                        "source_section_id"
                    ]
                ),
                (
                    str(
                        edge[
                            "target_document_id"
                        ]
                    )
                    if edge[
                        "target_document_id"
                    ] is not None
                    else "NULL"
                ),
                sql_quote(
                    description
                ),
                sql_quote(
                    metadata
                )
                + "::jsonb",
            ])
            + ")"
        )


    if not values:
        raise SystemExit(
            "Refusing sync: desired edge "
            "set is empty."
        )


    sql = f"""
BEGIN;

SELECT pg_advisory_xact_lock(
    hashtext(
        'explicit-reference-v1-sync'
    )
);

CREATE TEMP TABLE
desired_explicit_reference_v1 (
    edge_key TEXT PRIMARY KEY,
    source_document_id BIGINT NOT NULL,
    source_section_id BIGINT NOT NULL,
    target_document_id BIGINT,
    description TEXT,
    metadata JSONB NOT NULL
) ON COMMIT DROP;


INSERT INTO
desired_explicit_reference_v1
VALUES
{",\n".join(values)};


-- Remove only stale relationships owned by
-- this deterministic extractor.
DELETE FROM cross_references c
WHERE
    c.relationship =
        '{RELATIONSHIP}'
    AND c.metadata->>'extractor' =
        '{EXTRACTOR}'
    AND NOT EXISTS (
        SELECT 1
        FROM
            desired_explicit_reference_v1 d
        WHERE
            d.edge_key =
                c.metadata->>'edge_key'
    );


-- Refresh current database pointers and
-- generated metadata.
UPDATE cross_references c
SET
    source_document_id =
        d.source_document_id,

    source_section_id =
        d.source_section_id,

    target_document_id =
        d.target_document_id,

    target_section_id =
        NULL,

    description =
        d.description,

    metadata =
        d.metadata

FROM
    desired_explicit_reference_v1 d

WHERE
    c.relationship =
        '{RELATIONSHIP}'
    AND c.metadata->>'extractor' =
        '{EXTRACTOR}'
    AND c.metadata->>'edge_key' =
        d.edge_key;


-- Insert newly discovered relationships.
INSERT INTO cross_references (
    source_document_id,
    source_section_id,
    target_document_id,
    target_section_id,
    relationship,
    description,
    metadata
)
SELECT
    d.source_document_id,
    d.source_section_id,
    d.target_document_id,
    NULL,
    '{RELATIONSHIP}',
    d.description,
    d.metadata
FROM
    desired_explicit_reference_v1 d

WHERE NOT EXISTS (
    SELECT 1
    FROM cross_references c
    WHERE
        c.relationship =
            '{RELATIONSHIP}'
        AND c.metadata->>'extractor' =
            '{EXTRACTOR}'
        AND c.metadata->>'edge_key' =
            d.edge_key
);


-- Safety validation.
DO $$
DECLARE
    v_expected BIGINT;
    v_actual BIGINT;
    v_bad BIGINT;
BEGIN

    SELECT COUNT(*)
    INTO v_expected
    FROM desired_explicit_reference_v1;

    SELECT COUNT(*)
    INTO v_actual
    FROM cross_references
    WHERE
        relationship =
            '{RELATIONSHIP}'
        AND metadata->>'extractor' =
            '{EXTRACTOR}';

    IF v_expected <> v_actual THEN
        RAISE EXCEPTION
            'explicit-reference sync count mismatch: expected %, actual %',
            v_expected,
            v_actual;
    END IF;


    SELECT COUNT(*)
    INTO v_bad
    FROM cross_references
    WHERE
        relationship =
            '{RELATIONSHIP}'
        AND metadata->>'extractor' =
            '{EXTRACTOR}'
        AND (
            metadata->>'edge_key'
                IS NULL

            OR COALESCE(
                metadata->>'regenerable',
                'false'
            ) <> 'true'
        );

    IF v_bad <> 0 THEN
        RAISE EXCEPTION
            'invalid managed explicit-reference rows: %',
            v_bad;
    END IF;

END
$$;

COMMIT;
"""

    psql(sql)


# ============================================================
# Reporting
# ============================================================

def show_report(
    edges,
    existing,
    inserts,
    updates,
    deletes,
    mode,
):

    kinds = Counter(
        x["target_kind"]
        for x in edges
    )

    resolution = Counter(
        (
            x["target_kind"],
            x["resolution_status"],
        )
        for x in edges
    )

    historical = sum(
        1
        for x in edges
        if x[
            "historical_edition_context"
        ]
    )

    recovered_chunks = {
        chunk_id
        for edge in edges
        for chunk_id in edge[
            "recovered_source_chunk_ids"
        ]
    }


    print("=" * 82)
    print(
        "EXPLICIT REFERENCE SYNCHRONIZER V1"
    )
    print("=" * 82)

    print(
        f"Mode                         : "
        f"{mode}"
    )

    print(
        f"Desired graph edges          : "
        f"{len(edges)}"
    )

    print(
        f"Existing managed edges       : "
        f"{len(existing)}"
    )

    print(
        f"Principal Ordinance refs     : "
        f"{kinds['principal-ordinance']}"
    )

    print(
        f"Resolved principal refs      : "
        f"{resolution[(
            'principal-ordinance',
            'resolved'
        )]}"
    )

    print(
        f"Unresolved principal refs    : "
        f"{resolution[(
            'principal-ordinance',
            'unresolved'
        )]}"
    )

    print(
        f"Subsidiary legislation refs  : "
        f"{kinds['subsidiary-legislation']}"
    )

    print(
        f"Historical-edition contexts  : "
        f"{historical}"
    )

    print(
        f"Recovered orphan chunks      : "
        f"{len(recovered_chunks)}"
    )

    print()
    print(
        f"New edges                    : "
        f"{len(inserts)}"
    )

    print(
        f"Existing edges to refresh    : "
        f"{len(updates)}"
    )

    print(
        f"Stale edges to remove        : "
        f"{len(deletes)}"
    )


    print()
    print("=" * 82)
    print("CANARY RELATIONSHIPS")
    print("=" * 82)

    wanted = {
        (
            "636",
            "3(3)",
            "CAP_502",
        ),
        (
            "636",
            "3(3)",
            "CAP_572",
        ),
        (
            "572",
            "3(1)",
            "CAP_123_SUBLEG_A",
        ),
        (
            "121",
            "2(1)",
            "CAP_123",
        ),
        (
            "121",
            "2(1)",
            "CAP_123_SUBLEG_F",
        ),
    }

    for edge in edges:

        key = (
            edge["source_cap"],
            edge["source_section"],
            edge["target_ref"],
        )

        if key not in wanted:
            continue

        print(
            f"CAP_{edge['source_cap']}:"
            f"{edge['source_section']} "
            f"-> {edge['target_ref']} "
            f"[{edge['target_kind']}; "
            f"{edge['resolution_status']}]"
        )


# ============================================================
# Main
# ============================================================

def main():

    parser = argparse.ArgumentParser(
        description=(
            "Synchronize deterministic "
            "explicit statutory references."
        )
    )

    mode = parser.add_mutually_exclusive_group(
        required=True
    )

    mode.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Calculate graph changes without "
            "writing to PostgreSQL."
        ),
    )

    mode.add_argument(
        "--sync",
        action="store_true",
        help=(
            "Synchronize deterministic "
            "explicit-reference edges."
        ),
    )

    args = parser.parse_args()

    edges = build_edges()
    existing = load_existing()

    (
        desired,
        inserts,
        updates,
        deletes,
    ) = plan_changes(
        edges,
        existing,
    )

    show_report(
        edges,
        existing,
        inserts,
        updates,
        deletes,
        "DRY-RUN"
        if args.dry_run
        else "SYNC",
    )

    if args.dry_run:

        print()
        print(
            "DRY-RUN ONLY — database unchanged."
        )

        return


    print()
    print(
        "Synchronizing deterministic "
        "explicit-reference graph..."
    )

    sync_database(
        desired,
        deletes,
    )


    after = load_existing()

    if len(after) != len(edges):

        raise SystemExit(
            "POST-SYNC VALIDATION FAILED: "
            f"expected {len(edges)} "
            f"managed edges, found "
            f"{len(after)}."
        )


    print()
    print("=" * 82)
    print("SYNC COMMITTED")
    print("=" * 82)

    print(
        f"Managed explicit-reference "
        f"edges: {len(after)}"
    )

    print(
        "Post-sync validation: PASS"
    )


if __name__ == "__main__":
    main()
