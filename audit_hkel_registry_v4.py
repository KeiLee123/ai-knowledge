#!/usr/bin/env python3

import json
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

sys.path.insert(
    0,
    "/opt/ai-knowledge"
)

from parse_hkel_xml_v4 import (
    walk,
    deduplicate,
)


ROOT = Path(
    "/opt/ai-knowledge/watch/"
    "legislation/current"
)


def audit_file(path):

    root = ET.parse(path).getroot()

    records = deduplicate(
        walk(root)
    )

    canonical = [
        r["canonical_reference"]
        for r in records
        if r.get(
            "canonical_reference"
        )
    ]

    counts = Counter(
        canonical
    )

    duplicates = {
        ref: count
        for ref, count
        in counts.items()
        if count > 1
    }

    return {
        "total_records":
            len(records),

        "canonical_references":
            len(counts),

        "exact_ref_eligible":
            sum(
                1
                for r in records
                if r.get(
                    "exact_ref_eligible"
                )
            ),

        "definitions":
            sum(
                1
                for r in records
                if r.get(
                    "definition_name"
                )
            ),

        "repealed":
            sum(
                1
                for r in records
                if r.get(
                    "repealed"
                )
            ),

        "duplicates":
            duplicates,
    }


def main():

    results = {}

    failures = {}

    files = sorted(
        ROOT.glob(
            "CAP_*/machine/current.xml"
        )
    )

    print("=" * 92)
    print(
        "HKeL LEGAL PARSER V3 "
        "REGRESSION AUDIT"
    )
    print("=" * 92)

    print()
    print(
        f"{'LAW':<12}"
        f"{'RECORDS':>10}"
        f"{'CANONICAL':>12}"
        f"{'DEFS':>8}"
        f"{'REPEALED':>10}"
        f"{'DUPLICATES':>12}"
    )

    print("-" * 92)

    for path in files:

        law = path.parents[1].name

        try:

            result = audit_file(
                path
            )

            results[law] = result

            print(
                f"{law:<12}"
                f"{result['total_records']:>10}"
                f"{result['canonical_references']:>12}"
                f"{result['definitions']:>8}"
                f"{result['repealed']:>10}"
                f"{len(result['duplicates']):>12}"
            )

        except Exception as exc:

            failures[law] = str(
                exc
            )

            print(
                f"{law:<12}"
                f"{'ERROR':>10}"
            )

    print()
    print("=" * 92)

    laws_with_duplicates = {
        law: data["duplicates"]
        for law, data
        in results.items()
        if data["duplicates"]
    }

    print(
        "Laws audited:",
        len(results)
    )

    print(
        "Parse failures:",
        len(failures)
    )

    print(
        "Laws with canonical collisions:",
        len(
            laws_with_duplicates
        )
    )

    if failures:

        print()
        print("PARSE FAILURES:")

        print(
            json.dumps(
                failures,
                indent=2,
                ensure_ascii=False
            )
        )

    if laws_with_duplicates:

        print()
        print(
            "CANONICAL COLLISIONS:"
        )

        print(
            json.dumps(
                laws_with_duplicates,
                indent=2,
                ensure_ascii=False
            )
        )

    if (
        not failures
        and not laws_with_duplicates
    ):
        print()
        print(
            "QUALITY GATE: PASS"
        )
        print(
            "All current legislation "
            "passed Parser v3 audit."
        )

    else:
        print()
        print(
            "QUALITY GATE: REVIEW REQUIRED"
        )


if __name__ == "__main__":
    main()
