#!/usr/bin/env python3

import json
import re
import subprocess


DB_CONTAINER = (
    "ai-knowledge-db-jiyckdrlappwgimwebnzxwmr"
)

DB_USER = "ai_knowledge"
DB_NAME = "ai_knowledge"


def psql(sql):

    p = subprocess.run(
        [
            "docker",
            "exec",
            "-i",
            DB_CONTAINER,
            "psql",
            "-U",
            DB_USER,
            "-d",
            DB_NAME,
            "-At",
            "-v",
            "ON_ERROR_STOP=1",
        ],
        input=sql,
        text=True,
        capture_output=True,
    )

    if p.returncode != 0:

        raise RuntimeError(
            p.stderr.strip()
            or p.stdout.strip()
            or "Database query failed."
        )

    return [
        line
        for line in p.stdout.splitlines()
        if line.strip()
    ]


def subject_key(value):

    return re.sub(
        r"[^a-z0-9]+",
        "",
        str(value).casefold(),
    )


def strip_wrapping_quotes(value):

    value = str(value).strip()

    pairs = (
        ('"', '"'),
        ("'", "'"),
        ("“", "”"),
        ("‘", "’"),
    )

    for left, right in pairs:

        if (
            len(value) >= 2
            and value.startswith(left)
            and value.endswith(right)
        ):

            return value[
                len(left):
                -len(right)
            ].strip()

    return value


def clean_subject(value):

    value = strip_wrapping_quotes(
        str(value).strip(
            " ?？."
        )
    )

    value = re.sub(
        r"^(?:a|an|the)\s+",
        "",
        value,
        flags=re.IGNORECASE,
    )

    return value.strip()


def extract_candidate(question):

    text = " ".join(
        str(question).strip().split()
    )

    patterns = (

        # ----------------------------------------------------
        # High-confidence definition forms
        # ----------------------------------------------------

        r"^what\s+does\s+(.+?)\s+mean"
        r"(?:\s+under\b|\s+in\b|[?？]|$)",

        r"^what\s+is\s+meant\s+by\s+(.+?)"
        r"(?:\s+under\b|\s+in\b|[?？]|$)",

        r"^what\s+is\s+the\s+definition\s+of\s+(.+?)"
        r"(?:\s+under\b|\s+in\b|[?？]|$)",

        r"^define\s+(.+?)"
        r"(?:\s+under\b|\s+in\b|[?？.]|$)",

        r"^how\s+is\s+(.+?)\s+defined"
        r"(?:\s+under\b|\s+in\b|[?？]|$)",


        # ----------------------------------------------------
        # Qualification forms
        # ----------------------------------------------------

        r"^under\s+.+?,\s*when\s+is\s+.+?"
        r"\s+considered\s+(?:a|an|the)\s+(.+?)"
        r"[?？]?$",

        r"^when\s+is\s+.+?"
        r"\s+considered\s+(?:a|an|the)\s+(.+?)"
        r"(?:\s+under\b|\s+in\b|[?？]|$)",


        # ----------------------------------------------------
        # Traditional Chinese definition form
        # ----------------------------------------------------

        r"^.*?對\s+(.+?)\s+的定義"
        r"\s*(?:是甚麼|是什麼)\s*[?？]?$",


        # ----------------------------------------------------
        # Ambiguous forms.
        #
        # These are SAFE only because corpus confirmation
        # below is mandatory before a Subject Lock is allowed.
        # ----------------------------------------------------

        r"^what\s+is\s+(?:a|an|the)\s+(.+?)"
        r"(?:\s+under\b|\s+in\b|[?？]|$)",

        r"^what\s+are\s+(.+?)"
        r"(?:\s+under\b|\s+in\b|[?？]|$)",
    )


    for pattern in patterns:

        match = re.search(
            pattern,
            text,
            flags=re.IGNORECASE,
        )

        if not match:
            continue


        subject = clean_subject(
            match.group(1)
        )


        if (
            subject
            and len(subject) <= 120
        ):

            return subject


    return None


def resolve_scope_document_id(scope):

    if not isinstance(
        scope,
        dict,
    ):

        return None


    if (
        scope.get(
            "status"
        )
        != "resolved"
    ):

        return None


    candidates = (
        scope.get(
            "candidates"
        )
        or []
    )


    if len(candidates) != 1:
        return None


    document_ids = (
        candidates[0].get(
            "document_ids"
        )
        or []
    )


    if len(document_ids) != 1:
        return None


    return int(
        document_ids[0]
    )


def confirm_metadata_definition(
    document_id,
    subject,
):

    key = subject_key(
        subject
    )


    if not key:
        return None


    rows = psql(
        f"""
SELECT json_build_object(

    'chunk_id',
        c.id,

    'section_number',
        s.section_number,

    'definition_name',
        c.metadata->>'definition_name',

    'parent_reference',
        c.metadata->>'parent_reference',

    'semantic_part',
        c.metadata->>'semantic_part',

    'semantic_parts',
        c.metadata->>'semantic_parts'

)::text

FROM chunks c

LEFT JOIN sections s
    ON s.id = c.section_id

WHERE
    c.document_id = {int(document_id)}

    AND c.metadata->>'retrieval_role'
        = 'legal-semantic'

    AND c.metadata->>'semantic_type'
        = 'definition'

    AND c.metadata->>'operative'
        = 'true'

    AND c.metadata->>'repealed'
        = 'false'

    AND c.metadata->>'not_in_operation'
        = 'false'

    AND c.metadata->>'omitted_as_spent'
        = 'false'

    AND regexp_replace(
        lower(
            c.metadata->>'definition_name'
        ),
        '[^a-z0-9]+',
        '',
        'g'
    ) = '{key}'

ORDER BY
    c.metadata->>'parent_reference',
    (
        c.metadata->>'semantic_part'
    )::int,
    c.id;
"""
    )


    if not rows:
        return None


    matches = [
        json.loads(
            row
        )
        for row in rows
    ]


    occurrence_refs = []

    seen = set()


    for item in matches:

        parent_reference = (
            item.get(
                "parent_reference"
            )
        )

        if parent_reference in seen:
            continue

        seen.add(
            parent_reference
        )

        occurrence_refs.append(
            parent_reference
        )


    return {
        "method":
            "metadata-definition",

        "definition_chunks":
            len(matches),

        "definition_occurrences":
            len(occurrence_refs),

        "occurrence_references":
            occurrence_refs,

        "evidence_chunk_ids": [
            int(
                item[
                    "chunk_id"
                ]
            )
            for item in matches
        ],
    }


def structural_predicate_matches(
    content,
    subject,
):

    text = " ".join(
        str(content).strip().split()
    )

    escaped = re.escape(
        subject
    )


    pattern = (
        rf"\b(?:is|are)\s+"
        rf"(?:a\s+|an\s+|the\s+)?"
        rf"{escaped}"
        rf"\s+only\s+if\s*—\s*$"
    )


    return bool(
        re.search(
            pattern,
            text,
            flags=re.IGNORECASE,
        )
    )


def load_structural_candidates(
    document_id,
):

    rows = psql(
        f"""
SELECT json_build_object(

    'chunk_id',
        c.id,

    'section_id',
        s.id,

    'section_number',
        s.section_number,

    'content',
        c.content,

    'semantic_length',
        length(
            c.content
        ),

    'direct_child_count',
        (
            SELECT COUNT(*)

            FROM sections child

            WHERE
                child.parent_section_id
                    = s.id
        ),

    'exact_chunk_id',
        exact.chunk_id,

    'exact_length',
        exact.content_length

)::text

FROM chunks c

JOIN sections s
    ON s.id = c.section_id

LEFT JOIN LATERAL (

    SELECT
        ce.id AS chunk_id,
        length(
            ce.content
        ) AS content_length

    FROM chunks ce

    WHERE
        ce.document_id
            = c.document_id

        AND ce.section_id
            = c.section_id

        AND ce.metadata->>'retrieval_role'
            = 'legal-exact'

        AND ce.metadata->>'operative'
            = 'true'

        AND ce.metadata->>'repealed'
            = 'false'

        AND ce.metadata->>'not_in_operation'
            = 'false'

        AND ce.metadata->>'omitted_as_spent'
            = 'false'

    ORDER BY
        length(
            ce.content
        ) DESC,
        ce.id

    LIMIT 1

) exact
    ON TRUE

WHERE
    c.document_id = {int(document_id)}

    AND c.metadata->>'retrieval_role'
        = 'legal-semantic'

    AND c.metadata->>'semantic_type'
        = 'canonical-atomic'

    AND c.metadata->>'operative'
        = 'true'

    AND c.metadata->>'repealed'
        = 'false'

    AND c.metadata->>'not_in_operation'
        = 'false'

    AND c.metadata->>'omitted_as_spent'
        = 'false'

    AND c.content ~*
        '(is|are)[[:space:]]+.{{1,160}}'
        '[[:space:]]+only[[:space:]]+if'
        '[[:space:]]*—[[:space:]]*$'

ORDER BY
    s.sort_order NULLS LAST,
    c.id;
"""
    )


    return [
        json.loads(
            row
        )
        for row in rows
    ]


def confirm_structural_qualification(
    document_id,
    subject,
):

    candidates = (
        load_structural_candidates(
            document_id
        )
    )


    for item in candidates:

        child_count = int(
            item.get(
                "direct_child_count"
            )
            or 0
        )

        exact_chunk_id = (
            item.get(
                "exact_chunk_id"
            )
        )

        exact_length = int(
            item.get(
                "exact_length"
            )
            or 0
        )

        semantic_length = int(
            item.get(
                "semantic_length"
            )
            or 0
        )


        if child_count < 1:
            continue


        if exact_chunk_id is None:
            continue


        if (
            exact_length
            <= semantic_length
        ):

            continue


        if not structural_predicate_matches(
            item.get(
                "content",
                "",
            ),
            subject,
        ):

            continue


        return {
            "method":
                "structural-qualification",

            "evidence_chunk_id":
                int(
                    item[
                        "chunk_id"
                    ]
                ),

            "section_id":
                int(
                    item[
                        "section_id"
                    ]
                ),

            "section_number":
                item.get(
                    "section_number"
                ),

            "direct_child_count":
                child_count,

            # Useful later for F2 structural completion.
            # This does NOT itself modify answer evidence.
            "completion_chunk_id":
                int(
                    exact_chunk_id
                ),

            "semantic_length":
                semantic_length,

            "completion_length":
                exact_length,
        }


    return None


def resolve_query_subject(
    question,
    document_scope,
):

    candidate = extract_candidate(
        question
    )


    if not candidate:

        return {
            "status":
                "not-confirmed",

            "reason":
                "no-candidate",
        }


    document_id = (
        resolve_scope_document_id(
            document_scope
        )
    )


    if document_id is None:

        return {
            "status":
                "not-confirmed",

            "candidate":
                candidate,

            "reason":
                "scope-not-uniquely-resolved",
        }


    evidence = (
        confirm_metadata_definition(
            document_id,
            candidate,
        )
    )


    if evidence is None:

        evidence = (
            confirm_structural_qualification(
                document_id,
                candidate,
            )
        )


    if evidence is None:

        return {
            "status":
                "not-confirmed",

            "candidate":
                candidate,

            "document_id":
                document_id,

            "document_title":
                document_scope.get(
                    "document_title"
                ),

            "reason":
                "corpus-not-confirmed",
        }


    return {
        "status":
            "confirmed",

        "subject":
            candidate,

        "subject_key":
            subject_key(
                candidate
            ),

        "document_id":
            document_id,

        "document_title":
            document_scope.get(
                "document_title"
            ),

        **evidence,
    }
