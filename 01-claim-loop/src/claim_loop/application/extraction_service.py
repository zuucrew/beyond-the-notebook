"""The extraction worker.

    short transaction  ->  long work  ->  short transaction

Never hold a transaction open across the slow part. Wrapping the whole loop body
in one transaction would keep a row lock for the duration of the model call,
block VACUUM from reclaiming dead tuples, and turn a healthy queue into bloat.
That is the most common way database-as-queue goes wrong.
"""
import time

from ..domain.routing import route
from ..infrastructure.db import claims_repository as repo
from ..infrastructure.llm_providers.stub import extract


def process_one(worker_id: str) -> dict | None:
    """Handle a single claim. Returns a summary, or None if the queue is empty."""
    claim = repo.claim_next_for_extraction(worker_id)   # transaction. ~1ms
    if claim is None:
        return None

    try:
        # No transaction held here. This is the slow part -- a stub today,
        # a 30-second vision model call at increment 5.
        extracted = extract(claim["storage_uri"])
        status, reasons = route(extracted)
    except Exception as exc:
        outcome = repo.fail_extraction(claim["id"], claim["attempt_count"])
        return {
            "id": claim["id"],
            "status": outcome,
            "error": f"{type(exc).__name__}: {exc}",
            "attempt": claim["attempt_count"],
        }

    repo.finish_extraction(claim["id"], extracted, status, actor=worker_id)  # transaction
    return {
        "id": claim["id"],
        "status": status,
        "reasons": reasons,
        "fields": len(extracted),
    }


def run(worker_id: str, once: bool = False, poll_seconds: float = 1.0):
    """Drain the repo.

    once=True  -> process until empty, then return. This is the cron / Cloud Run
                  Job shape: start, drain, exit, cost nothing until next fired.
    once=False -> keep waiting for more. The daemon shape, for local work.

    The only difference between a background worker and a cron job is what
    happens when the queue is empty.
    """
    while True:
        result = process_one(worker_id)
        if result is None:
            if once:
                return
            time.sleep(poll_seconds)
            continue
        yield result
