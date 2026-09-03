-- Claims and their audit log.
--
-- Two tables. Everything that varies between clients and form types lives in
-- claims.extracted (jsonb), so adding a client, a form, or a field is never a
-- migration. Everything the queue runs on is a typed, indexed column.

CREATE TABLE claims (
    id               uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id        text        NOT NULL,
    form_code        text        NOT NULL,
    form_version     text        NOT NULL DEFAULT '1',

    -- file:// locally, gs:// when deployed. One column, two schemes.
    -- UNIQUE is what makes submit idempotent: same file, one claim.
    storage_uri      text        NOT NULL UNIQUE,

    status           text        NOT NULL,
    attempt_count    int         NOT NULL DEFAULT 0,

    -- whoever currently holds the lease: a worker during 'extracting',
    -- a reviewer during 'in_review'. Transient. Who *completed* the work is
    -- recorded permanently in field_events.actor.
    locked_by        text,
    lease_expires_at timestamptz,

    extracted        jsonb,

    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT claims_status_valid CHECK (status IN (
        'submitted',
        'extracting',
        'pending_review',
        'in_review',
        'auto_approved',
        'approved',
        'rejected',
        'incomplete',
        'extraction_failed'
    ))
);

-- The queue indexes. PARTIAL on purpose: a claim that reaches a terminal state
-- leaves the index entirely, so the claiming query stays proportional to queue
-- depth rather than table size. 10M processed claims + 5 pending = 5 entries.
CREATE INDEX claims_awaiting_extraction
    ON claims (created_at) WHERE status = 'submitted';

CREATE INDEX claims_awaiting_review
    ON claims (created_at) WHERE status = 'pending_review';

-- The reaper's scan: anything holding a lease that has expired.
CREATE INDEX claims_leased
    ON claims (lease_expires_at) WHERE status IN ('extracting', 'in_review');


-- Append-only. Never UPDATEd, never DELETEd.
-- The model's answer and the human's correction are both rows here. Overwriting
-- claims.extracted in place would destroy the most valuable signal the system
-- produces: where, and how often, the model is wrong.
CREATE TABLE field_events (
    id          bigserial   PRIMARY KEY,
    claim_id    uuid        NOT NULL REFERENCES claims(id) ON DELETE CASCADE,
    field_key   text        NOT NULL,
    event_type  text        NOT NULL,
    old_value   text,
    new_value   text,
    confidence  real,
    actor       text        NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT field_events_type_valid CHECK (event_type IN (
        'extracted',
        'corrected',
        'confirmed',
        'confirmed_blank'
    ))
);

CREATE INDEX field_events_claim ON field_events (claim_id);
CREATE INDEX field_events_field ON field_events (field_key, event_type);
