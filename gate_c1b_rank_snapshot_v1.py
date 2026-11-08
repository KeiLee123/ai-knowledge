#!/usr/bin/env python3
"""Pinned user-observed ranking METADATA for Gate C-1b, not a Gold answer set.

C1 evaluation was run read-only in an isolated GitHub feature checkout against
Staging SHA 099094e... on 2026-11-08. No questions, excerpts or secrets here.
Each row: case_id, original_rank, source_cohesion_rank, form_aware_rank.
"""
VERSION = "gate-c1b-operator-rank-snapshot-v1"
STAGING_SHA = "099094e04bc0ea46fba3eee2cba9050d1a209e7f"
EXPERIMENT_SHA = "2746954dbd43bba5c750e33af7b663eb6d0a126f"
LABELS = "DRAFT_NOT_PROFESSIONALLY_APPROVED_GOLD"
POLICIES = ("original", "source_cohesion", "source_cohesion_form_aware")
ROWS = (
    ("Q01", 6, 5, 3),
    ("Q02", 4, 4, 4),
    ("Q03", 1, 1, 1),
    ("Q04", 4, 11, 10),
    ("Q05", 6, 3, 2),
    ("Q06", 1, 1, 6),
    ("Q07", 1, 1, 6),
    ("Q08", 5, 5, 2),
    ("Q09", 6, 6, 7),
    ("Q10", 5, 5, 5),
    ("Q11", 2, 2, 2),
    ("Q12", 1, 1, 1),
    ("Q13", 1, 1, 4),
    ("Q14", 5, 5, 3),
    ("Q15", 4, 4, 3),
    ("Q16", 2, 2, 2),
)


def ranks_for(policy):
    if policy not in POLICIES:
        raise ValueError("unknown_recorded_policy")
    index = POLICIES.index(policy) + 1
    return tuple((r[0], r[index]) for r in ROWS)
