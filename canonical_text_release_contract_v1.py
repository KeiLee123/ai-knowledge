#!/usr/bin/env python3

import json


REQUIRED_ROUTE = "legacy-v1"
FROZEN_INGESTION_VERSION = "canonical-text-ingestion-v1"


def validate_legacy_route(route):
    decision = route.get("decision") or {}

    if decision.get("production_decision_valid") is not True:
        raise RuntimeError(
            "Router did not produce a valid full-document decision"
        )

    if decision.get("eligible_for_v2") is not False:
        raise RuntimeError(
            "Canonical text release refused: "
            "document is eligible for multimodal-v2"
        )

    if decision.get("recommended_pipeline") != REQUIRED_ROUTE:
        raise RuntimeError(
            "Canonical text release refused: "
            "router did not select legacy-v1"
        )

    return decision


def write_json(path, payload):
    path.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
