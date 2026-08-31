"""Where an extracted claim goes next.

Routing is a pure function of the extraction result. That is why there is no
'extracted' state in the database -- extraction and routing commit together, so
a claim is never parked in a state nothing queries.
"""
from ..config import CONFIDENCE_THRESHOLD

# Present in the mandatory_only and gaps dataset variants. In a multi-form
# system this moves into a template table (D-012); with one form type it is a
# constant, and pretending otherwise would be building for an N you do not have.
MANDATORY_FIELDS = {
    "member_number",
    "given_names",
    "surname",
    "date_of_birth",
    "address_street",
    "address_suburb",
    "address_state",
    "address_postcode",
    "diagnosis",
    "date_of_disability",
    "date_last_worked",
    "signature_date",
    "contact_phone",
}

# Escalated regardless of how confident the model claims to be.
#
# The source documents use DD/MM/YYYY. 03/04/2025 is genuinely ambiguous, and a
# model reading it as March 4th will be *confidently* wrong -- which is exactly
# the case a confidence threshold cannot catch. When a field's failure mode is
# invisible to your uncertainty signal, escalate it unconditionally.
ALWAYS_ESCALATE = {
    "date_of_birth",
    "date_of_disability",
    "date_last_worked",
    "signature_date",
}


def route(extracted: dict[str, dict]) -> tuple[str, list[str]]:
    """Return (next_status, reasons)."""
    reasons: list[str] = []

    blank_mandatory = [
        key
        for key, field in extracted.items()
        if field["source"] == "blank" and key in MANDATORY_FIELDS
    ]
    if blank_mandatory:
        # Not a review problem. The information is not on the form, so no human
        # reading it more carefully will produce it -- this goes back to the
        # claimant. Distinct outcome, distinct state.
        return "incomplete", [f"mandatory field blank on form: {k}" for k in blank_mandatory]

    for key, field in extracted.items():
        if field["source"] != "model":
            continue
        if key in ALWAYS_ESCALATE:
            reasons.append(f"{key}: always escalated (ambiguous date format)")
        elif field["confidence"] < CONFIDENCE_THRESHOLD:
            reasons.append(f"{key}: confidence {field['confidence']:.2f}")

    if reasons:
        return "pending_review", reasons
    return "auto_approved", []


def fields_needing_review(extracted: dict[str, dict]) -> list[str]:
    return [
        key
        for key, field in extracted.items()
        if field["source"] == "model"
        and (key in ALWAYS_ESCALATE or field["confidence"] < CONFIDENCE_THRESHOLD)
    ]
