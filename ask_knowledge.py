#!/usr/bin/env python3

import argparse
import json
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path("/opt/ai-knowledge")

sys.path.insert(0, str(BASE_DIR))

from query_normalizer import normalize


parser = argparse.ArgumentParser(
    description="Ask the AI Knowledge Retrieval System"
)

parser.add_argument(
    "question",
    nargs="+",
    help="Question in Chinese, Cantonese or English"
)

parser.add_argument(
    "--document-title",
    default="",
    help="Optional document scope"
)

args = parser.parse_args()

question = " ".join(args.question).strip()

if not question:
    raise SystemExit("Question cannot be empty.")


print()
print("=" * 78)
print("QUERY NORMALIZER")
print("=" * 78)

normalized = normalize(question)

print(
    json.dumps(
        normalized,
        ensure_ascii=False,
        indent=2
    )
)

english_query = normalized.get(
    "english_query",
    question
)

terms = normalized.get(
    "technical_terms",
    []
)

references = normalized.get(
    "references",
    []
)

domain = normalized.get(
    "domain",
    "general"
)


print()
print("=" * 78)
print("RETRIEVAL")
print("=" * 78)
print(f"Domain: {domain}")


cmd = [
    sys.executable,
    str(BASE_DIR / "hybrid_search_v3.py"),

    "--query",
    question,

    "--english-query",
    english_query,

    "--terms",
    ",".join(terms),

    "--refs",
    ",".join(references),
]


if args.document_title:
    cmd.extend([
        "--document-title",
        args.document_title
    ])


result = subprocess.run(cmd)

raise SystemExit(result.returncode)
