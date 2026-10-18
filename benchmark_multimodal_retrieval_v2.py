#!/usr/bin/env python3

import argparse
import json
import math
import urllib.request
from pathlib import Path

from build_multimodal_chunks_v2 import (
    DEFAULT_OVERLAP_CHARS,
    DEFAULT_TARGET_CHARS,
    normalize_text,
    split_text,
)


BENCHMARK_VERSION = "phase-d2-1"
DEFAULT_EMBED_URL = "http://127.0.0.1:8088/embed"
EXPECTED_DIMENSIONS = 384


def load_json(path: Path):
    return json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )


def embed(
    text: str,
    prefix: str,
    embed_url: str,
) -> list[float]:
    payload = json.dumps(
        {
            "inputs":
                prefix + text
        },
        ensure_ascii=False,
    ).encode("utf-8")

    req = urllib.request.Request(
        embed_url,
        data=payload,
        headers={
            "Content-Type":
                "application/json"
        },
        method="POST",
    )

    with urllib.request.urlopen(
        req,
        timeout=60,
    ) as response:
        result = json.loads(
            response.read().decode(
                "utf-8"
            )
        )

    vector = result[0]

    if len(vector) != EXPECTED_DIMENSIONS:
        raise RuntimeError(
            "Unexpected embedding dimension: "
            f"{len(vector)}"
        )

    return [
        float(value)
        for value in vector
    ]


def cosine_similarity(
    a: list[float],
    b: list[float],
) -> float:
    dot = sum(
        x * y
        for x, y in zip(a, b)
    )

    norm_a = math.sqrt(
        sum(x * x for x in a)
    )

    norm_b = math.sqrt(
        sum(x * x for x in b)
    )

    if not norm_a or not norm_b:
        return 0.0

    return dot / (
        norm_a * norm_b
    )


def build_native_baseline(
    manifest: dict,
    target_chars: int,
    overlap_chars: int,
) -> list[dict]:
    chunks = []

    for unit in (
        manifest.get("units")
        or []
    ):
        if (
            unit.get("unit_type")
            != "page"
        ):
            continue

        page = unit.get(
            "page_number"
        )

        if not isinstance(
            page,
            int,
        ):
            continue

        text = normalize_text(
            unit.get("text")
            or ""
        )

        if not text:
            continue

        for local_index, content in enumerate(
            split_text(
                text,
                target_chars=
                    target_chars,
                overlap_chars=
                    overlap_chars,
            )
        ):
            chunks.append({
                "page":
                    page,
                "origin":
                    "native_text",
                "tier":
                    "primary",
                "local_chunk_index":
                    local_index,
                "content":
                    content,
            })

    return chunks


def load_multimodal_chunks(
    chunks_payload: dict,
) -> list[dict]:
    chunks = []

    for item in (
        chunks_payload.get(
            "chunks"
        )
        or []
    ):
        metadata = (
            item.get("metadata")
            or {}
        )

        page = item.get(
            "page_start"
        )

        content = normalize_text(
            item.get("content")
            or ""
        )

        if (
            not isinstance(page, int)
            or not content
        ):
            continue

        chunks.append({
            "page":
                page,
            "origin":
                metadata.get(
                    "evidence_origin"
                )
                or "unknown",
            "tier":
                metadata.get(
                    "evidence_tier"
                )
                or "unknown",
            "local_chunk_index":
                metadata.get(
                    "local_chunk_index"
                ),
            "content":
                content,
        })

    return chunks


def embed_corpus(
    chunks: list[dict],
    embed_url: str,
) -> list[dict]:
    cache = {}
    embedded = []

    for chunk in chunks:
        content = chunk["content"]

        if content not in cache:
            cache[content] = embed(
                content,
                prefix="passage: ",
                embed_url=embed_url,
            )

        enriched = dict(
            chunk
        )

        enriched["embedding"] = (
            cache[content]
        )

        embedded.append(
            enriched
        )

    return embedded


def rank_pages(
    query: str,
    embedded_chunks: list[dict],
    embed_url: str,
) -> list[dict]:
    query_vector = embed(
        query,
        prefix="query: ",
        embed_url=embed_url,
    )

    best_by_page = {}

    for chunk in embedded_chunks:
        score = cosine_similarity(
            query_vector,
            chunk["embedding"],
        )

        page = chunk["page"]

        candidate = {
            "page":
                page,
            "similarity":
                round(score, 6),
            "origin":
                chunk["origin"],
            "tier":
                chunk["tier"],
            "content_preview":
                chunk["content"][
                    :240
                ].replace(
                    "\n",
                    " ",
                ),
        }

        current = (
            best_by_page.get(page)
        )

        if (
            current is None
            or candidate["similarity"]
            > current["similarity"]
        ):
            best_by_page[page] = (
                candidate
            )

    return sorted(
        best_by_page.values(),
        key=lambda item:
            (
                -item[
                    "similarity"
                ],
                item["page"],
            ),
    )


def expected_rank(
    ranking: list[dict],
    expected_pages: list[int],
):
    expected = set(
        expected_pages
    )

    for index, item in enumerate(
        ranking,
        start=1,
    ):
        if item["page"] in expected:
            return index

    return None


def reciprocal_rank(rank):
    if rank is None:
        return 0.0

    return 1.0 / rank


def metrics(
    results: list[dict],
) -> dict:
    if not results:
        return {
            "query_count": 0,
            "hit_at_1": 0.0,
            "hit_at_3": 0.0,
            "mrr": 0.0,
        }

    total = len(results)

    hit1 = sum(
        1
        for item in results
        if (
            item.get("rank")
            is not None
            and item["rank"] <= 1
        )
    )

    hit3 = sum(
        1
        for item in results
        if (
            item.get("rank")
            is not None
            and item["rank"] <= 3
        )
    )

    mrr = sum(
        reciprocal_rank(
            item.get("rank")
        )
        for item in results
    ) / total

    return {
        "query_count":
            total,
        "hit_at_1":
            round(hit1 / total, 4),
        "hit_at_3":
            round(hit3 / total, 4),
        "mrr":
            round(mrr, 4),
    }


def group_metrics(
    results: list[dict],
    side: str,
) -> dict:
    grouped = {}

    categories = sorted({
        item["category"]
        for item in results
    })

    for category in categories:
        scoped = [
            {
                "rank":
                    item[side][
                        "expected_rank"
                    ]
            }
            for item in results
            if (
                item["category"]
                == category
            )
        ]

        grouped[category] = (
            metrics(scoped)
        )

    grouped["overall"] = metrics([
        {
            "rank":
                item[side][
                    "expected_rank"
                ]
        }
        for item in results
    ])

    return grouped


def validate_queries(
    payload,
) -> list[dict]:
    if not isinstance(
        payload,
        list,
    ):
        raise RuntimeError(
            "Queries JSON must be a list"
        )

    seen_ids = set()
    validated = []

    for item in payload:
        if not isinstance(
            item,
            dict,
        ):
            raise RuntimeError(
                "Each benchmark query "
                "must be an object"
            )

        query_id = str(
            item.get("id")
            or ""
        ).strip()

        query = normalize_text(
            item.get("query")
            or ""
        )

        category = str(
            item.get("category")
            or "uncategorized"
        ).strip()

        pages = (
            item.get(
                "expected_pages"
            )
            or []
        )

        if (
            not query_id
            or query_id in seen_ids
        ):
            raise RuntimeError(
                "Query IDs must be "
                "unique and non-empty"
            )

        if not query:
            raise RuntimeError(
                f"Query {query_id} "
                "has no text"
            )

        if (
            not isinstance(pages, list)
            or not pages
            or not all(
                isinstance(page, int)
                and page > 0
                for page in pages
            )
        ):
            raise RuntimeError(
                f"Query {query_id} has "
                "invalid expected_pages"
            )

        seen_ids.add(query_id)

        validated.append({
            "id":
                query_id,
            "category":
                category,
            "query":
                query,
            "expected_pages":
                pages,
        })

    return validated


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Offline page-level retrieval benchmark "
            "comparing native-text baseline with "
            "multimodal retrieval chunks."
        )
    )

    parser.add_argument(
        "manifest",
        help=(
            "Phase A/B/C manifest "
            "for native baseline"
        ),
    )

    parser.add_argument(
        "chunks",
        help=(
            "Phase D1 retrieval-chunks-v2 "
            "JSON"
        ),
    )

    parser.add_argument(
        "queries",
        help=(
            "Benchmark query JSON"
        ),
    )

    parser.add_argument(
        "-o",
        "--output",
        required=True,
        help=(
            "Write benchmark result JSON"
        ),
    )

    parser.add_argument(
        "--embed-url",
        default=DEFAULT_EMBED_URL,
    )

    parser.add_argument(
        "--top-k",
        type=int,
        default=5,
    )

    args = parser.parse_args()

    manifest_path = Path(
        args.manifest
    )

    chunks_path = Path(
        args.chunks
    )

    queries_path = Path(
        args.queries
    )

    output_path = Path(
        args.output
    )

    for path in [
        manifest_path,
        chunks_path,
        queries_path,
    ]:
        if not path.is_file():
            raise SystemExit(
                f"File not found: {path}"
            )

    if args.top_k < 1:
        raise SystemExit(
            "--top-k must be >= 1"
        )

    try:
        manifest = load_json(
            manifest_path
        )

        chunks_payload = load_json(
            chunks_path
        )

        query_payload = load_json(
            queries_path
        )

        queries = validate_queries(
            query_payload
        )

        policy = (
            chunks_payload.get(
                "policy"
            )
            or {}
        )

        target_chars = int(
            policy.get(
                "target_chars"
            )
            or DEFAULT_TARGET_CHARS
        )

        overlap_chars = int(
            policy.get(
                "overlap_chars"
            )
            or DEFAULT_OVERLAP_CHARS
        )

        baseline_chunks = (
            build_native_baseline(
                manifest,
                target_chars=
                    target_chars,
                overlap_chars=
                    overlap_chars,
            )
        )

        multimodal_chunks = (
            load_multimodal_chunks(
                chunks_payload
            )
        )

        baseline_embedded = (
            embed_corpus(
                baseline_chunks,
                args.embed_url,
            )
        )

        multimodal_embedded = (
            embed_corpus(
                multimodal_chunks,
                args.embed_url,
            )
        )

        results = []

        for query_item in queries:
            baseline_ranking = (
                rank_pages(
                    query_item["query"],
                    baseline_embedded,
                    args.embed_url,
                )
            )

            multimodal_ranking = (
                rank_pages(
                    query_item["query"],
                    multimodal_embedded,
                    args.embed_url,
                )
            )

            baseline_rank = (
                expected_rank(
                    baseline_ranking,
                    query_item[
                        "expected_pages"
                    ],
                )
            )

            multimodal_rank = (
                expected_rank(
                    multimodal_ranking,
                    query_item[
                        "expected_pages"
                    ],
                )
            )

            if (
                baseline_rank is None
                and multimodal_rank
                is not None
            ):
                comparison = (
                    "improved"
                )

            elif (
                baseline_rank
                is not None
                and multimodal_rank
                is None
            ):
                comparison = (
                    "regressed"
                )

            elif (
                baseline_rank
                is None
                and multimodal_rank
                is None
            ):
                comparison = "same"

            elif (
                multimodal_rank
                < baseline_rank
            ):
                comparison = (
                    "improved"
                )

            elif (
                multimodal_rank
                > baseline_rank
            ):
                comparison = (
                    "regressed"
                )

            else:
                comparison = "same"

            results.append({
                **query_item,
                "comparison":
                    comparison,
                "baseline": {
                    "expected_rank":
                        baseline_rank,
                    "top_results":
                        baseline_ranking[
                            :args.top_k
                        ],
                },
                "multimodal": {
                    "expected_rank":
                        multimodal_rank,
                    "top_results":
                        multimodal_ranking[
                            :args.top_k
                        ],
                },
            })

        comparison_counts = {
            "improved": sum(
                1
                for item in results
                if (
                    item["comparison"]
                    == "improved"
                )
            ),
            "same": sum(
                1
                for item in results
                if (
                    item["comparison"]
                    == "same"
                )
            ),
            "regressed": sum(
                1
                for item in results
                if (
                    item["comparison"]
                    == "regressed"
                )
            ),
        }

        output = {
            "schema_version":
                "retrieval-benchmark-v2",
            "benchmark_version":
                BENCHMARK_VERSION,
            "embedding": {
                "url":
                    args.embed_url,
                "model_contract":
                    "multilingual-e5-small",
                "dimensions":
                    EXPECTED_DIMENSIONS,
                "query_prefix":
                    "query: ",
                "passage_prefix":
                    "passage: ",
            },
            "corpora": {
                "baseline": {
                    "policy":
                        "native-text-only",
                    "chunk_count":
                        len(
                            baseline_chunks
                        ),
                },
                "multimodal": {
                    "policy":
                        "phase-d1",
                    "chunk_count":
                        len(
                            multimodal_chunks
                        ),
                },
            },
            "comparison_counts":
                comparison_counts,
            "metrics": {
                "baseline":
                    group_metrics(
                        results,
                        "baseline",
                    ),
                "multimodal":
                    group_metrics(
                        results,
                        "multimodal",
                    ),
            },
            "results":
                results,
            "safety": {
                "database_write_performed":
                    False,
                "production_retrieval_modified":
                    False,
            },
        }

    except Exception as exc:
        raise SystemExit(
            "Benchmark failed: "
            f"{type(exc).__name__}: "
            f"{exc}"
        ) from exc

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_path.write_text(
        json.dumps(
            output,
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print(output_path)


if __name__ == "__main__":
    main()
