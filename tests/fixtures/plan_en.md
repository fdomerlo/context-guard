# PLAN-3 — Retry budget for the ingest worker

Give the ingest worker a bounded retry budget so a poisoned message stops
costing the queue its throughput.

## Diagnosis / evidence

A single malformed payload retried forever on 2026-07-30, saturating the
worker pool for six hours. The retry loop has no ceiling.

## F1 — Bounded retry counter

Add a per-message attempt counter persisted alongside the message, so a
restart does not reset the budget back to zero.

**Spec:**
- `max_attempts` defaults to 5, configurable per queue.
- The counter lives in the message envelope, not worker memory.
- Exhausted messages move to the dead-letter queue, never dropped.

**Tests:** write the adversarial test first, confirm it fails against the
current code (RED), then fix, then confirm GREEN.
- A message failing 6 times lands in the dead-letter queue exactly once.
- A worker restart mid-retry preserves the attempt count.

**Acceptance criteria:**
- No message is retried more than `max_attempts` times.
- Dead-lettered messages retain their original payload and headers.

## F2 — Operator visibility

Surface the retry budget in the existing metrics endpoint.

**Spec:**
- Emit `ingest_attempts_total` and `ingest_deadlettered_total`.

**Tests:**
- Both counters appear in the scrape output after a forced failure.

**Acceptance criteria:**
- An operator can tell from metrics alone whether messages are dead-lettering.

## Out of scope

Rewriting the queue transport. The retry budget is orthogonal to it.

## Criteria for the whole cycle

1. Full suite green.
2. Every phase's acceptance criteria met and demonstrated.
