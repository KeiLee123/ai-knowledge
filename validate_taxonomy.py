#!/usr/bin/env python3

import argparse
import json
import re
import sys
from pathlib import Path

import yaml


TAXONOMY_FILE = Path("/opt/ai-knowledge/taxonomy.yaml")


def load_taxonomy():
    with TAXONOMY_FILE.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def is_kebab_case(value):
    return bool(
        re.fullmatch(
            r"[a-z0-9]+(?:-[a-z0-9]+)*",
            value
        )
    )


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument("--authority", required=True)
    parser.add_argument("--domain", required=True)
    parser.add_argument("--document-type", required=True)
    parser.add_argument("--topic", required=True)

    args = parser.parse_args()

    taxonomy = load_taxonomy()

    authorities = taxonomy["authorities"]
    domains = taxonomy["domains"]
    document_types = taxonomy["document_types"]
    topic_rules = taxonomy["topic_rules"]

    errors = []

    authority_code = None
    authority_name = None

    # Accept either canonical code or canonical full name.
    if args.authority in authorities:
        authority_code = args.authority
        authority_name = authorities[args.authority]

    else:
        for code, name in authorities.items():
            if args.authority == name:
                authority_code = code
                authority_name = name
                break

    if authority_code is None:
        errors.append(
            f"Unknown authority: {args.authority}"
        )

    if args.domain not in domains:
        errors.append(
            f"Unknown domain: {args.domain}"
        )

    if args.document_type not in document_types:
        errors.append(
            f"Unknown document type: {args.document_type}"
        )

    if not is_kebab_case(args.topic):
        errors.append(
            f"Topic must use kebab-case: {args.topic}"
        )

    if args.topic in topic_rules.get("prohibited", []):
        errors.append(
            f"Topic is prohibited: {args.topic}"
        )

    if errors:
        print(
            json.dumps(
                {
                    "valid": False,
                    "errors": errors
                },
                indent=2,
                ensure_ascii=False
            )
        )
        raise SystemExit(1)

    print(
        json.dumps(
            {
                "valid": True,
                "taxonomy_version":
                    taxonomy["taxonomy_version"],
                "authority_code":
                    authority_code,
                "authority_name":
                    authority_name,
                "domain":
                    args.domain,
                "document_type":
                    args.document_type,
                "topic":
                    args.topic
            },
            indent=2,
            ensure_ascii=False
        )
    )


if __name__ == "__main__":
    main()
