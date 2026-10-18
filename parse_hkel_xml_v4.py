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


def schedule_prefix(schedule_no):

    if schedule_no is None:
        return None

    value = str(
        schedule_no
    ).strip()

    # HKeL uses sch0 for an unnumbered Schedule.
    if value == "0":
        return "Schedule"

    return f"Sch.{value}"


def part_prefix(part_name):

    if not part_name:
        return None

    value = str(
        part_name
    ).strip()

    m = re.fullmatch(
        r"P(.+)",
        value,
        flags=re.I
    )

    if m:
        return f"Pt.{m.group(1)}"

    return value


def structural_prefix(
    schedule_no,
    part_name
):

    schedule = schedule_prefix(
        schedule_no
    )

    if not schedule:
        return None

    parts = [schedule]

    part = part_prefix(
        part_name
    )

    if part:
        parts.append(part)

    return " ".join(parts)


def build_canonical_ref(
    parent_canonical,
    raw_ref,
    tag,
    num,
    component,
    schedule_no,
    part_name,
    in_definition,
    in_table,
    component_valid,
    content
):

    # Definitions and table-internal numbering are
    # not independent statutory references.
    if (
        not component_valid
        or in_definition
        or in_table
    ):
        return None

    num = (
        num or ""
    ).strip()

    content = (
        content or ""
    ).strip()

    # HKeL occasionally contains structural ghost
    # nodes with an XML name but no visible number
    # and no substantive text.
    if (
        not num
        and not content
    ):
        return None

    # --------------------------------------------------------
    # Child of an already canonical legal provision
    # --------------------------------------------------------

    if parent_canonical:

        return (
            f"{parent_canonical}"
            f"({component})"
        )

    # --------------------------------------------------------
    # Schedule-level provision
    # --------------------------------------------------------

    prefix = structural_prefix(
        schedule_no,
        part_name
    )

    if prefix:

        # Some schedules contain top-level provisions
        # displayed as "(1)", "(2)" even though HKeL
        # encodes them as <section>.
        #
        # Keep them distinct from "1.", "2." provisions.
        if (
            tag == "section"
            and re.fullmatch(
                r"\([^()]+\)",
                num
            )
        ):
            return (
                f"{prefix} "
                f"para.{num}"
            )

        if tag == "section":
            return (
                f"{prefix} "
                f"s.{component}"
            )

        return (
            f"{prefix} "
            f"{tag}.({component})"
        )

    # --------------------------------------------------------
    # Main body
    # --------------------------------------------------------

    if tag == "section":
        return component

    if raw_ref:
        return raw_ref

    return None


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
    parent_canonical=None,
    parent_temporal_id=None,
    schedule_no=None,
    part_name=None,
    definition_name=None,
    definition_text=None,
    repealed_context=False,
    in_table=False
):

    records = []

    tag = local(
        elem.tag
    )

    current_ref = (
        parent_ref
    )

    current_canonical = (
        parent_canonical
    )

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

        # New Schedule = new statutory numbering context.
        current_ref = None
        current_canonical = None
        current_temporal_id = None
        current_part = None

    elif tag == "part":

        current_part = (
            elem.attrib.get(
                "name"
            )
        )

        # Inside a Schedule, each Part may restart
        # its own section numbering.
        if current_schedule is not None:
            current_ref = None
            current_canonical = None
            current_temporal_id = None

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

        if text_marks_repealed(
            num,
            content
        ):
            current_repealed = True

        canonical_ref = (
            build_canonical_ref(
                parent_canonical=
                    parent_canonical,

                raw_ref=
                    current_ref,

                tag=
                    tag,

                num=
                    num,

                component=
                    component,

                schedule_no=
                    current_schedule,

                part_name=
                    current_part,

                in_definition=
                    bool(
                        current_definition
                    ),

                in_table=
                    current_in_table,

                component_valid=
                    component_valid,

                content=
                    content,
            )
        )

        current_canonical = (
            canonical_ref
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

            "parent_canonical_reference":
                parent_canonical,

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

                parent_ref=
                    current_ref,

                parent_canonical=
                    current_canonical,

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

    value = " ".join(
        value.strip().split()
    )

    # --------------------------------------------------------
    # Unnumbered Schedule + Part + section
    # e.g. Schedule Pt.2 s.1
    # --------------------------------------------------------

    m = re.fullmatch(
        r"Schedule\s+"
        r"(?:Pt\.?|Part)\s*([0-9A-Za-z]+)\s+"
        r"(?:s\.?|section)\s*(.+)",
        value,
        flags=re.I
    )

    if m:

        part = m.group(1)
        ref = m.group(2).replace(
            " ",
            ""
        )

        return (
            f"Schedule Pt.{part} "
            f"s.{ref}"
        )

    # --------------------------------------------------------
    # Numbered Schedule + Part + section
    # e.g. Sch.5 Pt.5 s.1
    # --------------------------------------------------------

    m = re.fullmatch(
        r"(?:Sch(?:edule)?\.?)\s*"
        r"([0-9A-Za-z]+)\s+"
        r"(?:Pt\.?|Part)\s*"
        r"([0-9A-Za-z]+)\s+"
        r"(?:s\.?|section)\s*(.+)",
        value,
        flags=re.I
    )

    if m:

        sch = m.group(1)
        part = m.group(2)

        ref = m.group(3).replace(
            " ",
            ""
        )

        return (
            f"Sch.{sch} "
            f"Pt.{part} "
            f"s.{ref}"
        )

    # --------------------------------------------------------
    # Numbered Schedule + paragraph
    # e.g. Sch.3 para.(1)
    # --------------------------------------------------------

    m = re.fullmatch(
        r"(?:Sch(?:edule)?\.?)\s*"
        r"([0-9A-Za-z]+)\s+"
        r"(?:para(?:graph)?\.?)\s*"
        r"(.+)",
        value,
        flags=re.I
    )

    if m:

        sch = m.group(1)

        para = m.group(2).replace(
            " ",
            ""
        )

        return (
            f"Sch.{sch} "
            f"para.{para}"
        )

    # --------------------------------------------------------
    # Numbered Schedule + section
    # e.g. Sch.7 s.16
    # --------------------------------------------------------

    m = re.fullmatch(
        r"(?:Sch(?:edule)?\.?)\s*"
        r"([0-9A-Za-z]+)\s+"
        r"(?:s\.?|section)\s*(.+)",
        value,
        flags=re.I
    )

    if m:

        sch = m.group(1)

        ref = m.group(2).replace(
            " ",
            ""
        )

        return (
            f"Sch.{sch} "
            f"s.{ref}"
        )

    # --------------------------------------------------------
    # Main Ordinance
    # e.g. s.16(3A)
    # --------------------------------------------------------

    value = re.sub(
        r"^(?:s\.?|section)\s*",
        "",
        value,
        flags=re.I
    )

    return value.replace(
        " ",
        ""
    )


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
