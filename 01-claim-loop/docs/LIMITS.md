# Limits

What breaks, when, and what I'd do about it. Written as I go, not at the end.
Answers only count if they name a number or a mechanism. "It would get slow"
is not an answer.

## Scale questions to answer

**Throughput.** 10 claims/day is trivial. At what rate does this system stop
working, and which component gives first: the extractor, the database, or the
humans? Humans are a fixed-capacity resource: N reviewers × M claims/hour is a
hard ceiling that no amount of scaling the app changes.

**Queue depth.** If arrivals exceed review capacity, the queue grows without
bound. What is the intended behaviour: reject, degrade, auto-approve more
aggressively, page someone? Doing nothing is also a choice, just an unstated one.

**The claiming query.** `SKIP LOCKED` scans for the first unlocked eligible
row. With a million rows and most of them terminal, what does that query
actually do? What index makes it stop being a sequential scan?

**Connection limits.** Each app instance holds a pool. Managed Postgres has a
hard `max_connections` tied to instance size. instances × pool_size vs that
number. Write out the arithmetic and find the crossover point. This is the
failure mode that shows up on deploy day, not in local development.

**Lease expiry.** Too short and you steal work from a reviewer mid-typing. Too
long and abandoned claims sit dead for an hour. What's the right number, and
what does the reviewer see when their lease expires while the form is open?

**Storage growth.** An append-only correction log never shrinks. Per claim, how
many rows and bytes? At a year of volume, how large, and does that change the
answer to any question above?

## Correctness questions

**At-least-once means duplicates.** If a lease expires and the claim is
reissued while the first reviewer is still working, two humans may submit
corrections for the same claim. Which one wins, and how does the schema express
that?

**Crash mid-transition.** The process dies between extracting and writing the
result. What state is the claim in when it restarts, and does anything ever
notice it's stuck?

**Poison claims.** A document that crashes the extractor every time it's
retried. What stops it from being retried forever?

## Third-party dependencies

**Extraction goes through OpenRouter**, which is a company that can be down,
rate-limit me, deprecate a model ID, or change pricing. What happens to a claim
that is mid-extraction when that occurs: does it retry, park in a state, or
fail loudly? And what is the blast radius: does the *review* half of the system
keep working while extraction is down, or does everything stop?

That second question is the interesting one. Extraction and review are
independent halves joined only by a table, so there is a design in which
reviewers keep working through an outage. Is that what actually happens?

## Cost

Per 1,000 claims: extraction cost, database cost, human review minutes. Which
term dominates, and by how much? If the answer is "human time by two orders of
magnitude", and it will be, then every engineering optimisation that doesn't
reduce escalation rate is theatre.
