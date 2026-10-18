#!/usr/bin/env python3

import argparse
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path


LEGAL_TAGS = {
    "section",
    "subsection",
    "paragraph",
    "subparagraph",
}


def local(tag):
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def clean_text(elem):
    return " ".join(
        "".join(elem.itertext()).split()
    )


def direct_child_text(elem, wanted_tag):
    for child in elem:
        if local(child.tag) == wanted_tag:
            return clean_text(child)
    return ""


def normalize_section_name(value):
    value = (value or "").strip()

    if value.lower().startswith("s"):
        value = value[1:]

    return value


def make_ref(parent_ref, tag, name):

    name = normalize_section_name(name)

    if tag == "section":
        return name

    if not parent_ref:
        return name

    return f"{parent_ref}({name})"


def walk_provisions(elem, parent_ref=None, parent_id=None):

    results = []

    tag = local(elem.tag)

    current_ref = parent_ref
    current_id = parent_id

    if tag in LEGAL_TAGS:

        name = elem.attrib.get("name", "")

        current_ref = make_ref(
            parent_ref,
            tag,
            name
        )

        current_id = (
            elem.attrib.get("temporalId")
            or elem.attrib.get("id")
        )

        heading = direct_child_text(
            elem,
            "heading"
        )

        num = direct_child_text(
            elem,
            "num"
        )

        record = {
            "reference": current_ref,
            "level": tag,
            "name": name,
            "num": num,
            "heading": heading,
            "temporal_id":
                elem.attrib.get("temporalId"),
            "xml_id":
                elem.attrib.get("id"),
            "status":
                elem.attrib.get("status"),
            "reason":
                elem.attrib.get("reason"),
            "start_period":
                elem.attrib.get("startPeriod"),
            "parent_reference":
                parent_ref,
            "parent_temporal_id":
                parent_id,
            "content":
                clean_text(elem),
        }

        results.append(record)

    # Recurse through EVERY child.
    # Non-legal container elements simply preserve
    # the nearest legal parent context.
    for child in elem:

        results.extend(
            walk_provisions(
                child,
                current_ref,
                current_id
            )
        )

    return results


def deduplicate(records):

    seen = set()
    output = []

    for item in records:

        key = (
            item.get("temporal_id"),
            item.get("reference"),
            item.get("xml_id")
        )

        if key in seen:
            continue

        seen.add(key)
        output.append(item)

    return output


def normalize_query_ref(value):

    value = value.strip()

    value = re.sub(
        r"^(?:s\.?|section)\s*",
        "",
        value,
        flags=re.I
    )

    value = value.replace(" ", "")

    return value


def main():

    parser = argparse.ArgumentParser(
        description="Parse HKeL XML into legal provisions."
    )

    parser.add_argument(
        "file"
    )

    parser.add_argument(
        "--ref",
        help="Show one provision, e.g. 16(3A)"
    )

    parser.add_argument(
        "--json",
        action="store_true"
    )

    args = parser.parse_args()

    path = Path(args.file)

    tree = ET.parse(path)
    root = tree.getroot()

    records = deduplicate(
        walk_provisions(root)
    )

    if args.ref:

        target = normalize_query_ref(
            args.ref
        ).lower()

        records = [
            item
            for item in records
            if (
                item["reference"]
                .replace(" ", "")
                .lower()
                == target
            )
        ]

    if args.json:

        print(
            json.dumps(
                records,
                indent=2,
                ensure_ascii=False
            )
        )

        return

    print(
        f"Parsed provisions: {len(records)}"
    )

    print()

    for item in records:

        print(
            item["reference"],
            "|",
            item["level"],
            "|",
            item["heading"]
        )

        print(
            item["content"][:800]
        )

        print()


if __name__ == "__main__":
    main()
