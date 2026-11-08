#!/usr/bin/env python3
"""Gate C1c DRAFT clause-intent review labels; not legal Gold or runtime data.

Source digests identify historical pinned corpus editions only. They NEVER
certify that any provision remains current or that a passage answers a query.
All intent codes are HUMAN-SUPPLIED and REVIEW PENDING.
"""
VERSION = "gate-c1c-clause-catalog-v0.1"
REVIEW_STATUS = "DRAFT_NOT_PROFESSIONALLY_APPROVED"
PINNED_STAGING_SHA = "099094e04bc0ea46fba3eee2cba9050d1a209e7f"

APP145 = "BD_PNAP_APP145"
APP149 = "BD_PNAP_APP149"

SOURCE_SHA256 = {
    APP145: "dc3262cc55c5fd79d29f337fd811cdd871543f59d795972d9f30f558e313127c",
    APP149: "a5b4d5a1af5f4a32b43973db33d95436f9390e8e2da77747ee666015077bb1a8",
}
OFFICIAL_URL = (
    "https://www.bd.gov.hk/doc/en/resources/codes-and-references/"
    "practice-notes-and-circular-letters/pnap/APP/"
)
SOURCE_FILENAME = {APP145: "APP145.pdf", APP149: "APP149.pdf"}

# Sequence priority is for offline demonstration only. No automatic
# question->intent inference; multi-clause completeness is not adjudicated.
DRAFT_INTENT_CLAUSES = {
    "fire_enforcement_split": ((APP145, 115),),
    "fire_legacy_exception": ((APP145, 113),),
    "fire_compliance_difficulty": ((APP145, 116),),
    "fire_plan_submission": ((APP145, 117),),
    "as_temporary_absence": ((APP149, 121), (APP149, 122)),
    "as_substitute_eligibility": ((APP149, 122),),
    "as_absence_over_30_days": ((APP149, 123),),
    "as_change_notification_form": ((APP149, 124), (APP149, 120)),
    "as_temporary_nomination_form": ((APP149, 125), (APP149, 121)),
}
