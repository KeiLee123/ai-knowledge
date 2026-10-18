#!/usr/bin/env python3

import argparse
import json
import re
import xml.etree.ElementTree as ET
from collections import Counter
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


def normalize_name(value):
    value = (value or "").strip()

    if value.lower().startswith("s"):
        value = value[1:]

    return value


def schedule_number(value):
    value = (value or "").strip()

    m = re.fullmatch(
        r"sch(.+)",
        value,
        flags=re.I
    )

    if m:
        return m.group(1)

    return value or None


def citation_component(tag, xml_name, num):

    xml_component = normalize_name(
        xml_name
    )

    num = (num or "").strip()

    # Sections normally display:
    # 16.
    # 24AA.
    if tag == "section":

        m = re.fullmatch(
            r"([0-9]+[A-Za-z]*)\.",
            num
        )

        if m:
            return (
                m.group(1),
                True,
                "visible-num"
            )

        return (
            xml_component,
            bool(xml_component),
            "xml-name-fallback"
        )

    # Subsections / paragraphs normally display:
    # (3A), (d), (i), etc.
    m = re.fullmatch(
        r"\(([^()]+)\)",
        num
    )

    if m:
        return (
            m.group(1).strip(),
            True,
            "visible-num"
        )

    return (
        xml_component,
        bool(xml_component),
        "xml-name-fallback"
    )


def build_raw_ref(
    parent_ref,
    tag,
    component
):

    component = (
        component or ""
    ).strip()

    if tag == "section":
        return component

    if not parent_ref:
        return component

    return (
        f"{parent_ref}"
        f"({component})"
    )


def build_canonical_ref(
    raw_ref,
    schedule_no,
    in_definition,
    in_table,
    component_valid
):

    if (
        not raw_ref
        or not component_valid
        or in_definition
        or in_table
    ):
        return None

    if schedule_no:
        return (
            f"Sch.{schedule_no} "
            f"s.{raw_ref}"
        )

    return raw_ref


def text_marks_repealed(
    num,
    content
):

    text = (
        content or ""
    ).strip()

    num = (
        num or ""
    ).strip()

    if (
        num
        and text.startswith(num)
    ):
        text = text[
            len(num):
        ].lstrip()

    return bool(
        re.match(
            r"^\(?\s*"
            r"(?:Repealed|Revoked)"
            r"\b",
            text,
            flags=re.I
        )
    )


def walk(
    elem,
    parent_ref=None,
    parent_temporal_id=None,
    schedule_no=None,
    part_name=None,
    definition_name=None,
    definition_text=None,
    repealed_context=False,
    in_table=False
):

    records = []

    tag = local(elem.tag)

    current_ref = parent_ref
    current_temporal_id = (
        parent_temporal_id
    )

    current_schedule = (
        schedule_no
    )

    current_part = (
        part_name
    )

    current_definition = (
        definition_name
    )

    current_definition_text = (
        definition_text
    )

    current_in_table = (
        in_table
        or tag in {
            "table",
            "thead",
            "tbody",
            "tr",
            "td",
        }
    )

    status = elem.attrib.get(
        "status"
    )

    reason = elem.attrib.get(
        "reason"
    )

    current_repealed = (
        repealed_context
        or status == "repealed"
        or reason == "repealed"
    )

    # --------------------------------------------------------
    # Structural context
    # --------------------------------------------------------

    if tag == "schedule":

        current_schedule = (
            schedule_number(
                elem.attrib.get(
                    "name"
                )
            )
        )

    elif tag == "part":

        current_part = (
            elem.attrib.get(
                "name"
            )
        )

    elif tag == "def":

        current_definition = (
            elem.attrib.get(
                "name"
            )
            or ""
        )

        current_definition_text = (
            clean_text(elem)
        )

    # --------------------------------------------------------
    # Legal provision
    # --------------------------------------------------------

    if tag in LEGAL_TAGS:

        xml_name = elem.attrib.get(
            "name",
            ""
        )

        num = direct_child_text(
            elem,
            "num"
        )

        content = clean_text(
            elem
        )

        (
            component,
            component_valid,
            component_source
        ) = citation_component(
            tag,
            xml_name,
            num
        )

        current_ref = build_raw_ref(
            parent_ref,
            tag,
            component
        )

        current_temporal_id = (
            elem.attrib.get(
                "temporalId"
            )
            or elem.attrib.get(
                "id"
            )
        )

        # Some HKeL nodes have no explicit
        # repealed status attribute but the
        # displayed provision says "(Repealed ...)".
        if text_marks_repealed(
            num,
            content
        ):
            current_repealed = True

        canonical_ref = (
            build_canonical_ref(
                current_ref,
                current_schedule,
                bool(
                    current_definition
                ),
                current_in_table,
                component_valid
            )
        )

        record = {

            "raw_reference":
                current_ref,

            "canonical_reference":
                canonical_ref,

            "exact_ref_eligible":
                canonical_ref
                is not None,

            "level":
                tag,

            "name":
                xml_name,

            "xml_name":
                xml_name,

            "citation_component":
                component,

            "citation_component_source":
                component_source,

            "num":
                num,

            "heading":
                direct_child_text(
                    elem,
                    "heading"
                ),

            "temporal_id":
                elem.attrib.get(
                    "temporalId"
                ),

            "xml_id":
                elem.attrib.get(
                    "id"
                ),

            "parent_raw_reference":
                parent_ref,

            "parent_temporal_id":
                parent_temporal_id,

            "schedule_number":
                current_schedule,

            "part_name":
                current_part,

            "definition_name":
                current_definition,

            "definition_text":
                (
                    current_definition_text
                    if current_definition
                    else None
                ),

            "in_table":
                current_in_table,

            "status":
                status,

            "reason":
                reason,

            "start_period":
                elem.attrib.get(
                    "startPeriod"
                ),

            "repealed":
                current_repealed,

            "operative":
                not current_repealed,

            "content":
                content,
        }

        records.append(
            record
        )

    # --------------------------------------------------------
    # Recurse
    # --------------------------------------------------------

    for child in elem:

        records.extend(
            walk(
                child,
                parent_ref=current_ref,
                parent_temporal_id=
                    current_temporal_id,
                schedule_no=
                    current_schedule,
                part_name=
                    current_part,
                definition_name=
                    current_definition,
                definition_text=
                    current_definition_text,
                repealed_context=
                    current_repealed,
                in_table=
                    current_in_table
            )
        )

    return records


def deduplicate(records):
    seen = set()
    output = []

    for item in records:

        # xml_id is the safest identity where present.
        key = (
            item.get("xml_id"),
            item.get("canonical_reference"),
            item.get("definition_name"),
            item.get("raw_reference")
        )

        if key in seen:
            continue

        seen.add(key)
        output.append(item)

    return output


def normalize_query_ref(value):
    value = value.strip()

    # Schedule form
    m = re.fullmatch(
        r"(?:sch(?:edule)?\.?\s*)([0-9A-Za-z]+)"
        r"\s*(?:s(?:ection)?\.?\s*)"
        r"(.+)",
        value,
        flags=re.I
    )

    if m:
        sch = m.group(1)
        ref = m.group(2).replace(" ", "")

        return (
            f"Sch.{sch} s.{ref}"
        )

    value = re.sub(
        r"^(?:s\.?|section)\s*",
        "",
        value,
        flags=re.I
    )

    return value.replace(" ", "")


def main():

    parser = argparse.ArgumentParser(
        description=(
            "Parse HKeL XML with "
            "context-aware legal references."
        )
    )

    parser.add_argument(
        "file"
    )

    parser.add_argument(
        "--ref",
        help=(
            "Canonical reference, e.g. "
            "16(3A) or Sch.7 s.16"
        )
    )

    parser.add_argument(
        "--definition",
        help=(
            "Filter by HKeL definition name, "
            "e.g. AuthorizedPerson"
        )
    )

    parser.add_argument(
        "--json",
        action="store_true"
    )

    parser.add_argument(
        "--stats",
        action="store_true"
    )

    args = parser.parse_args()

    path = Path(args.file)

    root = ET.parse(path).getroot()

    records = deduplicate(
        walk(root)
    )

    if args.ref:

        target = normalize_query_ref(
            args.ref
        ).lower()

        records = [
            item
            for item in records
            if (
                item.get(
                    "canonical_reference"
                )
                and
                item[
                    "canonical_reference"
                ].lower() == target
            )
        ]

    if args.definition:

        target = args.definition.lower()

        records = [
            item
            for item in records
            if (
                item.get(
                    "definition_name"
                )
                and
                item[
                    "definition_name"
                ].lower() == target
            )
        ]

    if args.stats:

        canonical = [
            r["canonical_reference"]
            for r in records
            if r.get(
                "canonical_reference"
            )
        ]

        counts = Counter(canonical)

        duplicates = {
            ref: count
            for ref, count
            in counts.items()
            if count > 1
        }

        eligible = sum(
            1
            for r in records
            if r["exact_ref_eligible"]
        )

        definitions = sum(
            1
            for r in records
            if r.get(
                "definition_name"
            )
        )

        repealed = sum(
            1
            for r in records
            if r.get(
                "repealed"
            )
        )

        print(
            json.dumps(
                {
                    "total_records":
                        len(records),

                    "exact_ref_eligible":
                        eligible,

                    "definition_internal":
                        definitions,

                    "repealed":
                        repealed,

                    "canonical_references":
                        len(counts),

                    "duplicate_canonical_references":
                        duplicates,
                },
                indent=2,
                ensure_ascii=False
            )
        )

        return

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
        "Parsed records:",
        len(records)
    )

    for item in records:

        print()
        print(
            item.get(
                "canonical_reference"
            )
            or
            f"[non-canonical] "
            f"{item['raw_reference']}"
        )

        if item.get(
            "definition_name"
        ):
            print(
                "  definition:",
                item[
                    "definition_name"
                ]
            )

        print(
            "  ",
            item["content"][:500]
        )


if __name__ == "__main__":
    main()
