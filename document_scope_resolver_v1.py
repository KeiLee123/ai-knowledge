#!/usr/bin/env python3

import argparse
import json
import re
import subprocess
import sys


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


def normalize_text(value):

    value = (
        value
        or ""
    ).lower()

    value = re.sub(
        r"[^a-z0-9]+",
        " ",
        value,
    )

    return re.sub(
        r"\s+",
        " ",
        value,
    ).strip()


def extract_cap_refs(question):

    refs = re.findall(
        r"\bcap\.?\s*"
        r"([0-9]+[A-Za-z]?)\b",
        question or "",
        flags=re.I,
    )

    return sorted({
        ref.upper()
        for ref in refs
    })


def load_documents():

    rows = psql("""
SELECT json_build_object(
    'id',
        id,
    'title',
        title,
    'source_file_id',
        source_file_id
)::text

FROM documents

WHERE
    title IS NOT NULL

ORDER BY
    id;
""")


    return [
        json.loads(
            row
        )
        for row in rows
    ]


def cap_from_title(title):

    m = re.search(
        r"\(Cap\.\s*"
        r"([0-9]+[A-Za-z]?)"
        r"\)\s*$",
        title or "",
        flags=re.I,
    )

    if not m:
        return None

    return m.group(1).upper()


def title_alias(title):

    return re.sub(
        r"\s*\(Cap\.\s*"
        r"[0-9]+[A-Za-z]?"
        r"\)\s*$",
        "",
        title or "",
        flags=re.I,
    ).strip()


def resolve_document_scope(
    question,
):

    documents = (
        load_documents()
    )

    raw_caps = (
        extract_cap_refs(
            question
        )
    )

    normalized_question = (
        normalize_text(
            question
        )
    )


    matches = {}


    # ========================================================
    # 1. Explicit Cap references in RAW user question
    # ========================================================

    for cap in raw_caps:

        candidates = [
            doc
            for doc in documents
            if cap_from_title(
                doc.get(
                    "title"
                )
            ) == cap
        ]


        for doc in candidates:

            matches[
                int(
                    doc[
                        "id"
                    ]
                )
            ] = {
                **doc,
                "match_modes":
                    {
                        "cap-reference"
                    },
            }


    # ========================================================
    # 2. Exact official-title alias appearing in RAW question
    #
    # Example:
    #
    #   DB:
    #   Gas Safety Ordinance (Cap. 51)
    #
    #   Alias:
    #   Gas Safety Ordinance
    #
    # We deliberately do NOT inspect LLM-generated
    # english_query here.
    # ========================================================

    for doc in documents:

        alias = title_alias(
            doc.get(
                "title"
            )
        )

        normalized_alias = (
            normalize_text(
                alias
            )
        )


        # Avoid accidental matching of very short titles.
        if len(
            normalized_alias
        ) < 8:

            continue


        pattern = (
            r"(?:^|\s)"
            + re.escape(
                normalized_alias
            )
            + r"(?:$|\s)"
        )


        if not re.search(
            pattern,
            normalized_question,
        ):

            continue


        doc_id = int(
            doc[
                "id"
            ]
        )


        if doc_id in matches:

            matches[
                doc_id
            ][
                "match_modes"
            ].add(
                "official-title"
            )

        else:

            matches[
                doc_id
            ] = {
                **doc,
                "match_modes":
                    {
                        "official-title"
                    },
            }


    matched = list(
        matches.values()
    )


    # Same legal document may theoretically appear as more
    # than one DB row/version. Group conservatively by title.
    titles = {}


    for item in matched:

        title = item[
            "title"
        ]

        if title not in titles:

            titles[
                title
            ] = {
                "title":
                    title,

                "document_ids":
                    [],

                "source_file_ids":
                    [],

                "match_modes":
                    set(),
            }


        titles[
            title
        ][
            "document_ids"
        ].append(
            int(
                item[
                    "id"
                ]
            )
        )


        if item.get(
            "source_file_id"
        ):

            titles[
                title
            ][
                "source_file_ids"
            ].append(
                item[
                    "source_file_id"
                ]
            )


        titles[
            title
        ][
            "match_modes"
        ].update(
            item[
                "match_modes"
            ]
        )


    grouped = []


    for item in titles.values():

        grouped.append({
            **item,
            "match_modes":
                sorted(
                    item[
                        "match_modes"
                    ]
                ),
        })


    grouped.sort(
        key=lambda x:
            x["title"]
    )


    if len(grouped) == 1:

        selected = grouped[0]

        return {
            "status":
                "resolved",

            "document_title":
                selected[
                    "title"
                ],

            "match_modes":
                selected[
                    "match_modes"
                ],

            "raw_cap_refs":
                raw_caps,

            "candidates":
                grouped,
        }


    if len(grouped) > 1:

        return {
            "status":
                "multiple-documents",

            "document_title":
                None,

            "raw_cap_refs":
                raw_caps,

            "candidates":
                grouped,
        }


    return {
        "status":
            "unresolved",

        "document_title":
            None,

        "raw_cap_refs":
            raw_caps,

        "candidates":
            [],
    }


def main():

    parser = (
        argparse.ArgumentParser()
    )

    parser.add_argument(
        "question",
    )

    args = parser.parse_args()


    print(
        json.dumps(
            resolve_document_scope(
                args.question
            ),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
