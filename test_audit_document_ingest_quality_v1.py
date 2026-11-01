#!/usr/bin/env python3
"""Offline document table quality smoke tests."""
from audit_document_ingest_quality_v1 import table_shape


def main():
    table = {
        "table_index": 0,
        "row_count": 2,
        "column_count": 2,
        "bbox": [10.0, 10.0, 200.0, 150.0],
        "rows": [["Item", "Limit"], ["Concrete", "40 mm"]],
    }
    assert table_shape(table, 1, 612, 792) == []
    table["rows"][1] = ["Concrete"]
    assert "TABLE_RAGGED_ROWS" in table_shape(table, 1, 612, 792)
    table["rows"][1] = ["Concrete", "40 mm"]
    table["bbox"] = [900.0, 0.0, 1000.0, 150.0]
    assert "TABLE_BBOX_INVALID" in table_shape(table, 1, 612, 792)
    print("DOCUMENT INGEST QUALITY OFFLINE CONTRACT: PASS")


if __name__ == "__main__":
    main()
