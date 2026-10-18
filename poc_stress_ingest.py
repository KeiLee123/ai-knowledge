import json
import subprocess
import urllib.request

DB_CONTAINER = "ai-knowledge-db-jiyckdrlappwgimwebnzxwmr"
EMBED_URL = "http://127.0.0.1:8088/embed"
DOC_TITLE = "POC - Building Surveying Stress Test"

chunks = [
    (
        "concrete-spalling",
        "Concrete spalling is the breaking away or detachment of concrete cover. "
        "A common cause is corrosion of embedded reinforcement, where corrosion products "
        "expand and generate tensile stresses in the surrounding concrete."
    ),
    (
        "reinforcement-corrosion",
        "Reinforcement corrosion is an electrochemical deterioration process affecting steel "
        "embedded in concrete. Loss of passivation may allow corrosion to develop when moisture "
        "and oxygen are available."
    ),
    (
        "carbonation",
        "Carbonation occurs when atmospheric carbon dioxide penetrates concrete and reacts with "
        "alkaline constituents. The resulting reduction in alkalinity can depassivate embedded "
        "reinforcement when the carbonation front reaches the steel."
    ),
    (
        "chloride-attack",
        "Chloride ions can penetrate concrete and locally break down the passive protective layer "
        "around reinforcement. Sufficient chloride concentration at the reinforcement may initiate "
        "pitting corrosion even where the concrete remains alkaline."
    ),
    (
        "concrete-delamination",
        "Concrete delamination is separation of a layer of concrete from the underlying material. "
        "It may occur above corroding reinforcement before the detached concrete becomes visibly spalled."
    ),
    (
        "cover-depth",
        "Concrete cover provides physical and environmental protection to reinforcement. "
        "Insufficient cover can reduce resistance to carbonation, chloride ingress, fire exposure "
        "and other deterioration mechanisms."
    ),
    (
        "half-cell-potential",
        "Half-cell potential measurement is an electrochemical survey technique used to assess "
        "the probability of active reinforcement corrosion. It does not directly measure the amount "
        "of steel section loss."
    ),
    (
        "crack-repair",
        "Concrete crack repair should consider whether the crack is active or dormant, its width, "
        "cause and structural significance. Repair techniques may include resin injection, routing "
        "and sealing, or other appropriate treatments."
    ),
    (
        "roof-leakage",
        "Roof leakage may result from failed waterproofing, defective joints, deteriorated sealant, "
        "poor detailing, penetrations or inadequate drainage falls that permit water accumulation."
    ),
    (
        "waterproofing-membrane",
        "A waterproofing membrane forms a barrier intended to prevent water penetration through a "
        "roof or other building element. Damage, ageing, poor laps or defective detailing may impair performance."
    ),
    (
        "movement-joint",
        "Movement joints accommodate dimensional changes and relative movement between parts of a building. "
        "Failed joint sealants or damaged joint systems can permit water penetration and local deterioration."
    ),
    (
        "fire-safety",
        "Means of escape should remain clear and unobstructed so occupants can evacuate safely during "
        "an emergency. Inspection should identify obstructions or alterations that impair escape routes."
    ),
]

def psql(sql):
    return subprocess.check_output([
        "docker", "exec", "-i", DB_CONTAINER,
        "psql",
        "-U", "ai_knowledge",
        "-d", "ai_knowledge",
        "-qAt",
        "-v", "ON_ERROR_STOP=1",
        "-c", sql
    ], text=True).strip()

def quote(value):
    return value.replace("'", "''")

# Find or create benchmark document
doc_id = psql(
    f"SELECT id FROM documents "
    f"WHERE title='{quote(DOC_TITLE)}' "
    f"ORDER BY id LIMIT 1;"
)

if not doc_id:
    doc_id = psql(f"""
        INSERT INTO documents (
            title,
            domain,
            topic,
            document_type,
            authority,
            jurisdiction,
            source_type,
            language,
            metadata
        )
        VALUES (
            '{quote(DOC_TITLE)}',
            'building-surveying',
            'retrieval-stress-test',
            'test',
            'internal',
            'HK',
            'manual',
            'en',
            '{{"synthetic":true,"benchmark":"stress-v1"}}'::jsonb
        )
        RETURNING id;
    """)

doc_id = int(doc_id)
print(f"Document ID: {doc_id}")

for chunk_index, (topic, content) in enumerate(chunks):

    metadata = json.dumps({
        "topic": topic,
        "synthetic": True,
        "benchmark": "stress-v1"
    })

    chunk_id = psql(f"""
        INSERT INTO chunks (
            document_id,
            chunk_index,
            content,
            metadata
        )
        VALUES (
            {doc_id},
            {chunk_index},
            '{quote(content)}',
            '{quote(metadata)}'::jsonb
        )
        ON CONFLICT (document_id, chunk_index)
        DO UPDATE SET
            content = EXCLUDED.content,
            metadata = EXCLUDED.metadata
        RETURNING id;
    """)

    chunk_id = int(chunk_id)

    payload = json.dumps({
        "inputs": "passage: " + content
    }).encode("utf-8")

    request = urllib.request.Request(
        EMBED_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    with urllib.request.urlopen(request) as response:
        vector = json.loads(
            response.read().decode("utf-8")
        )[0]

    if len(vector) != 384:
        raise RuntimeError(
            f"{topic}: expected 384 dimensions, got {len(vector)}"
        )

    vector_literal = "[" + ",".join(str(x) for x in vector) + "]"

    psql(f"""
        INSERT INTO embeddings (
            chunk_id,
            provider,
            model,
            dimensions,
            embedding
        )
        VALUES (
            {chunk_id},
            'local',
            'multilingual-e5-small',
            384,
            '{vector_literal}'::vector
        )
        ON CONFLICT (chunk_id, provider, model)
        DO UPDATE SET
            dimensions = EXCLUDED.dimensions,
            embedding = EXCLUDED.embedding,
            created_at = NOW();
    """)

    print(
        f"✓ {chunk_index:02d} "
        f"{topic:25s} "
        f"chunk_id={chunk_id}"
    )

print()
print(f"Completed: {len(chunks)} stress-test chunks embedded.")
