import argparse
import json
import subprocess
import urllib.request
from collections import defaultdict

DB_CONTAINER = "ai-knowledge-db-jiyckdrlappwgimwebnzxwmr"
EMBED_URL = "http://127.0.0.1:8088/embed"

parser = argparse.ArgumentParser()
parser.add_argument("--query", required=True)
parser.add_argument("--english-query", required=True)
parser.add_argument("--limit", type=int, default=5)

args = parser.parse_args()


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

    return vector


def vector_search(query, limit=10):
    vector = embed(query)
    v = "[" + ",".join(str(x) for x in vector) + "]"

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
                    ('{v}'::vector(384))
                )
            )::numeric,
            6
        ),
        c.content
    FROM embeddings e
    JOIN chunks c ON c.id = e.chunk_id
    JOIN documents d ON d.id = c.document_id
    WHERE
        e.provider='local'
        AND e.model='multilingual-e5-small'
        AND d.title='POC - Building Surveying Stress Test'
    ORDER BY
        (e.embedding::vector(384))
        <=>
        ('{v}'::vector(384))
    LIMIT {limit};
    """

    output = subprocess.check_output([
        "docker", "exec", "-i", DB_CONTAINER,
        "psql",
        "-U", "ai_knowledge",
        "-d", "ai_knowledge",
        "-At",
        "-F", "\t",
        "-c", sql
    ], text=True)

    rows = []

    for line in output.strip().splitlines():
        if not line:
            continue

        chunk_id, topic, score, content = line.split("\t", 3)

        rows.append({
            "id": int(chunk_id),
            "topic": topic,
            "score": float(score),
            "content": content
        })

    return rows


# Original-language search
original_results = vector_search(args.query)

# English normalized search
english_results = vector_search(args.english_query)

# Reciprocal Rank Fusion
scores = defaultdict(float)
records = {}

# Give English retrieval more weight
for rank, item in enumerate(english_results, 1):
    scores[item["id"]] += 1.5 / (60 + rank)
    records[item["id"]] = item

for rank, item in enumerate(original_results, 1):
    scores[item["id"]] += 1.0 / (60 + rank)
    records[item["id"]] = item


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
print("FUSED RESULTS:")
print()

for rank, (chunk_id, rrf_score) in enumerate(
    ranked[:args.limit],
    1
):
    item = records[chunk_id]

    print(
        f"{rank}. "
        f"{item['topic'] or '(no topic)'} "
        f"[chunk={chunk_id}] "
        f"RRF={rrf_score:.6f}"
    )

    print("   ", item["content"][:180])
    print()
