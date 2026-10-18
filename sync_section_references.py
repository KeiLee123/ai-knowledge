#!/usr/bin/env python3

import argparse
import json
import re
import subprocess
from collections import defaultdict

DB_CONTAINER = "ai-knowledge-db-jiyckdrlappwgimwebnzxwmr"

PARENT_EXTRACTOR = "explicit-reference-v1"
EXTRACTOR = "explicit-section-reference-v1"
RELATIONSHIP = "explicit-section-reference"
SCHEMA_VERSION = 1


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
# Section-reference grammar
# ============================================================

FULL_REF_RE = re.compile(
    r'^[0-9]+[A-Za-z]*'
    r'(?:\([0-9A-Za-z]+\))*$'
)

RELATIVE_REF_RE = re.compile(
    r'^(?:\([0-9A-Za-z]+\))+$'
)


def split_groups(ref):

    m = re.match(
        r'^([0-9]+[A-Za-z]*)'
        r'((?:\([0-9A-Za-z]+\))*)$',
        ref,
    )

    if not m:
        return None, []

    base = m.group(1)

    groups = re.findall(
        r'\(([0-9A-Za-z]+)\)',
        m.group(2),
    )

    return base, groups


def normalize_relative(
    previous,
    relative,
):

    base, previous_groups = (
        split_groups(previous)
    )

    relative_groups = re.findall(
        r'\(([0-9A-Za-z]+)\)',
        relative,
    )

    if (
        base is None
        or not relative_groups
    ):
        return None


    first = relative_groups[0]


    # Example:
    #   18(2) and (3)
    #       -> 18(2), 18(3)
    #
    #   3(2)(b) or (3)
    #       -> 3(2)(b), 3(3)
    if first.isdigit():

        return (
            base
            + "".join(
                f"({x})"
                for x in relative_groups
            )
        )


    # Example:
    #   3(2)(a) and (b)
    #       -> 3(2)(a), 3(2)(b)
    keep = max(
        0,
        len(previous_groups)
        - len(relative_groups)
    )

    prefix_groups = (
        previous_groups[:keep]
    )

    return (
        base
        + "".join(
            f"({x})"
            for x in prefix_groups
        )
        + "".join(
            f"({x})"
            for x in relative_groups
        )
    )


def parse_ref_list(raw):

    text = raw.strip()

    text = re.sub(
        r'\s*(?:,?\s+and\s+|'
        r',?\s+or\s+|\s*&\s*)',
        ',',
        text,
        flags=re.I,
    )

    parts = [
        x.strip()
        for x in text.split(",")
        if x.strip()
    ]

    refs = []
    previous = None

    for part in parts:

        part = re.sub(
            r'\s+',
            '',
            part,
        )

        if FULL_REF_RE.fullmatch(part):

            refs.append(part)
            previous = part
            continue


        if (
            previous
            and RELATIVE_REF_RE.fullmatch(
                part
            )
        ):

            expanded = normalize_relative(
                previous,
                part,
            )

            if expanded:

                refs.append(expanded)
                previous = expanded
                continue


        return None

    return refs


# ============================================================
# Existing resolved document-level graph
# ============================================================

def load_parent_edges():

    rows = psql(f"""
SELECT json_build_object(
    'id', cr.id,

    'edge_key',
        cr.metadata->>'edge_key',

    'source_ref',
        cr.metadata->>'source_ref',

    'source_document_id',
        cr.source_document_id,

    'source_section_id',
        cr.source_section_id,

    'source_section',
        ss.section_number,

    'target_document_id',
        cr.target_document_id,

    'target_ref',
        cr.metadata->>'target_ref',

    'source_chunk_ids',
        cr.metadata->'source_chunk_ids'

)::text

FROM cross_references cr

JOIN sections ss
    ON ss.id =
        cr.source_section_id

WHERE
    cr.relationship =
        'explicit-reference'

    AND cr.metadata->>'extractor' =
        '{PARENT_EXTRACTOR}'

    AND cr.metadata->>'target_kind' =
        'principal-ordinance'

    AND cr.metadata->>'resolution_status' =
        'resolved'

    AND cr.target_document_id
        IS NOT NULL

ORDER BY
    cr.metadata->>'edge_key';
""")

    return [
        json.loads(x)
        for x in rows
    ]


# ============================================================
# Evidence chunks
# ============================================================

def load_chunk_map(parent_edges):

    chunk_ids = sorted({
        int(chunk_id)

        for edge in parent_edges

        for chunk_id in (
            edge["source_chunk_ids"]
            or []
        )
    })

    if not chunk_ids:
        return {}


    ids = ",".join(
        str(x)
        for x in chunk_ids
    )

    result = {}

    for line in psql(f"""
SELECT json_build_object(
    'id', id,
    'content', content
)::text
FROM chunks
WHERE id IN ({ids});
"""):

        obj = json.loads(line)

        result[obj["id"]] = (
            obj["content"]
            or ""
        )

    return result


# ============================================================
# Target section catalogue
# ============================================================

def load_sections():

    result = defaultdict(
        lambda: defaultdict(list)
    )

    rows = psql("""
SELECT json_build_object(
    'document_id', document_id,
    'section_id', id,
    'section_number', section_number
)::text
FROM sections
ORDER BY
    document_id,
    sort_order,
    id;
""")

    for line in rows:

        obj = json.loads(line)

        result[
            obj["document_id"]
        ][
            obj["section_number"]
        ].append(
            obj["section_id"]
        )

    return result


# ============================================================
# Citation pattern A:
#
# section 2(1) of ... Ordinance (Cap.123)
# ============================================================

def find_before_cap(
    content,
    cap,
    failures,
    chunk_id,
):

    pattern = re.compile(
        rf'''
        \bsections?\s+

        (?P<refs>
            [0-9A-Za-z()
            .,\-\s&]+?
        )

        \s+of\s+

        (?:the\s+)?

        .{{0,220}}?

        \(Cap\.?\s*
        {re.escape(cap)}
        \)
        ''',
        re.I | re.X,
    )

    results = []

    for m in pattern.finditer(
        content
    ):

        raw_refs = (
            m.group("refs")
            .strip()
        )

        refs = parse_ref_list(
            raw_refs
        )

        if refs is None:

            failures.append({
                "chunk_id":
                    chunk_id,

                "pattern":
                    "section-before-cap",

                "raw_refs":
                    raw_refs,

                "evidence":
                    m.group(0),
            })

            continue


        results.append({
            "refs":
                refs,

            "pattern":
                "section-before-cap",

            "evidence":
                m.group(0),
        })

    return results


# ============================================================
# Citation pattern B:
#
# ... Ordinance (Cap.102) ...
# section 17(2)(b) of that Ordinance
# ============================================================

def find_after_cap(
    content,
    cap,
    failures,
    chunk_id,
):

    cap_pattern = re.compile(
        rf'\(Cap\.?\s*'
        rf'{re.escape(cap)}\)',
        re.I,
    )

    results = []

    for cap_match in cap_pattern.finditer(
        content
    ):

        after = content[
            cap_match.end():
            min(
                len(content),
                cap_match.end()
                + 350,
            )
        ]


        # Stop before another Cap. citation.
        next_cap = re.search(
            r'\(Cap\.?\s*'
            r'[0-9]+[A-Z]?\)',
            after,
            re.I,
        )

        if next_cap:

            after = after[
                :next_cap.start()
            ]


        pattern = re.compile(
            r'''
            \bsections?\s+

            (?P<refs>
                [0-9A-Za-z()
                .,\-\s&]+?
            )

            \s+of\s+

            (?:that|the)\s+
            Ordinance
            ''',
            re.I | re.X,
        )


        for m in pattern.finditer(
            after
        ):

            raw_refs = (
                m.group("refs")
                .strip()
            )

            refs = parse_ref_list(
                raw_refs
            )

            if refs is None:

                failures.append({
                    "chunk_id":
                        chunk_id,

                    "pattern":
                        "section-after-cap-that-ordinance",

                    "raw_refs":
                        raw_refs,

                    "evidence":
                        m.group(0),
                })

                continue


            results.append({
                "refs":
                    refs,

                "pattern":
                    "section-after-cap-that-ordinance",

                "evidence":
                    m.group(0),
            })

    return results


# ============================================================
# Candidate extraction
# ============================================================

def build_candidates():

    parent_edges = (
        load_parent_edges()
    )

    chunk_map = load_chunk_map(
        parent_edges
    )

    sections = load_sections()

    candidates = {}

    parse_failures = []


    for parent in parent_edges:

        target_ref = (
            parent["target_ref"]
        )

        cap = target_ref.replace(
            "CAP_",
            "",
        )

        source_ref = (
            parent["source_ref"]
        )


        for chunk_id in (
            parent["source_chunk_ids"]
            or []
        ):

            chunk_id = int(chunk_id)

            content = chunk_map.get(
                chunk_id,
                "",
            )


            matches = []

            matches.extend(
                find_before_cap(
                    content,
                    cap,
                    parse_failures,
                    chunk_id,
                )
            )

            matches.extend(
                find_after_cap(
                    content,
                    cap,
                    parse_failures,
                    chunk_id,
                )
            )


            for match in matches:

                for target_section in (
                    match["refs"]
                ):

                    section_ids = (
                        sections[
                            parent[
                                "target_document_id"
                            ]
                        ][
                            target_section
                        ]
                    )


                    if len(section_ids) == 1:

                        status = "resolved"

                        target_section_id = (
                            section_ids[0]
                        )

                    elif len(section_ids) == 0:

                        status = "missing"

                        target_section_id = None

                    else:

                        status = "ambiguous"

                        target_section_id = None


                    edge_key = (
                        f"{RELATIONSHIP}|"
                        f"{source_ref}|"
                        f"{target_ref}|"
                        f"{target_section}"
                    )


                    if edge_key not in candidates:

                        candidates[
                            edge_key
                        ] = {
                            "edge_key":
                                edge_key,

                            "parent_edge_key":
                                parent[
                                    "edge_key"
                                ],

                            "source_ref":
                                source_ref,

                            "source_document_id":
                                parent[
                                    "source_document_id"
                                ],

                            "source_section_id":
                                parent[
                                    "source_section_id"
                                ],

                            "source_section":
                                parent[
                                    "source_section"
                                ],

                            "target_document_ref":
                                target_ref,

                            "target_document_id":
                                parent[
                                    "target_document_id"
                                ],

                            "target_section":
                                target_section,

                            "target_section_id":
                                target_section_id,

                            "status":
                                status,

                            "patterns":
                                set(),

                            "source_chunk_ids":
                                set(),

                            "mention_count":
                                0,
                        }


                    item = candidates[
                        edge_key
                    ]


                    # The same stable target must
                    # not resolve differently.
                    if (
                        item[
                            "target_section_id"
                        ]
                        != target_section_id
                        or item["status"]
                        != status
                    ):

                        raise SystemExit(
                            "Conflicting section "
                            "resolution for "
                            f"{edge_key}"
                        )


                    item["patterns"].add(
                        match["pattern"]
                    )

                    item[
                        "source_chunk_ids"
                    ].add(
                        chunk_id
                    )

                    item[
                        "mention_count"
                    ] += 1


    results = []

    for item in candidates.values():

        item["patterns"] = sorted(
            item["patterns"]
        )

        item[
            "source_chunk_ids"
        ] = sorted(
            item[
                "source_chunk_ids"
            ]
        )

        results.append(item)


    results.sort(
        key=lambda x: (
            x["edge_key"]
        )
    )

    return (
        parent_edges,
        results,
        parse_failures,
    )


# ============================================================
# Existing managed section edges
# ============================================================

def load_existing():

    rows = psql(f"""
SELECT json_build_object(
    'id', id,
    'edge_key',
        metadata->>'edge_key',
    'metadata', metadata
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
                "Managed section edge "
                "without edge_key: "
                f"id={obj['id']}"
            )

        if edge_key in existing:

            raise SystemExit(
                "Duplicate managed "
                "section edge_key: "
                f"{edge_key}"
            )

        existing[
            edge_key
        ] = obj

    return existing


# ============================================================
# Metadata
# ============================================================

def metadata_for(edge):

    return {
        "schema_version":
            SCHEMA_VERSION,

        "edge_key":
            edge["edge_key"],

        "parent_edge_key":
            edge[
                "parent_edge_key"
            ],

        "source_ref":
            edge["source_ref"],

        "target_document_ref":
            edge[
                "target_document_ref"
            ],

        "target_section_ref":
            edge[
                "target_section"
            ],

        "target_ref":
            (
                edge[
                    "target_document_ref"
                ]
                + ":"
                + edge[
                    "target_section"
                ]
            ),

        "resolution_status":
            "resolved",

        "regenerable":
            True,

        "extractor":
            EXTRACTOR,

        "parent_extractor":
            PARENT_EXTRACTOR,

        "pattern_types":
            edge["patterns"],

        "source_chunk_ids":
            edge[
                "source_chunk_ids"
            ],

        "mention_count":
            edge["mention_count"],
    }


# ============================================================
# Planning
# ============================================================

def plan_changes(
    resolved_edges,
    existing,
):

    desired = {
        edge["edge_key"]: edge
        for edge in resolved_edges
    }

    desired_keys = set(desired)
    existing_keys = set(existing)

    inserts = sorted(
        desired_keys - existing_keys
    )

    updates = sorted(
        desired_keys & existing_keys
    )

    deletes = sorted(
        existing_keys - desired_keys
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

def sync_database(desired):

    if not desired:

        raise SystemExit(
            "Refusing sync: desired "
            "section edge set is empty."
        )


    values = []

    for edge in desired.values():

        metadata = json.dumps(
            metadata_for(edge),
            ensure_ascii=False,
            separators=(",", ":"),
        )


        description = (
            "Explicit statutory "
            "section reference from "
            f"{edge['source_ref']} "
            "to "
            f"{edge['target_document_ref']}:"
            f"{edge['target_section']}."
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

                str(
                    edge[
                        "target_document_id"
                    ]
                ),

                str(
                    edge[
                        "target_section_id"
                    ]
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


    sql = f"""
BEGIN;

SELECT pg_advisory_xact_lock(
    hashtext(
        'explicit-section-reference-v1-sync'
    )
);


CREATE TEMP TABLE
desired_explicit_section_v1 (
    edge_key TEXT PRIMARY KEY,
    source_document_id BIGINT NOT NULL,
    source_section_id BIGINT NOT NULL,
    target_document_id BIGINT NOT NULL,
    target_section_id BIGINT NOT NULL,
    description TEXT,
    metadata JSONB NOT NULL
) ON COMMIT DROP;


INSERT INTO
desired_explicit_section_v1
VALUES
{",\n".join(values)};


-- Remove only stale edges owned by
-- this deterministic extractor.
DELETE FROM cross_references c
WHERE
    c.relationship =
        '{RELATIONSHIP}'

    AND c.metadata->>'extractor' =
        '{EXTRACTOR}'

    AND NOT EXISTS (
        SELECT 1
        FROM desired_explicit_section_v1 d
        WHERE
            d.edge_key =
                c.metadata->>'edge_key'
    );


-- Refresh managed edges.
UPDATE cross_references c
SET
    source_document_id =
        d.source_document_id,

    source_section_id =
        d.source_section_id,

    target_document_id =
        d.target_document_id,

    target_section_id =
        d.target_section_id,

    description =
        d.description,

    metadata =
        d.metadata

FROM desired_explicit_section_v1 d

WHERE
    c.relationship =
        '{RELATIONSHIP}'

    AND c.metadata->>'extractor' =
        '{EXTRACTOR}'

    AND c.metadata->>'edge_key' =
        d.edge_key;


-- Insert new edges.
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
    d.target_section_id,
    '{RELATIONSHIP}',
    d.description,
    d.metadata

FROM desired_explicit_section_v1 d

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


-- ========================================================
-- Safety validation
-- ========================================================

DO $$
DECLARE
    v_expected BIGINT;
    v_actual BIGINT;
    v_bad BIGINT;
BEGIN

    SELECT COUNT(*)
    INTO v_expected
    FROM desired_explicit_section_v1;


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
            'section-reference sync count mismatch: expected %, actual %',
            v_expected,
            v_actual;

    END IF;


    -- Every section edge must point to
    -- a target section belonging to its
    -- target document.
    SELECT COUNT(*)
    INTO v_bad

    FROM cross_references c

    LEFT JOIN sections ts
        ON ts.id =
            c.target_section_id

    WHERE
        c.relationship =
            '{RELATIONSHIP}'

        AND c.metadata->>'extractor' =
            '{EXTRACTOR}'

        AND (
            c.target_document_id
                IS NULL

            OR c.target_section_id
                IS NULL

            OR ts.id IS NULL

            OR ts.document_id <>
                c.target_document_id

            OR COALESCE(
                c.metadata->>'regenerable',
                'false'
            ) <> 'true'
        );


    IF v_bad <> 0 THEN

        RAISE EXCEPTION
            'invalid managed section-reference rows: %',
            v_bad;

    END IF;


    -- Every section-level relationship
    -- must still have its parent
    -- document-level relationship.
    SELECT COUNT(*)
    INTO v_bad

    FROM cross_references c

    WHERE
        c.relationship =
            '{RELATIONSHIP}'

        AND c.metadata->>'extractor' =
            '{EXTRACTOR}'

        AND NOT EXISTS (
            SELECT 1
            FROM cross_references p

            WHERE
                p.relationship =
                    'explicit-reference'

                AND p.metadata->>'extractor' =
                    '{PARENT_EXTRACTOR}'

                AND p.metadata->>'edge_key' =
                    c.metadata->>'parent_edge_key'
        );


    IF v_bad <> 0 THEN

        RAISE EXCEPTION
            'section-reference rows without parent document edge: %',
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
    parent_edges,
    candidates,
    parse_failures,
    existing,
    inserts,
    updates,
    deletes,
    mode,
):

    resolved = [
        x for x in candidates
        if x["status"]
            == "resolved"
    ]

    missing = [
        x for x in candidates
        if x["status"]
            == "missing"
    ]

    ambiguous = [
        x for x in candidates
        if x["status"]
            == "ambiguous"
    ]


    print("=" * 82)
    print(
        "EXPLICIT SECTION REFERENCE "
        "SYNCHRONIZER V1"
    )
    print("=" * 82)

    print(
        f"Mode                         : "
        f"{mode}"
    )

    print(
        "Resolved parent document edges:",
        len(parent_edges),
    )

    print(
        "Section-level candidates      :",
        len(candidates),
    )

    print(
        "Resolved target sections      :",
        len(resolved),
    )

    print(
        "Missing target sections       :",
        len(missing),
    )

    print(
        "Ambiguous target sections     :",
        len(ambiguous),
    )

    print(
        "Citation parse failures       :",
        len(parse_failures),
    )


    print()
    print(
        f"Existing managed edges       : "
        f"{len(existing)}"
    )

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
    print("CANARY SECTION RELATIONSHIPS")
    print("=" * 82)


    wanted = {
        (
            "explicit-reference|"
            "CAP_51|2|CAP_123",
            "2(1)",
        ),

        (
            "explicit-reference|"
            "CAP_123|2(1)|CAP_102",
            "17(2)(b)",
        ),

        (
            "explicit-reference|"
            "CAP_618|Sch.11 s.2(1)(d)|"
            "CAP_123",
            "3(2)(b)",
        ),

        (
            "explicit-reference|"
            "CAP_618|Sch.11 s.2(1)(d)|"
            "CAP_123",
            "3(3)",
        ),
    }


    for item in candidates:

        key = (
            item[
                "parent_edge_key"
            ],
            item[
                "target_section"
            ],
        )

        if key not in wanted:
            continue


        print(
            item[
                "parent_edge_key"
            ],
            "->",
            (
                item[
                    "target_document_ref"
                ]
                + ":"
                + item[
                    "target_section"
                ]
            ),
            f"[{item['status']}]",
        )


    if missing:

        print()
        print("MISSING:")

        for item in missing:

            print(
                " ",
                item["edge_key"]
            )


    if ambiguous:

        print()
        print("AMBIGUOUS:")

        for item in ambiguous:

            print(
                " ",
                item["edge_key"]
            )


    if parse_failures:

        print()
        print("PARSE FAILURES:")

        for item in parse_failures:

            print(
                " ",
                f"chunk={item['chunk_id']}",
                f"pattern={item['pattern']}",
                f"refs={item['raw_refs']!r}",
            )


# ============================================================
# Main
# ============================================================

def main():

    parser = argparse.ArgumentParser(
        description=(
            "Synchronize deterministic "
            "explicit statutory "
            "section references."
        )
    )


    mode = parser.add_mutually_exclusive_group(
        required=True
    )

    mode.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Calculate section graph "
            "changes without writing."
        ),
    )

    mode.add_argument(
        "--sync",
        action="store_true",
        help=(
            "Synchronize deterministic "
            "section-reference edges."
        ),
    )

    args = parser.parse_args()


    (
        parent_edges,
        candidates,
        parse_failures,
    ) = build_candidates()


    existing = load_existing()


    resolved = [
        x for x in candidates
        if x["status"]
            == "resolved"
    ]

    (
        desired,
        inserts,
        updates,
        deletes,
    ) = plan_changes(
        resolved,
        existing,
    )


    show_report(
        parent_edges,
        candidates,
        parse_failures,
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
            "DRY-RUN ONLY — "
            "database unchanged."
        )

        return


    missing = [
        x for x in candidates
        if x["status"]
            == "missing"
    ]

    ambiguous = [
        x for x in candidates
        if x["status"]
            == "ambiguous"
    ]


    # Fail safely rather than silently
    # writing a partial section graph.
    if (
        parse_failures
        or missing
        or ambiguous
    ):

        raise SystemExit(
            "SYNC REFUSED: unresolved "
            "section-reference conditions "
            "exist. Run --dry-run and "
            "inspect the report."
        )


    print()
    print(
        "Synchronizing deterministic "
        "section-reference graph..."
    )


    sync_database(
        desired
    )


    after = load_existing()


    if len(after) != len(resolved):

        raise SystemExit(
            "POST-SYNC VALIDATION FAILED: "
            f"expected {len(resolved)} "
            f"managed section edges, "
            f"found {len(after)}."
        )


    print()
    print("=" * 82)
    print("SYNC COMMITTED")
    print("=" * 82)

    print(
        "Managed explicit-section-reference "
        f"edges: {len(after)}"
    )

    print(
        "Post-sync validation: PASS"
    )


if __name__ == "__main__":
    main()
