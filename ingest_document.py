#!/usr/bin/env python3

import argparse
import hashlib
import json
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

DB_CONTAINER = "ai-knowledge-db-jiyckdrlappwgimwebnzxwmr"
EMBED_URL = "http://127.0.0.1:8088/embed"

parser = argparse.ArgumentParser()

parser.add_argument("file")
parser.add_argument("--title", required=True)
parser.add_argument("--domain", required=True)
parser.add_argument("--topic", default="")
parser.add_argument("--document-type", default="reference")
parser.add_argument("--authority", default="")
parser.add_argument("--jurisdiction", default="HK")
parser.add_argument("--language", default="en")
parser.add_argument("--source-url", default="")

args = parser.parse_args()

path = Path(args.file)

if not path.exists():
    raise SystemExit(f"File not found: {path}")


def sql_quote(value):
    return str(value).replace("'", "''")


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


def sha256_file(path):
    h = hashlib.sha256()

    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)

    return h.hexdigest()


def extract_pdf(path):
    try:
        import pymupdf
    except ImportError:
        raise RuntimeError(
            "PyMuPDF is required for PDF ingestion"
        )

    pages = []

    doc = pymupdf.open(path)

    for i, page in enumerate(doc, 1):
        text = page.get_text("text")

        pages.append({
            "page": i,
            "text": text.strip()
        })

    return pages


def extract_docx(path):
    try:
        from docx import Document
    except ImportError:
        raise RuntimeError(
            "python-docx is required for DOCX ingestion"
        )

    doc = Document(path)

    text = "\n".join(
        p.text for p in doc.paragraphs
        if p.text.strip()
    )

    return [{
        "page": None,
        "text": text
    }]


def extract_text(path):
    suffix = path.suffix.lower()

    if suffix == ".pdf":
        return extract_pdf(path)

    if suffix == ".docx":
        return extract_docx(path)

    if suffix in (".txt", ".md"):
        return [{
            "page": None,
            "text": path.read_text(
                encoding="utf-8",
                errors="replace"
            )
        }]

    raise RuntimeError(
        f"Unsupported file type: {suffix}"
    )


def normalize_text(text):
    text = text.replace("\r\n", "\n")
    text = text.replace("\r", "\n")

    text = re.sub(
        r"[ \t]+",
        " ",
        text
    )

    text = re.sub(
        r"\n{3,}",
        "\n\n",
        text
    )

    return text.strip()


def split_chunks(pages, target_chars=1800, overlap_chars=250):

    chunks = []

    for page_data in pages:

        page_no = page_data["page"]
        text = normalize_text(page_data["text"])

        if not text:
            continue

        paragraphs = [
            p.strip()
            for p in re.split(r"\n\s*\n", text)
            if p.strip()
        ]

        current = ""

        for paragraph in paragraphs:

            if (
                current
                and len(current) + len(paragraph) + 2
                > target_chars
            ):
                chunks.append({
                    "content": current.strip(),
                    "page_start": page_no,
                    "page_end": page_no
                })

                overlap = current[-overlap_chars:]

                current = (
                    overlap + "\n\n" + paragraph
                ).strip()

            else:
                if current:
                    current += "\n\n"

                current += paragraph

        if current.strip():
            chunks.append({
                "content": current.strip(),
                "page_start": page_no,
                "page_end": page_no
            })

    return chunks


def embed(text):

    payload = json.dumps({
        "inputs": "passage: " + text
    }).encode("utf-8")

    req = urllib.request.Request(
        EMBED_URL,
        data=payload,
        headers={
            "Content-Type": "application/json"
        },
        method="POST"
    )

    with urllib.request.urlopen(
        req,
        timeout=60
    ) as response:

        vector = json.loads(
            response.read().decode("utf-8")
        )[0]

    if len(vector) != 384:
        raise RuntimeError(
            f"Unexpected vector dimension: {len(vector)}"
        )

    return vector


print("Extracting document...")

pages = extract_text(path)

print(f"Extracted {len(pages)} page/unit(s)")

chunks = split_chunks(pages)

print(f"Created {len(chunks)} chunk(s)")

if not chunks:
    raise SystemExit("No usable text extracted.")

checksum = sha256_file(path)

# Prevent accidental duplicate production ingestion
existing = psql(f"""
SELECT id
FROM documents
WHERE checksum_sha256 = '{checksum}'
LIMIT 1;
""")

if existing:
    raise SystemExit(
        f"Document already ingested as document_id={existing}"
    )


metadata = {
    "synthetic": False,
    "ingestion_version": "v1",
    "source_filename": path.name
}

metadata_json = json.dumps(
    metadata,
    ensure_ascii=False
)


doc_id = psql(f"""
INSERT INTO documents (
    title,
    domain,
    topic,
    document_type,
    authority,
    jurisdiction,
    source_type,
    source_url,
    checksum_sha256,
    language,
    metadata
)
VALUES (
    '{sql_quote(args.title)}',
    '{sql_quote(args.domain)}',
    '{sql_quote(args.topic)}',
    '{sql_quote(args.document_type)}',
    '{sql_quote(args.authority)}',
    '{sql_quote(args.jurisdiction)}',
    'local-file',
    {("'" + sql_quote(args.source_url) + "'") if args.source_url else "NULL"},
    '{checksum}',
    '{sql_quote(args.language)}',
    '{sql_quote(metadata_json)}'::jsonb
)
RETURNING id;
""")

doc_id = int(doc_id)

print(f"Document ID: {doc_id}")


for index, chunk in enumerate(chunks):

    content = chunk["content"]

    chunk_metadata = json.dumps({
        "synthetic": False
    })

    chunk_id = psql(f"""
    INSERT INTO chunks (
        document_id,
        chunk_index,
        content,
        page_start,
        page_end,
        metadata
    )
    VALUES (
        {doc_id},
        {index},
        '{sql_quote(content)}',
        {"NULL" if chunk["page_start"] is None else chunk["page_start"]},
        {"NULL" if chunk["page_end"] is None else chunk["page_end"]},
        '{chunk_metadata}'::jsonb
    )
    RETURNING id;
    """)

    chunk_id = int(chunk_id)

    vector = embed(content)

    vector_literal = (
        "[" + ",".join(str(x) for x in vector) + "]"
    )

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
    );
    """)

    print(
        f"✓ chunk {index + 1}/{len(chunks)} "
        f"id={chunk_id} "
        f"page={chunk['page_start']}"
    )


print()
print("Ingestion completed.")
print(f"Document ID: {doc_id}")
print(f"Chunks: {len(chunks)}")
print(f"SHA256: {checksum}")
