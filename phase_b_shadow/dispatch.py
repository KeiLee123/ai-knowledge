"""Operator-only dispatch of one allowlisted, SHA-pinned fixture."""

import argparse
import json
import os
from pathlib import Path

from phase_b_shadow.contract import load_fixture, task_id


def main() -> None:
    parser = argparse.ArgumentParser(description="Dispatch one staging-only PDF shadow task")
    parser.add_argument("fixture_id", help="ID in the mounted immutable catalog")
    args = parser.parse_args()
    if os.environ.get("JASON_OS_ENV") != "staging":
        parser.error("explicit staging identity required")
    input_dir = Path(os.environ["PHASE_B_INPUT_DIR"])
    fixture, _ = load_fixture(input_dir / "catalog.json", args.fixture_id, input_dir)
    from phase_b_shadow.celery_app import parse_pdf, QUEUE
    key = task_id(fixture)
    parse_pdf.apply_async(args=[fixture.fixture_id, fixture.sha256], task_id=key, queue=QUEUE)
    print(json.dumps({"task_id": key, "fixture_id": fixture.fixture_id,
                      "source_sha256": fixture.sha256, "queue": QUEUE}))


if __name__ == "__main__":
    main()
