#!/usr/bin/env python3

import argparse
import json
import subprocess
from pathlib import Path


LOCATOR_VERSION = "sr-b-1"
SCHEMA_VERSION = "source-locator-v1"

DEFAULT_DB_CONTAINER = (
    "ai-knowledge-db-jiyckdrlappwgimwebnzxwmr"
)


def run_db_query(
    sql: str,
    db_container: str,
) -> str:
    result = subprocess.run(
        [
            "docker",
            "exec",
            "-i",
            db_container,
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
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        raise RuntimeError(
            result.stderr.strip()
            or result.stdout.strip()
            or "Database read-only query failed"
        )

    return result.stdout.strip()


def locator_label(
    title: str,
    page_start: int | None,
    page_end: int | None,
) -> str:
    title = (
        title.strip()
        or "Unknown document"
    )

    if page_start is None:
        return title

    if (
        page_end is None
        or page_end == page_start
    ):
        return (
            f"{title} — p.{page_start}"
        )

    return (
        f"{title} — "
        f"pp.{page_start}-{page_end}"
    )


def resolve_chunk_locators(
    chunk_ids: list[int],
    db_container: str = DEFAULT_DB_CONTAINER,
) -> dict:
    ordered_ids = []

    seen = set()

    for value in chunk_ids:
        chunk_id = int(value)

        if chunk_id <= 0:
            raise ValueError(
                "chunk IDs must be positive"
            )

        if chunk_id in seen:
            continue

        seen.add(chunk_id)
        ordered_ids.append(chunk_id)

    if not ordered_ids:
        raise ValueError(
            "At least one chunk ID is required"
        )

    values_sql = ",\n".join(
        f"({chunk_id}::bigint, {index})"
        for index, chunk_id
        in enumerate(
            ordered_ids,
            1,
        )
    )

    sql = f"""
    WITH requested(
        chunk_id,
        ordinal
    ) AS (
        VALUES
        {values_sql}
    )
    SELECT
        json_build_object(
            'chunk_id',
                c.id,
            'document_id',
                d.id,
            'document_title',
                COALESCE(d.title, ''),
            'document_checksum',
                COALESCE(
                    d.checksum_sha256,
                    ''
                ),
            'domain',
                COALESCE(d.domain, ''),
            'topic',
                COALESCE(d.topic, ''),
            'document_type',
                COALESCE(
                    d.document_type,
                    ''
                ),
            'page_start',
                c.page_start,
            'page_end',
                c.page_end,
            'source_type',
                COALESCE(
                    d.source_type,
                    ''
                ),
            'source_file_id',
                COALESCE(
                    d.source_file_id,
                    ''
                ),
            'source_url',
                COALESCE(
                    d.source_url,
                    ''
                ),
            'source_filename',
                COALESCE(
                    d.metadata
                        ->>'source_filename',
                    ''
                ),
            'source_path',
                COALESCE(
                    d.metadata
                        ->>'source_path',
                    ''
                ),
            'drive_modified_time',
                COALESCE(
                    d.metadata
                        ->>'drive_modified_time',
                    ''
                ),
            'ingestion_version',
                COALESCE(
                    d.metadata
                        ->>'ingestion_version',
                    c.metadata
                        ->>'ingestion_version',
                    ''
                ),
            'evidence_origin',
                COALESCE(
                    c.metadata
                        ->>'evidence_origin',
                    ''
                ),
            'retrieval_role',
                COALESCE(
                    c.metadata
                        ->>'retrieval_role',
                    ''
                )
        )::text
    FROM requested r
    JOIN chunks c
      ON c.id = r.chunk_id
    JOIN documents d
      ON d.id = c.document_id
    ORDER BY r.ordinal;
    """

    raw = run_db_query(
        sql,
        db_container,
    )

    locators = []

    if raw:
        for line in raw.splitlines():
            if not line.strip():
                continue

            item = json.loads(line)

            item["locator_label"] = (
                locator_label(
                    item.get(
                        "document_title",
                        "",
                    ),
                    item.get(
                        "page_start"
                    ),
                    item.get(
                        "page_end"
                    ),
                )
            )

            item[
                "source_url_available"
            ] = bool(
                item.get(
                    "source_url"
                )
            )

            item[
                "manual_source_locator_available"
            ] = any([
                bool(
                    item.get(
                        "source_filename"
                    )
                ),
                bool(
                    item.get(
                        "source_path"
                    )
                ),
                bool(
                    item.get(
                        "document_title"
                    )
                ),
            ])

            locators.append(
                item
            )

    resolved_ids = {
        int(
            item["chunk_id"]
        )
        for item in locators
    }

    missing_ids = [
        chunk_id
        for chunk_id in ordered_ids
        if chunk_id
        not in resolved_ids
    ]

    return {
        "schema_version":
            SCHEMA_VERSION,
        "locator_version":
            LOCATOR_VERSION,
        "read_only":
            True,
        "database_write_performed":
            False,
        "requested_chunk_ids":
            ordered_ids,
        "resolved_count":
            len(locators),
        "missing_chunk_ids":
            missing_ids,
        "locators":
            locators,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Resolve Knowledge Brain chunk IDs "
            "to source document/page provenance. "
            "Read-only; performs no database writes."
        )
    )

    parser.add_argument(
        "--chunk-id",
        action="append",
        required=True,
        type=int,
        help=(
            "Chunk ID to resolve. "
            "Repeat for multiple chunks."
        ),
    )

    parser.add_argument(
        "--db-container",
        default=
            DEFAULT_DB_CONTAINER,
    )

    parser.add_argument(
        "--output",
        help=(
            "Optional JSON output file. "
            "Without this option JSON is "
            "printed to stdout."
        ),
    )

    parser.add_argument(
        "--compact",
        action="store_true",
        help="Emit compact JSON",
    )

    args = parser.parse_args()

    try:
        payload = (
            resolve_chunk_locators(
                args.chunk_id,
                args.db_container,
            )
        )

    except Exception as exc:
        raise SystemExit(
            "Source locator failed: "
            f"{type(exc).__name__}: "
            f"{exc}"
        ) from exc

    if args.compact:
        output = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
        )

    else:
        output = json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
        )

    if args.output:
        path = (
            Path(args.output)
            .expanduser()
            .resolve()
        )

        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        path.write_text(
            output + "\n",
            encoding="utf-8",
        )

        print(path)

    else:
        print(output)


if __name__ == "__main__":
    main()
