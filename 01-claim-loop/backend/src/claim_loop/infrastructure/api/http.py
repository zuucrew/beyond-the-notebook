"""HTTP delivery.

A second entrypoint over the same application layer as the CLI. Neither knows
about the other; both call the repository and the routing rules. That is what
the layered structure buys -- adding a browser did not touch domain or
application code.

The queue semantics are unchanged. POST /claims/next-review runs the same
SELECT ... FOR UPDATE SKIP LOCKED as the CLI, takes the same lease, and races
the same way. A browser is just another consumer.
"""
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ...config import ALWAYS_ESCALATE, CONFIDENCE_THRESHOLD, LEASE_SECONDS, PROJECT_ROOT
from ...domain.routing import MANDATORY_FIELDS, fields_needing_review
from ..db import claims_repository as repo

app = FastAPI(title="claim-loop", version="0.1.0")

# The frontend is a separate deployable on its own origin, so it needs CORS.
# Wide open is fine for local development and would not be in production.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class FieldEdit(BaseModel):
    field_key: str
    action: str          # confirmed | corrected | confirmed_blank
    value: str | None = None


class CompleteRequest(BaseModel):
    reviewer: str
    edits: list[FieldEdit]


@app.get("/stats")
def stats():
    counts = {r["status"]: r["n"] for r in repo.status_counts()}
    return {
        "counts": counts,
        "stuck": len(repo.stuck_claims("1 hour")),
        "threshold": CONFIDENCE_THRESHOLD,
        "lease_seconds": LEASE_SECONDS,
    }


@app.get("/claims/{claim_id}")
def get_claim(claim_id: str):
    claim = repo.get_claim(claim_id)
    if claim is None:
        raise HTTPException(404, "no such claim")
    extracted = claim.get("extracted") or {}
    return {
        "id": str(claim["id"]),
        "status": claim["status"],
        "storage_uri": claim["storage_uri"],
        "form_code": claim["form_code"],
        "flagged": fields_needing_review(extracted),
        "mandatory": sorted(MANDATORY_FIELDS),
        "always_escalate": sorted(ALWAYS_ESCALATE),
        "extracted": extracted,
    }


@app.post("/claims/next-review")
def next_review(reviewer: str = "web"):
    """Claim the next task. Same lock, same lease, same race as the CLI."""
    claim = repo.claim_next_for_review(reviewer)
    if claim is None:
        raise HTTPException(404, "nothing waiting for review")
    extracted = claim["extracted"] or {}
    return {
        "id": claim["id"],
        "storage_uri": claim["storage_uri"],
        "form_code": claim["form_code"],
        "flagged": fields_needing_review(extracted),
        "always_escalate": sorted(ALWAYS_ESCALATE),
        "threshold": CONFIDENCE_THRESHOLD,
        "lease_seconds": LEASE_SECONDS,
        "extracted": extracted,
    }


@app.post("/claims/{claim_id}/complete")
def complete(claim_id: str, body: CompleteRequest):
    claim = repo.get_claim(claim_id)
    if claim is None:
        raise HTTPException(404, "no such claim")

    extracted = dict(claim.get("extracted") or {})
    events, blank_mandatory = [], False

    for edit in body.edits:
        old = (extracted.get(edit.field_key) or {}).get("value")
        if edit.action == "corrected":
            extracted[edit.field_key] = {
                "value": edit.value, "confidence": 1.0, "source": "human",
            }
            events.append({"field_key": edit.field_key, "event_type": "corrected",
                           "old_value": old, "new_value": edit.value})
        elif edit.action == "confirmed_blank":
            extracted[edit.field_key] = {
                "value": None, "confidence": 1.0, "source": "blank",
            }
            events.append({"field_key": edit.field_key,
                           "event_type": "confirmed_blank",
                           "old_value": old, "new_value": None})
            if edit.field_key in MANDATORY_FIELDS:
                blank_mandatory = True
        else:
            events.append({"field_key": edit.field_key, "event_type": "confirmed",
                           "old_value": old, "new_value": old})

    # A mandatory field the reviewer confirms is empty is not a review failure:
    # the information is not on the form, so the claim goes back to the claimant.
    status = "incomplete" if blank_mandatory else "approved"
    repo.complete_review(claim_id, extracted, events, body.reviewer, status)
    return {"id": claim_id, "status": status, "events": len(events)}


@app.get("/claims/{claim_id}/document")
def document(claim_id: str):
    """Stream the source PDF so the reviewer can check against it.

    Local only. Once documents live in object storage this returns a signed URL
    instead -- the browser should fetch from storage directly rather than
    through the API.
    """
    claim = repo.get_claim(claim_id)
    if claim is None:
        raise HTTPException(404, "no such claim")
    uri = claim["storage_uri"]
    if not uri.startswith("file://"):
        raise HTTPException(501, "only local documents can be streamed")
    path = Path(uri[len("file://"):])
    path = path if path.is_absolute() else PROJECT_ROOT / path
    if not path.exists():
        raise HTTPException(404, "document missing")
    return FileResponse(path, media_type="application/pdf")


@app.get("/claims")
def list_claims(status: str = "pending_review", limit: int = 50):
    return {"claims": repo.claims_by_status(status, limit)}


@app.get("/health")
def health():
    return {"ok": True}
