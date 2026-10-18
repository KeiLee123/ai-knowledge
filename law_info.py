#!/usr/bin/env python3

import argparse
import re
from pathlib import Path

import yaml


REGISTRY = Path(
    "/opt/ai-knowledge/legislation_registry.yaml"
)


def normalize_cap(value):
    value = value.strip().upper()

    value = value.replace("CAP.", "CAP_")
    value = value.replace("CAP ", "CAP_")
    value = value.replace("-", "_")

    if re.fullmatch(r"\d+", value):
        value = f"CAP_{value}"

    return value


def main():

    parser = argparse.ArgumentParser(
        description="Show legislation registry information."
    )

    parser.add_argument(
        "legislation",
        help="e.g. CAP_572, Cap.572, 572"
    )

    args = parser.parse_args()

    with REGISTRY.open(
        "r",
        encoding="utf-8"
    ) as f:
        data = yaml.safe_load(f)

    key = normalize_cap(args.legislation)

    laws = data.get("legislation", {})

    if key not in laws:
        print(
            f"Legislation not found: "
            f"{args.legislation}"
        )
        raise SystemExit(1)

    item = laws[key]
    defaults = data.get("defaults", {})

    print()
    print("=" * 72)

    print(
        f"Cap.{item['chapter']} "
        f"{item['title']}"
    )

    print("=" * 72)
    print()

    print(
        "Mapping status:",
        item.get(
            "mapping_status",
            "unknown"
        )
    )

    print(
        "Jurisdiction:",
        defaults.get(
            "jurisdiction",
            "HK"
        )
    )

    print(
        "Source of truth:",
        defaults.get(
            "source_of_truth",
            "HKeL"
        )
    )

    print(
        "Monitoring:",
        defaults.get(
            "check_frequency",
            "unknown"
        )
    )

    print()

    authorities = item.get(
        "responsible_authorities",
        []
    )

    if not authorities:

        print(
            "Responsible authorities:"
        )

        print(
            "  Pending verification"
        )

    else:

        print(
            "Responsible authorities:"
        )

        print()

        for authority in authorities:

            code = authority.get(
                "authority_code",
                "Unknown"
            )

            role = authority.get(
                "role",
                ""
            )

            officer = authority.get(
                "statutory_officer"
            )

            print(
                f"{code}"
                + (
                    f" — {role}"
                    if role
                    else ""
                )
            )

            if officer:
                print(
                    f"  Statutory officer: "
                    f"{officer}"
                )

            scope = authority.get(
                "scope",
                []
            )

            if scope:
                print("  Scope:")

                for value in scope:
                    print(
                        f"    - {value}"
                    )

            print()

    bootstrap = defaults.get(
        "bootstrap",
        {}
    )

    lifecycle = defaults.get(
        "lifecycle",
        {}
    )

    print("Watch policy:")

    print(
        "  Download current version:",
        bootstrap.get(
            "download_current_version",
            False
        )
    )

    print(
        "  Human review required:",
        lifecycle.get(
            "require_human_review",
            False
        )
    )

    print(
        "  Auto supersede:",
        lifecycle.get(
            "auto_supersede",
            False
        )
    )

    print()


if __name__ == "__main__":
    main()
