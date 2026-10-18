import json
import subprocess
import urllib.request

DB_CONTAINER = "ai-knowledge-db-jiyckdrlappwgimwebnzxwmr"
EMBED_URL = "http://127.0.0.1:8088/embed"
DOC_TITLE = "POC - Building Surveying Stress Test"

tests = [
    (
        "Why does carbonation increase the risk of reinforcement corrosion?",
        "carbonation"
    ),
    (
        "How can chloride ions reaching reinforcement cause localized pitting corrosion?",
        "chloride-attack"
    ),
    (
        "Can a half-cell potential test directly measure reinforcement section loss?",
        "half-cell-potential"
    ),
    (
        "What is the defect called when the concrete cover separates from the underlying concrete before it visibly falls away?",
        "concrete-delamination"
    ),
    (
        "How does insufficient concrete cover affect resistance to carbonation, chloride ingress and fire?",
        "cover-depth"
    ),
    (
        "Why does expansion of corrosion products cause concrete cover to break away?",
        "concrete-spalling"
    ),
    (
        "Why can failure of sealant at a movement joint cause water penetration?",
        "movement-joint"
    ),
    (
        "What problem can result from an aged roof waterproofing membrane, defective laps or poor detailing?",
        "waterproofing-membrane"
    ),
    (
        "Why should we determine whether a concrete crack is active before selecting a repair method?",
        "crack-repair"
    ),
    (
        "What happens after reinforcement loses its passive protection when moisture and oxygen are present?",
        "reinforcement-corrosion"
    ),
]

def embed(text):
    payload = json.dumps(
        {"inputs": "query: " + text}
    ).encode("utf-8")

    req = urllib.request.Request(
        EMBED_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    with urllib.request.urlopen(req) as response:
        return json.loads(response.read().decode("utf-8"))[0]


def search(vector):
    v = "[" + ",".join(str(x) for x in vector) + "]"

    sql = f"""
    SELECT
        c.metadata->>'topic',
        ROUND(
            (
                1 - (
                    (e.embedding::vector(384))
                    <=>
                    ('{v}'::vector(384))
                )
            )::numeric,
            4
        )
    FROM embeddings e
    JOIN chunks c ON c.id = e.chunk_id
    JOIN documents d ON d.id = c.document_id
    WHERE
        e.provider='local'
        AND e.model='multilingual-e5-small'
        AND d.title='{DOC_TITLE}'
    ORDER BY
        (e.embedding::vector(384))
        <=>
        ('{v}'::vector(384))
    LIMIT 3;
    """

    result = subprocess.check_output([
        "docker", "exec", "-i", DB_CONTAINER,
        "psql",
        "-U", "ai_knowledge",
        "-d", "ai_knowledge",
        "-At",
        "-F", "|",
        "-c", sql
    ], text=True)

    return [
        line.split("|")
        for line in result.strip().splitlines()
        if line.strip()
    ]


top1 = 0
top3 = 0

for i, (question, expected) in enumerate(tests, 1):
    results = search(embed(question))
    topics = [r[0] for r in results]

    p1 = topics[0] == expected
    p3 = expected in topics

    top1 += int(p1)
    top3 += int(p3)

    print("=" * 75)
    print(f"TEST {i}")
    print(question)
    print("EXPECTED:", expected)
    print("TOP-1:", "PASS" if p1 else "FAIL")
    print("TOP-3:", "PASS" if p3 else "FAIL")

    for rank, (topic, score) in enumerate(results, 1):
        print(f"{rank}. {topic:25s} {score}")

print()
print("=" * 75)
print(f"Top-1 accuracy: {top1}/10 = {top1 * 10}%")
print(f"Top-3 accuracy: {top3}/10 = {top3 * 10}%")
