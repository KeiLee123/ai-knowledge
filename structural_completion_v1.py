#!/usr/bin/env python3

import copy
import json
import subprocess


DB_CONTAINER = (
    "ai-knowledge-db-jiyckdrlappwgimwebnzxwmr"
)

DB_USER = "ai_knowledge"
DB_NAME = "ai_knowledge"


def load_completion_chunk(chunk_id):

    chunk_id = int(chunk_id)

    sql = f"""
SELECT json_build_object(
    'chunk_id', c.id,
    'document_id', c.document_id,
    'section_id', c.section_id,
    'section_number', s.section_number,
    'heading', s.heading,
    'page_start', c.page_start,
    'page_end', c.page_end,
    'content', c.content,
    'metadata', c.metadata
)::text
FROM chunks c
LEFT JOIN sections s
  ON s.id = c.section_id
WHERE c.id = {chunk_id};
"""

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
            or "Completion chunk lookup failed."
        )

    rows = [
        line
        for line in p.stdout.splitlines()
        if line.strip()
    ]

    if len(rows) != 1:
        raise RuntimeError(
            "Expected exactly one completion chunk "
            f"for {chunk_id}; got {len(rows)}."
        )

    return json.loads(
        rows[0]
    )


def apply_structural_completion(
    retrieval,
):

    out = copy.deepcopy(
        retrieval
    )

    resolution = (
        out.get(
            "query_subject_resolution"
        )
        or {}
    )

    diagnostic = {
        "status": "not-applied",
        "reason": None,
    }

    out[
        "structural_completion"
    ] = diagnostic


    # --------------------------------------------------------
    # Narrow activation gate.
    # --------------------------------------------------------

    if (
        resolution.get(
            "status"
        )
        != "confirmed"
    ):
        diagnostic[
            "reason"
        ] = "subject-not-confirmed"

        return out


    if (
        resolution.get(
            "method"
        )
        != "structural-qualification"
    ):
        diagnostic[
            "reason"
        ] = "not-structural-qualification"

        return out


    evidence_chunk_id = (
        resolution.get(
            "evidence_chunk_id"
        )
    )

    completion_chunk_id = (
        resolution.get(
            "completion_chunk_id"
        )
    )

    section_id = (
        resolution.get(
            "section_id"
        )
    )

    document_id = (
        resolution.get(
            "document_id"
        )
    )


    if (
        evidence_chunk_id is None
        or completion_chunk_id is None
        or section_id is None
        or document_id is None
    ):
        diagnostic[
            "reason"
        ] = "incomplete-resolution-contract"

        return out


    evidence_chunk_id = int(
        evidence_chunk_id
    )

    completion_chunk_id = int(
        completion_chunk_id
    )

    section_id = int(
        section_id
    )

    document_id = int(
        document_id
    )


    if (
        evidence_chunk_id
        == completion_chunk_id
    ):
        diagnostic[
            "reason"
        ] = "same-chunk"

        return out


    results = (
        out.get(
            "results"
        )
        or []
    )


    matches = [
        (
            index,
            item,
        )
        for index, item
        in enumerate(results)
        if (
            int(
                item.get(
                    "chunk_id",
                    -1,
                )
            )
            == evidence_chunk_id
            and item.get(
                "answer_evidence_origin"
            )
            == "primary"
        )
    ]


    if len(matches) != 1:
        diagnostic[
            "reason"
        ] = (
            "trigger-primary-result-count-"
            f"{len(matches)}"
        )

        return out


    target_index, original = (
        matches[0]
    )


    # --------------------------------------------------------
    # Never introduce duplicate answer evidence.
    # --------------------------------------------------------

    for index, item in enumerate(
        results
    ):

        if index == target_index:
            continue

        if (
            int(
                item.get(
                    "chunk_id",
                    -1,
                )
            )
            == completion_chunk_id
        ):
            diagnostic[
                "reason"
            ] = (
                "completion-chunk-already-present"
            )

            return out


    completion = load_completion_chunk(
        completion_chunk_id
    )

    metadata = (
        completion.get(
            "metadata"
        )
        or {}
    )


    # --------------------------------------------------------
    # Fail-closed identity / status validation.
    # --------------------------------------------------------

    checks = {
        "document_id":
            int(
                completion[
                    "document_id"
                ]
            )
            == document_id,

        "section_id":
            int(
                completion[
                    "section_id"
                ]
            )
            == section_id,

        "retrieval_role":
            metadata.get(
                "retrieval_role"
            )
            == "legal-exact",

        "operative":
            metadata.get(
                "operative"
            )
            is True,

        "repealed":
            metadata.get(
                "repealed"
            )
            is False,

        "not_in_operation":
            metadata.get(
                "not_in_operation"
            )
            is False,

        "omitted_as_spent":
            metadata.get(
                "omitted_as_spent"
            )
            is False,

        "longer_content":
            len(
                completion.get(
                    "content"
                )
                or ""
            )
            >
            len(
                original.get(
                    "content"
                )
                or ""
            ),
    }


    failed_checks = [
        name
        for name, passed
        in checks.items()
        if not passed
    ]


    if failed_checks:
        diagnostic[
            "reason"
        ] = (
            "validation-failed:"
            + ",".join(
                failed_checks
            )
        )

        return out


    # --------------------------------------------------------
    # Upgrade in place.
    #
    # Ranking identity remains the semantic chunk.
    # Evidence identity becomes the full legal-exact chunk.
    # --------------------------------------------------------

    upgraded = dict(
        original
    )

    upgraded[
        "ranked_via_chunk_id"
    ] = evidence_chunk_id

    upgraded[
        "completion_chunk_id"
    ] = completion_chunk_id

    upgraded[
        "completion_mode"
    ] = "structural-exact"

    upgraded[
        "chunk_id"
    ] = completion_chunk_id

    upgraded[
        "content"
    ] = completion[
        "content"
    ]

    upgraded[
        "section_number"
    ] = completion.get(
        "section_number"
    )

    upgraded[
        "heading"
    ] = completion.get(
        "heading"
    )

    upgraded[
        "page_start"
    ] = completion.get(
        "page_start"
    )

    upgraded[
        "page_end"
    ] = completion.get(
        "page_end"
    )


    results[
        target_index
    ] = upgraded


    diagnostic.update({
        "status":
            "applied",

        "mode":
            "structural-exact",

        "ranked_via_chunk_id":
            evidence_chunk_id,

        "completion_chunk_id":
            completion_chunk_id,

        "answer_rank":
            upgraded.get(
                "rank"
            ),

        "primary_rank":
            upgraded.get(
                "primary_rank"
            ),

        "original_content_length":
            len(
                original.get(
                    "content"
                )
                or ""
            ),

        "completion_content_length":
            len(
                completion.get(
                    "content"
                )
                or ""
            ),
    })


    answer_evidence = (
        out.get(
            "answer_evidence"
        )
        or {}
    )

    answer_evidence[
        "structural_completion_count"
    ] = 1

    out[
        "answer_evidence"
    ] = answer_evidence


    return out
