import argparse
import json
import subprocess
import urllib.request
from collections import defaultdict

DB_CONTAINER = "ai-knowledge-db-jiyckdrlappwgimwebnzxwmr"
EMBED_URL = "http://127.0.0.1:8088/embed"
DOC_TITLE = "POC - Building Surveying Stress Test"

parser = argparse.ArgumentParser()
parser.add_argument("--query", required=True)
parser.add_argument("--english-query", required=True)
parser.add_argument("--terms", required=True,
                    help="Comma-separated English technical terms")
parser.add_argument("--limit", type=int, default=5)

args = parser.parse_args()

terms = [
    t.strip().lower()
    for t in args.terms.split(",")
    if t.strip()
]


def sql_quote(text):
    return text.replace("'", "''")


def embed(text):
    payload = json.dumps(
        {"inputs": "query: " + text},
        ensure_ascii=False
    ).encode("utf-8")

    req = urllib.request.Request(
        EMBED_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    with urllib.request.urlopen(req) as response:
        vector = json.loads(
            response.read().decode("utf-8")
        )[0]

    if len(vector) != 384:
        raise RuntimeError(
            f"Expected 384 dimensions, got {len(vector)}"
        )

    return vector


def run_sql(sql):
    output = subprocess.check_output([
        "docker", "exec", "-i", DB_CONTAINER,
        "psql",
        "-U", "ai_knowledge",
        "-d", "ai_knowledge",
        "-At",
        "-F", "\t",
        "-c", sql
    ], text=True)

    return [
        line
        for line in output.strip().splitlines()
        if line.strip()
    ]


def vector_search(query, limit=20):
    vector = embed(query)

    vector_literal = (
        "[" + ",".join(str(x) for x in vector) + "]"
    )

    sql = f"""
    SELECT
        c.id,
        COALESCE(c.metadata->>'topic',''),
        ROUND(
            (
                1 -
                (
                    (e.embedding::vector(384))
                    <=>
                    ('{vector_literal}'::vector(384))
                )
            )::numeric,
            6
        ),
        c.content
    FROM embeddings e
    JOIN chunks c
        ON c.id = e.chunk_id
    JOIN documents d
        ON d.id = c.document_id
    WHERE
        e.provider = 'local'
        AND e.model = 'multilingual-e5-small'
        AND d.title = '{sql_quote(DOC_TITLE)}'
    ORDER BY
        (e.embedding::vector(384))
        <=>
        ('{vector_literal}'::vector(384))
    LIMIT {limit};
    """

    rows = []

    for line in run_sql(sql):
        chunk_id, topic, similarity, content = \
            line.split("\t", 3)

        rows.append({
            "id": int(chunk_id),
            "topic": topic,
            "similarity": float(similarity),
            "content": content
        })

    return rows


def lexical_search(terms, limit=20):
    if not terms:
        return []

    hit_parts = []
    where_parts = []

    for term in terms:
        q = sql_quote(term)

        hit_parts.append(
            f"""
            CASE
                WHEN POSITION(
                    '{q}' IN LOWER(c.content)
                ) > 0
                THEN 1
                ELSE 0
            END
            """
        )

        where_parts.append(
            f"""
            POSITION(
                '{q}' IN LOWER(c.content)
            ) > 0
            """
        )

    hit_expression = " + ".join(hit_parts)
    where_expression = " OR ".join(where_parts)

    sql = f"""
    SELECT
        c.id,
        COALESCE(c.metadata->>'topic',''),
        ({hit_expression}) AS hits,
        c.content
    FROM chunks c
    JOIN documents d
        ON d.id = c.document_id
    WHERE
        d.title = '{sql_quote(DOC_TITLE)}'
        AND ({where_expression})
    ORDER BY
        hits DESC,
        c.id
    LIMIT {limit};
    """

    rows = []

    for line in run_sql(sql):
        chunk_id, topic, hits, content = \
            line.split("\t", 3)

        rows.append({
            "id": int(chunk_id),
            "topic": topic,
            "hits": int(hits),
            "content": content
        })

    return rows


english_results = vector_search(args.english_query)
original_results = vector_search(args.query)
lexical_results = lexical_search(terms)

scores = defaultdict(float)
records = {}
channels = defaultdict(dict)

# English semantic retrieval = primary semantic signal
for rank, item in enumerate(english_results, 1):
    scores[item["id"]] += 2.0 / (60 + rank)
    records[item["id"]] = item
    channels[item["id"]]["english"] = rank

# Original-language retrieval = weak supplementary signal
for rank, item in enumerate(original_results, 1):
    scores[item["id"]] += 0.2 / (60 + rank)
    records[item["id"]] = item
    channels[item["id"]]["original"] = rank

# Technical lexical terms = strong precision signal
for rank, item in enumerate(lexical_results, 1):
    scores[item["id"]] += 2.5 / (60 + rank)

    if item["id"] not in records:
        records[item["id"]] = item

    channels[item["id"]]["lexical"] = rank
    channels[item["id"]]["hits"] = item["hits"]


ranked = sorted(
    scores.items(),
    key=lambda x: x[1],
    reverse=True
)

print()
print("ORIGINAL QUERY:")
print(args.query)

print()
print("NORMALIZED ENGLISH QUERY:")
print(args.english_query)

print()
print("TECHNICAL TERMS:")
print(", ".join(terms))

print()
print("HYBRID RESULTS:")
print()

for rank, (chunk_id, score) in enumerate(
    ranked[:args.limit],
    1
):
    item = records[chunk_id]
    ch = channels[chunk_id]

    channel_info = []

    if "english" in ch:
        channel_info.append(
            f"E#{ch['english']}"
        )

    if "original" in ch:
        channel_info.append(
            f"O#{ch['original']}"
        )

    if "lexical" in ch:
        channel_info.append(
            f"L#{ch['lexical']}"
            f"/hits={ch['hits']}"
        )

    print(
        f"{rank}. "
        f"{item['topic'] or '(no topic)'} "
        f"[chunk={chunk_id}] "
        f"score={score:.6f}"
    )

    print(
        "   channels:",
        ", ".join(channel_info)
    )

    print(
        "   ",
        item["content"][:200]
    )

    print()
