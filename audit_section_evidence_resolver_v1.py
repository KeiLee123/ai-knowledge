#!/usr/bin/env python3

import json
import re
import subprocess
import sys
from collections import defaultdict


DB_CONTAINER = (
    "ai-knowledge-db-jiyckdrlappwgimwebnzxwmr"
)


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

        print(
            p.stdout,
            file=sys.stderr,
        )

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
# Load section graph edges
# ============================================================

edge_rows = psql("""
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

ORDER BY
    cr.metadata->>'source_ref',
    cr.metadata->>'target_ref';
""")


edges = [
    json.loads(x)
    for x in edge_rows
]


source_ids = sorted({
    int(chunk_id)

    for edge in edges

    for chunk_id in (
        edge.get(
            "source_chunk_ids"
        )
        or []
    )
})


target_section_ids = sorted({
    int(
        edge[
            "target_section_id"
        ]
    )

    for edge in edges

    if edge.get(
        "target_section_id"
    )
    is not None
})


# ============================================================
# Load source provenance chunks
# ============================================================

source_id_sql = ",".join(
    str(x)
    for x in source_ids
)


source_rows = psql(f"""
SELECT json_build_object(

    'chunk_id',
        c.id,

    'semantic_type',
        c.metadata->>'semantic_type',

    'definition_name',
        c.metadata->>'definition_name',

    'content',
        c.content

)::text

FROM chunks c

WHERE
    c.id IN (
        {source_id_sql}
    );
""")


sources = {
    int(item["chunk_id"]): item

    for item in (
        json.loads(x)
        for x in source_rows
    )
}


# ============================================================
# Load target semantic candidates
# ============================================================

target_id_sql = ",".join(
    str(x)
    for x in target_section_ids
)


target_rows = psql(f"""
SELECT json_build_object(

    'section_id',
        c.section_id,

    'chunk_id',
        c.id,

    'semantic_type',
        c.metadata->>'semantic_type',

    'definition_name',
        c.metadata->>'definition_name',

    'content',
        c.content

)::text

FROM chunks c

WHERE
    c.section_id IN (
        {target_id_sql}
    )

    AND c.metadata->>'retrieval_role'
        = 'legal-semantic'

    AND COALESCE(
        c.metadata->>'operative',
        'true'
    ) = 'true'

ORDER BY
    c.section_id,
    c.id;
""")


targets_by_section = defaultdict(
    list
)


for line in target_rows:

    item = json.loads(
        line
    )

    targets_by_section[
        int(
            item[
                "section_id"
            ]
        )
    ].append(
        item
    )


# ============================================================
# Citation-window term matching
# ============================================================

def citation_window(
    content,
    target_section_ref,
):

    if (
        not content
        or not target_section_ref
    ):

        return ""


    text = content.strip()


    # --------------------------------------------------------
    # Remove generated source-document prefix.
    #
    # Examples:
    #
    #   Cap. 123 Buildings Ordinance.
    #   Cap. 618 Lifts and Escalators Ordinance.
    #   Cap. 636 Fire Safety (Industrial Buildings) Ordinance.
    #
    # Without this step, target terms such as Building,
    # Lift and Escalator can match the SOURCE document title
    # rather than the actual citation phrase.
    # --------------------------------------------------------

    text = re.sub(
        r'^Cap\.\s*'
        r'[0-9]+[A-Z]?\s+'
        r'[^.\n]{1,220}\.\s*',
        '',
        text,
        count=1,
        flags=re.I,
    )


    escaped = re.escape(
        target_section_ref
    )


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


    for m in matches:

        start = max(
            0,
            m.start() - 240,
        )

        window = text[
            start:m.start()
        ].strip()

        if window:

            windows.append(
                window
            )


    return " ".join(
        windows
    )



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


    matches = []


    for candidate in target_candidates:

        definition_name = (
            candidate.get(
                "definition_name"
            )
        )


        for alias in split_definition_names(
            definition_name
        ):

            key = normalize_term(
                alias
            )

            if (
                len(key) >= 3
                and key
                in normalized_window
            ):

                matches.append({
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
    #   source phrase = "building works"
    #
    # candidates:
    #
    #   Building
    #   BuildingWorks
    #
    # Keep BuildingWorks only.
    # --------------------------------------------------------

    filtered = []


    for item in matches:

        key = item[
            "key"
        ]


        nested = False


        for other in matches:

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


    # Deduplicate by target chunk.
    unique = {}


    for item in filtered:

        chunk_id = int(
            item[
                "candidate"
            ][
                "chunk_id"
            ]
        )

        unique[
            chunk_id
        ] = item[
            "candidate"
        ]


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
# Resolve every source provenance mapping
# ============================================================

results = []


for edge in edges:

    target_section_id = int(
        edge[
            "target_section_id"
        ]
    )


    target_candidates = (
        targets_by_section[
            target_section_id
        ]
    )


    for source_chunk_id in (
        edge.get(
            "source_chunk_ids"
        )
        or []
    ):

        source_chunk_id = int(
            source_chunk_id
        )

        source = sources[
            source_chunk_id
        ]


        selected = []

        mode = None


        # ----------------------------------------------------
        # Rule 1:
        # only one possible semantic target.
        # ----------------------------------------------------

        if len(
            target_candidates
        ) == 1:

            selected = [
                target_candidates[0]
            ]

            mode = (
                "single-target"
            )


        # ----------------------------------------------------
        # Rule 2:
        # resolve the actual term appearing immediately
        # around the statutory citation.
        #
        # This intentionally comes BEFORE generic definition
        # identity.
        #
        # Example:
        #
        # GroundInvestigation... source chunk still says:
        #
        # "building works within the meaning assigned to
        # that term in section 2(1)..."
        #
        # Therefore the cited target is BuildingWorks.
        # ----------------------------------------------------

        if not selected:

            selected = (
                citation_term_matches(
                    source,
                    target_candidates,
                    edge.get(
                        "target_section_ref"
                    ),
                )
            )

            if selected:

                mode = (
                    "citation-term"
                )


        # ----------------------------------------------------
        # Rule 3:
        # exact definition identity.
        # ----------------------------------------------------

        if not selected:

            selected = (
                definition_identity_matches(
                    source,
                    target_candidates,
                )
            )

            if selected:

                mode = (
                    "definition-identity"
                )


        # ----------------------------------------------------
        # Rule 4:
        # no automatic cosine decision yet.
        #
        # Any remaining case requires fallback/review.
        # ----------------------------------------------------

        if not selected:

            mode = (
                "needs-fallback"
            )


        results.append({
            "edge_id":
                edge["edge_id"],

            "source_ref":
                edge["source_ref"],

            "target_ref":
                edge["target_ref"],

            "source_chunk_id":
                source_chunk_id,

            "source_definition":
                source.get(
                    "definition_name"
                ),

            "target_candidate_count":
                len(
                    target_candidates
                ),

            "resolution_mode":
                mode,

            "selected":
                selected,
        })


# ============================================================
# Report
# ============================================================

print(
    "=" * 100
)

print(
    "SECTION EVIDENCE RESOLVER V1 — DRY AUDIT"
)

print(
    "=" * 100
)


fallback_count = 0

selected_mapping_count = 0

edge_targets = defaultdict(
    set
)


for item in results:

    if (
        item[
            "resolution_mode"
        ]
        == "needs-fallback"
    ):

        fallback_count += 1


    selected_mapping_count += len(
        item[
            "selected"
        ]
    )


    for target in item[
        "selected"
    ]:

        edge_targets[
            item["edge_id"]
        ].add(
            int(
                target[
                    "chunk_id"
                ]
            )
        )


    print()

    print(
        f"{item['source_ref']} "
        f"-> "
        f"{item['target_ref']}"
    )

    print(
        "   source chunk:",
        item[
            "source_chunk_id"
        ],
    )

    print(
        "   source definition:",
        item.get(
            "source_definition"
        )
        or "(none)",
    )

    print(
        "   candidates:",
        item[
            "target_candidate_count"
        ],
    )

    print(
        "   mode:",
        item[
            "resolution_mode"
        ],
    )


    if not item[
        "selected"
    ]:

        print(
            "   selected:",
            "(none)"
        )

    else:

        for target in item[
            "selected"
        ]:

            print(
                "   selected:",
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
    "=" * 100
)

print(
    "SUMMARY"
)

print(
    "=" * 100
)

print(
    "section edges:",
    len(edges),
)

print(
    "source provenance mappings:",
    len(results),
)

print(
    "selected source->target mappings:",
    selected_mapping_count,
)

print(
    "edge-deduplicated target chunks:",
    sum(
        len(x)
        for x in edge_targets.values()
    ),
)

print(
    "needs fallback:",
    fallback_count,
)


if fallback_count:

    raise SystemExit(2)
