import json
import subprocess
import urllib.request

DB_CONTAINER = "ai-knowledge-db-jiyckdrlappwgimwebnzxwmr"
EMBED_URL = "http://127.0.0.1:8088/embed"
DOC_TITLE = "POC - Building Surveying Stress Test"

tests = [
    (
        "碳化點解會增加鋼筋鏽蝕風險？",
        "carbonation"
    ),
    (
        "氯離子去到鋼筋表面之後，點解可以引起局部點蝕？",
        "chloride-attack"
    ),
    (
        "Half-cell potential test 可以直接量度鋼筋截面損失幾多嗎？",
        "half-cell-potential"
    ),
    (
        "石屎未真正爆落之前，如果保護層已經同底層分離，這種缺陷叫甚麼？",
        "concrete-delamination"
    ),
    (
        "鋼筋保護層太薄，對碳化、氯離子滲入及耐火性能有甚麼影響？",
        "cover-depth"
    ),
    (
        "鋼筋鏽蝕產物膨脹，點解會造成石屎保護層剝落？",
        "concrete-spalling"
    ),
    (
        "伸縮或移動接縫的 sealant 失效，點解可能造成滲水？",
        "movement-joint"
    ),
    (
        "屋面防水膜老化、搭接位或細部處理失效，會造成甚麼問題？",
        "waterproofing-membrane"
    ),
    (
        "混凝土裂縫維修之前，為甚麼要先判斷裂縫是否仍然活動？",
        "crack-repair"
    ),
    (
        "鋼筋失去鈍化保護之後，在有水和氧氣的情況下會發生甚麼？",
        "reinforcement-corrosion"
    ),
]

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
        vector = json.loads(response.read().decode("utf-8"))[0]

    if len(vector) != 384:
        raise RuntimeError(f"Unexpected vector size: {len(vector)}")

    return vector


def search(vector, limit=3):
    vector_literal = "[" + ",".join(str(x) for x in vector) + "]"

    sql = f"""
    SELECT
        c.metadata->>'topic' AS topic,
        ROUND(
            (
                1 - (
                    (e.embedding::vector(384))
                    <=>
                    ('{vector_literal}'::vector(384))
                )
            )::numeric,
            4
        ) AS similarity
    FROM embeddings e
    JOIN chunks c ON c.id = e.chunk_id
    JOIN documents d ON d.id = c.document_id
    WHERE
        e.provider = 'local'
        AND e.model = 'multilingual-e5-small'
        AND d.title = '{DOC_TITLE}'
    ORDER BY
        (e.embedding::vector(384))
        <=>
        ('{vector_literal}'::vector(384))
    LIMIT {limit};
    """

    output = subprocess.check_output([
        "docker", "exec", "-i", DB_CONTAINER,
        "psql",
        "-U", "ai_knowledge",
        "-d", "ai_knowledge",
        "-At",
        "-F", "|",
        "-c", sql
    ], text=True)

    rows = []

    for line in output.strip().splitlines():
        if not line.strip():
            continue

        topic, similarity = line.split("|")
        rows.append((topic, float(similarity)))

    return rows


top1_correct = 0
top3_correct = 0

for number, (question, expected) in enumerate(tests, 1):

    vector = embed(question)
    results = search(vector, 3)

    top_topics = [r[0] for r in results]

    top1_pass = len(top_topics) > 0 and top_topics[0] == expected
    top3_pass = expected in top_topics

    top1_correct += int(top1_pass)
    top3_correct += int(top3_pass)

    print("=" * 78)
    print(f"TEST {number}")
    print("QUESTION:", question)
    print("EXPECTED:", expected)
    print(
        "TOP-1:",
        "PASS ✅" if top1_pass else "FAIL ❌"
    )
    print(
        "TOP-3:",
        "PASS ✅" if top3_pass else "FAIL ❌"
    )
    print()

    for rank, (topic, similarity) in enumerate(results, 1):
        marker = " ← expected" if topic == expected else ""
        print(
            f"{rank}. {topic:25s} "
            f"similarity={similarity:.4f}"
            f"{marker}"
        )

print()
print("=" * 78)
print("FINAL RESULT")
print(
    f"Top-1 accuracy: "
    f"{top1_correct}/{len(tests)} "
    f"= {top1_correct / len(tests) * 100:.1f}%"
)
print(
    f"Top-3 accuracy: "
    f"{top3_correct}/{len(tests)} "
    f"= {top3_correct / len(tests) * 100:.1f}%"
)
