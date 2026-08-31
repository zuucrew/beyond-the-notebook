"""The queue.

There is no broker and no jobs table. A claim row *is* the job, and `status` is
the answer to "what has been processed". That is the entire design, and every
correctness property in this file follows from it.
"""
from psycopg.types.json import Json

from ...config import LEASE_SECONDS, MAX_ATTEMPTS
from .pool import transaction

TERMINAL = ("auto_approved", "approved", "rejected", "incomplete", "extraction_failed")


# --------------------------------------------------------------------------
# producer
# --------------------------------------------------------------------------

def submit(client_id: str, form_code: str, storage_uri: str) -> str | None:
    """Enqueue a claim. Returns the id, or None if it was already submitted.

    This does NOT extract. It writes one row and returns. Extraction is a
    separate process reading the same row later, which is what makes it
    retryable -- if submit did the work and crashed, the claim would be gone
    with nobody aware it had ever existed.

    ON CONFLICT makes this idempotent: storage_uri is content-addressed, so
    submitting the same document twice produces one claim. A client that retries
    after a lost response does not create a duplicate.
    """
    with transaction() as conn:
        row = conn.execute(
            """
            INSERT INTO claims (client_id, form_code, storage_uri, status)
            VALUES (%s, %s, %s, 'submitted')
            ON CONFLICT (storage_uri) DO NOTHING
            RETURNING id
            """,
            (client_id, form_code, storage_uri),
        ).fetchone()
    return str(row["id"]) if row else None


# --------------------------------------------------------------------------
# extraction side
# --------------------------------------------------------------------------

def claim_next_for_extraction(worker_id: str) -> dict | None:
    """Take one submitted claim and mark it in progress. THE core of the project.

    Three things make this correct, and all three are easy to get wrong:

    1. SELECT and UPDATE are in ONE transaction. The row lock taken by
       FOR UPDATE lives for the life of the *transaction*, not the statement.
       Split this into a select, a commit, and a separate update and two workers
       will take the same claim. The code looks almost identical and is wrong.

    2. SKIP LOCKED, not plain FOR UPDATE. Without it, worker B blocks until
       worker A's transaction ends. With it, B skips the locked row and takes
       the next one. That is what lets you scale by starting more processes.

    3. A lease is set. If this worker dies mid-extraction the row is stranded in
       'extracting', which nothing queries -- the reaper uses lease_expires_at
       to put it back. Machines abandon work exactly like humans do; they just
       do it by crashing instead of going to lunch.

    Prove it to yourself with two psql sessions before trusting it.
    """
    with transaction() as conn:
        row = conn.execute(
            """
            SELECT id, storage_uri, form_code, attempt_count
            FROM claims
            WHERE status = 'submitted'
            ORDER BY created_at
            LIMIT 1
            FOR UPDATE SKIP LOCKED
            """
        ).fetchone()
        if row is None:
            return None

        conn.execute(
            """
            UPDATE claims
            SET status           = 'extracting',
                attempt_count    = attempt_count + 1,
                locked_by        = %s,
                lease_expires_at = now() + make_interval(secs => %s),
                updated_at       = now()
            WHERE id = %s
            """,
            (worker_id, LEASE_SECONDS, row["id"]),
        )
        return {
            "id": str(row["id"]),
            "storage_uri": row["storage_uri"],
            "form_code": row["form_code"],
            "attempt_count": row["attempt_count"] + 1,
        }


def finish_extraction(claim_id: str, extracted: dict, status: str, actor: str) -> None:
    """Write the result and route, in one transaction.

    Extraction and routing commit together. That is deliberate: routing is a
    pure function of the result, so persisting the claim in between would create
    a state nothing queries -- and claims would fall into it and die silently.
    """
    with transaction() as conn:
        conn.execute(
            """
            UPDATE claims
            SET extracted        = %s,
                status           = %s,
                locked_by        = NULL,
                lease_expires_at = NULL,
                updated_at       = now()
            WHERE id = %s
            """,
            (Json(extracted), status, claim_id),
        )
        # Append-only history. The model's answer is preserved even after a
        # human overwrites it in claims.extracted -- that difference is the most
        # valuable data this system produces.
        for field_key, field in extracted.items():
            conn.execute(
                """
                INSERT INTO field_events
                    (claim_id, field_key, event_type, new_value, confidence, actor)
                VALUES (%s, %s, 'extracted', %s, %s, %s)
                """,
                (claim_id, field_key, field["value"], field["confidence"], actor),
            )


def fail_extraction(claim_id: str, attempt_count: int) -> str:
    """Give up, or release for another attempt.

    Without this a poison document -- one that crashes the extractor every time
    -- is retried forever, and it will sit at the head of the queue delaying
    everything behind it. extraction_failed is the dead-letter state.
    """
    status = "extraction_failed" if attempt_count >= MAX_ATTEMPTS else "submitted"
    with transaction() as conn:
        conn.execute(
            """
            UPDATE claims
            SET status = %s, locked_by = NULL, lease_expires_at = NULL,
                updated_at = now()
            WHERE id = %s
            """,
            (status, claim_id),
        )
    return status


# --------------------------------------------------------------------------
# review side
# --------------------------------------------------------------------------

def claim_next_for_review(reviewer_id: str) -> dict | None:
    """Identical shape to the extraction claim. Same lock, different WHERE.

    The consumer being a human changes nothing structurally -- it just makes the
    lease matter more, because humans abandon work far more often than processes
    crash.
    """
    with transaction() as conn:
        row = conn.execute(
            """
            SELECT id, storage_uri, form_code, extracted
            FROM claims
            WHERE status = 'pending_review'
            ORDER BY created_at
            LIMIT 1
            FOR UPDATE SKIP LOCKED
            """
        ).fetchone()
        if row is None:
            return None

        conn.execute(
            """
            UPDATE claims
            SET status           = 'in_review',
                locked_by        = %s,
                lease_expires_at = now() + make_interval(secs => %s),
                updated_at       = now()
            WHERE id = %s
            """,
            (reviewer_id, LEASE_SECONDS, row["id"]),
        )
        return {
            "id": str(row["id"]),
            "storage_uri": row["storage_uri"],
            "form_code": row["form_code"],
            "extracted": row["extracted"],
        }


def complete_review(
    claim_id: str,
    extracted: dict,
    events: list[dict],
    reviewer_id: str,
    status: str,
) -> None:
    """Write corrections and reach a terminal state, atomically.

    One store, one transaction, so this cannot half-succeed. If the queue lived
    in a broker instead, this would be two writes to two systems with no shared
    transaction -- and either ordering leaves a broken claim. That single fact
    is the whole argument for not adding a message queue.
    """
    with transaction() as conn:
        conn.execute(
            """
            UPDATE claims
            SET extracted = %s, status = %s, locked_by = NULL,
                lease_expires_at = NULL, updated_at = now()
            WHERE id = %s
            """,
            (Json(extracted), status, claim_id),
        )
        for event in events:
            conn.execute(
                """
                INSERT INTO field_events
                    (claim_id, field_key, event_type, old_value, new_value, actor)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    claim_id,
                    event["field_key"],
                    event["event_type"],
                    event.get("old_value"),
                    event.get("new_value"),
                    reviewer_id,
                ),
            )


# --------------------------------------------------------------------------
# recovery and observation
# --------------------------------------------------------------------------

def reap_expired() -> list[dict]:
    """Return abandoned work to its queue.

    One statement. In a broker-based design this needs a second data structure
    and a janitor process to keep it consistent; here it is a WHERE clause.

    This is at-least-once delivery: a reviewer whose lease expires mid-edit will
    have their claim handed to someone else, and both may submit corrections.
    Who wins is D-003, and it is still unanswered.
    """
    with transaction() as conn:
        rows = conn.execute(
            """
            UPDATE claims
            SET status = CASE status
                    WHEN 'extracting' THEN 'submitted'
                    WHEN 'in_review'  THEN 'pending_review'
                END,
                locked_by = NULL,
                lease_expires_at = NULL,
                updated_at = now()
            WHERE status IN ('extracting', 'in_review')
              AND lease_expires_at < now()
            RETURNING id, status, locked_by
            """
        ).fetchall()
    return [dict(r) for r in rows]


def status_counts() -> list[dict]:
    with transaction() as conn:
        rows = conn.execute(
            "SELECT status, count(*) AS n FROM claims GROUP BY status ORDER BY status"
        ).fetchall()
    return [dict(r) for r in rows]


def stuck_claims(older_than: str = "1 hour") -> list[dict]:
    """The safety net.

    Anything non-terminal that has not moved recently. If this ever returns
    rows, a component is down -- and which status is piling up tells you which
    one. 'submitted' means no workers. 'extracting' means no reaper.
    """
    with transaction() as conn:
        rows = conn.execute(
            """
            SELECT id, status, attempt_count, updated_at
            FROM claims
            WHERE status <> ALL(%s)
              AND updated_at < now() - %s::interval
            ORDER BY updated_at
            """,
            (list(TERMINAL), older_than),
        ).fetchall()
    return [dict(r) for r in rows]


def get_claim(claim_id: str) -> dict | None:
    with transaction() as conn:
        row = conn.execute("SELECT * FROM claims WHERE id = %s", (claim_id,)).fetchone()
    return dict(row) if row else None


def field_history(claim_id: str) -> list[dict]:
    with transaction() as conn:
        rows = conn.execute(
            """
            SELECT field_key, event_type, old_value, new_value, confidence,
                   actor, created_at
            FROM field_events WHERE claim_id = %s ORDER BY id
            """,
            (claim_id,),
        ).fetchall()
    return [dict(r) for r in rows]
