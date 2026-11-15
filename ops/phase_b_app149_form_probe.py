"""APP149 public-forms-only layout probe; reports counts/coordinates, never PDF text.

Only runs after exact SHA256 / five-page checks in the direct Docling pilot.
This is an observational adapter, not a document-quality certification.
"""
import re

# Independently established against the byte-pinned APP149.pdf (top-left pt).
_FORM_MW_TOPLEFT = {
    4: ((99.5, 368.0), (244.9, 368.0), (386.5, 368.0),
        (99.5, 390.8), (244.9, 390.8), (386.5, 390.8)),
    5: ((99.5, 349.3), (244.9, 349.3), (386.5, 349.3),
        (99.5, 372.0), (244.9, 372.0), (386.5, 372.0)),
}


def form_reference(pdf):
    import pymupdf
    output = {}
    with pymupdf.open(pdf) as document:
        for number, targets in _FORM_MW_TOPLEFT.items():
            page = document[number - 1]
            found = sorted(
                ((float(w[0]), float(w[1])) for w in page.get_text("words") if w[4] == "MW"),
                key=lambda v: (v[1], v[0]),
            )
            expected_shape = (
                len(found) == 6
                and all(abs(x - ex) <= 1.5 and abs(y - ey) <= 1.5
                        for (x, y), (ex, ey) in zip(found, targets))
            )
            output[str(number)] = {
                "reference_form": "Appendix A" if number == 4 else "Appendix B",
                "reference_mw_box_groups": len(found),
                "reference_mw_pattern_2x3": expected_shape,
                "reference_signature_labels": len(re.findall(
                    r"\bsignature\b", page.get_text("text"), re.I
                )),
                "reference_vector_paths": len(page.get_drawings()),
                "docling_mw_tokens": 0,
                "docling_signature_tokens": 0,
                "mw_bearing_items": 0,
                "mw_anchor_points_covered_by_items": 0,
                "mw_item_bboxes_top_left": [],
            }
    return output


def _top_left_bbox(provenance, page_height):
    bbox = getattr(provenance, "bbox", None)
    try:
        l, r = float(bbox.l), float(bbox.r)
        top, bottom = float(bbox.t), float(bbox.b)
        origin = getattr(bbox, "coord_origin", None)
        if "bottom" in str(getattr(origin, "value", origin)).lower():
            top, bottom = page_height - top, page_height - bottom
        return (min(l, r), min(top, bottom), max(l, r), max(top, bottom))
    except (AttributeError, TypeError, ValueError):
        return None


def _item_text(item):
    """Read table-cell contents once rather than double-counting table text."""
    label = getattr(getattr(item, "label", None), "value", getattr(item, "label", None))
    if label == "table":
        cells = getattr(getattr(item, "data", None), "table_cells", None)
        if cells is not None:
            return " ".join(getattr(c, "text", "") or "" for c in cells)
    return getattr(item, "text", "") or ""


def add_docling_item(reference, number, item, provenance, page_height):
    if number not in (4, 5):
        return
    metrics = reference[str(number)]
    item_text = _item_text(item)
    mw_count = len(re.findall(r"\bMW\b", item_text))
    metrics["docling_mw_tokens"] += mw_count
    metrics["docling_signature_tokens"] += len(re.findall(
        r"\bsignature\b", item_text, re.I
    ))
    if mw_count:
        metrics["mw_bearing_items"] += 1
        box = _top_left_bbox(provenance, page_height)
        if box is not None:
            metrics["mw_item_bboxes_top_left"].append(
                [round(v, 1) for v in box]
            )


def finish(reference):
    for number, targets in _FORM_MW_TOPLEFT.items():
        metrics = reference[str(number)]
        boxes = metrics.pop("mw_item_bboxes_top_left")
        # Expected centers of the printed 'MW' tokens, not the blank boxes.
        centers = [(x + 11.0, y + 6.7) for x, y in targets]
        metrics["mw_anchor_points_covered_by_items"] = sum(
            any(box[0] - 3 <= x <= box[2] + 3
                and box[1] - 3 <= y <= box[3] + 3 for box in boxes)
            for x, y in centers
        )
        metrics["mw_item_bbox_count"] = len(boxes)
        metrics["reference_source_form_pass"] = (
            metrics["reference_mw_pattern_2x3"]
            and metrics["reference_signature_labels"] == 3
            and metrics["reference_vector_paths"] >= 100
        )
    return {
        "status": "AUTO_HOLD_FORM_FIELD_RELATIONSHIPS_NOT_CERTIFIED",
        "note": "Text counts and item-region coverage do not certify field mapping",
        "by_page": reference,
    }
