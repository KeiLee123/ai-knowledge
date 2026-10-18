#!/usr/bin/env python3

import argparse
import json
import os
import re
import urllib.request
from pathlib import Path

import pymupdf
import yaml
from docx import Document


TAXONOMY_FILE = Path("/opt/ai-knowledge/taxonomy.yaml")

HERMES_ENV = Path(
    "/data/coolify/services/"
    "rgu4flce2juuzyq6idzr49z2/.hermes/.env"
)

HERMES_CONFIG = Path(
    "/data/coolify/services/"
    "rgu4flce2juuzyq6idzr49z2/.hermes/config.yaml"
)


def load_env_file(path):
    values = {}

    if not path.exists():
        return values

    for line in path.read_text(
        encoding="utf-8",
        errors="ignore"
    ).splitlines():

        line = line.strip()

        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)

        values[key.strip()] = value.strip().strip('"').strip("'")

    return values


def extract_text(path):
    suffix = path.suffix.lower()

    if suffix == ".pdf":
        doc = pymupdf.open(path)

        pages = []

        for page in doc:
            pages.append(
                page.get_text("text").strip()
            )

        return "\n\n".join(pages)

    if suffix == ".docx":
        doc = Document(path)

        return "\n".join(
            p.text
            for p in doc.paragraphs
            if p.text.strip()
        )

    if suffix in {".txt", ".md"}:
        return path.read_text(
            encoding="utf-8",
            errors="ignore"
        )

    raise SystemExit(
        f"Unsupported file type: {suffix}"
    )


def compact_text(text, max_chars=18000):
    text = re.sub(r"\n{3,}", "\n\n", text)

    if len(text) <= max_chars:
        return text

    first = text[:12000]
    last = text[-6000:]

    return (
        first
        + "\n\n[... middle omitted for classification ...]\n\n"
        + last
    )


def load_taxonomy():
    with TAXONOMY_FILE.open(
        "r",
        encoding="utf-8"
    ) as f:
        return yaml.safe_load(f)


def get_model_config():
    env = load_env_file(HERMES_ENV)

    api_key = env.get("DEEPSEEK_API_KEY")

    if not api_key:
        raise SystemExit(
            "DEEPSEEK_API_KEY not found."
        )

    config = {}

    if HERMES_CONFIG.exists():
        with HERMES_CONFIG.open(
            "r",
            encoding="utf-8"
        ) as f:
            config = yaml.safe_load(f) or {}

    model_cfg = config.get("model", {})

    model = model_cfg.get(
        "default",
        "deepseek-v4-flash"
    )

    base_url = (
        model_cfg.get("base_url")
        or env.get("DEEPSEEK_BASE_URL")
        or "https://api.deepseek.com"
    )

    return api_key, model, base_url.rstrip("/")


def call_deepseek(system_prompt, user_prompt):
    api_key, model, base_url = get_model_config()

    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": system_prompt
            },
            {
                "role": "user",
                "content": user_prompt
            }
        ],
        "response_format": {
            "type": "json_object"
        },
        "temperature": 0
    }

    data = json.dumps(payload).encode("utf-8")

    req = urllib.request.Request(
        base_url + "/chat/completions",
        data=data,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        },
        method="POST"
    )

    with urllib.request.urlopen(
        req,
        timeout=120
    ) as response:

        result = json.loads(
            response.read().decode("utf-8")
        )

    content = (
        result["choices"][0]["message"]["content"]
    )

    return json.loads(content)


def is_kebab_case(value):
    return bool(
        re.fullmatch(
            r"[a-z0-9]+(?:-[a-z0-9]+)*",
            value or ""
        )
    )


def validate_result(result, taxonomy):
    errors = []

    code = result.get("authority_code")
    domain = result.get("domain")
    document_type = result.get("document_type")
    topic = result.get("topic")

    if code not in taxonomy["authorities"]:
        errors.append(
            f"Unknown authority_code: {code}"
        )

    if domain not in taxonomy["domains"]:
        errors.append(
            f"Unknown domain: {domain}"
        )

    if document_type not in taxonomy["document_types"]:
        errors.append(
            f"Unknown document_type: {document_type}"
        )

    if not is_kebab_case(topic):
        errors.append(
            f"Invalid topic: {topic}"
        )

    prohibited = taxonomy.get(
        "topic_rules",
        {}
    ).get(
        "prohibited",
        []
    )

    if topic in prohibited:
        errors.append(
            f"Prohibited topic: {topic}"
        )

    if code in taxonomy["authorities"]:
        result["authority_name"] = (
            taxonomy["authorities"][code]
        )

    metadata = result.setdefault("metadata", {})

    related_domains = metadata.get("related_domains", [])
    metadata["related_domains"] = [
        x for x in related_domains
        if x != domain
    ]

    related_authorities = metadata.get(
        "related_authorities",
        []
    )

    metadata["related_authorities"] = [
        x for x in related_authorities
        if x != code
    ]

    result["taxonomy_version"] = (
        taxonomy["taxonomy_version"]
    )

    result["taxonomy_valid"] = not errors
    result["validation_errors"] = errors

    return result


def main():
    parser = argparse.ArgumentParser(
        description="AI knowledge metadata classifier."
    )

    parser.add_argument(
        "file",
        help="PDF, DOCX, TXT or MD file"
    )

    args = parser.parse_args()

    path = Path(args.file)

    if not path.exists():
        raise SystemExit(
            f"File not found: {path}"
        )

    taxonomy = load_taxonomy()

    text = extract_text(path)
    sample = compact_text(text)

    authority_text = "\n".join(
        f"- {code}: {name}"
        for code, name
        in taxonomy["authorities"].items()
    )

    domain_text = "\n".join(
        f"- {x}"
        for x in taxonomy["domains"]
    )

    document_type_text = "\n".join(
        f"- {x}"
        for x in taxonomy["document_types"]
    )

    system_prompt = f"""
You classify professional knowledge documents
for a Hong Kong construction/property knowledge base.

Use ONLY the document evidence supplied.

Do not invent legislation, references, dates,
authorities or document relationships.

Authority MUST be selected from this list:

{authority_text}

Domain MUST be selected from this list:

{domain_text}

Document type MUST be selected from this list:

{document_type_text}

Topic:
- must be lowercase kebab-case
- should represent the stable MAIN subject of the document
- prefer a reusable topic over an overly specific topic
- put narrower concepts into metadata.subtopic or keywords
- do not combine multiple concepts into the topic unnecessarily
- do not include the authority name unless essential
- avoid vague topics such as general, misc or others

Example:
Primary subject "Validity of Approved Plans" with discussion of
Exclusion Orders:
topic = "validity-of-approved-plans"
subtopic = "exclusion-orders"

Do NOT use:
topic = "validity-of-approved-plans-exclusion-orders"

Return JSON only with exactly this structure:

{{
  "proposed_title": "",
  "authority_code": "",
  "domain": "",
  "topic": "",
  "document_type": "",
  "jurisdiction": "HK",
  "confidence": 0.0,
  "metadata": {{
    "subtopic": "",
    "related_domains": [],
    "related_authorities": [],
    "statutory_references": [],
    "code_references": [],
    "asset_types": [],
    "work_types": [],
    "project_stages": [],
    "keywords": []
  }},
  "evidence_summary": ""
}}

Rules:
- confidence is between 0 and 1
- related_domains must use approved domain values
- do NOT repeat the primary domain inside related_domains
- related_authorities must use approved authority codes
- do NOT repeat the primary authority inside related_authorities
- statutory_references must only include references
  actually present in the document
- code_references is ONLY for actual codes, standards or code references
- do not put a Practice Note number such as APP-1 into code_references
- project_stages must only be included when clearly supported
  by the document context
- prefer empty arrays over speculative metadata
- evidence_summary must be short and factual
"""

    user_prompt = f"""
Filename:
{path.name}

Document text:

--- BEGIN DOCUMENT ---

{sample}

--- END DOCUMENT ---
"""

    result = call_deepseek(
        system_prompt,
        user_prompt
    )

    result = validate_result(
        result,
        taxonomy
    )

    print(
        json.dumps(
            result,
            indent=2,
            ensure_ascii=False
        )
    )


if __name__ == "__main__":
    main()
