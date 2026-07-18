# Architecture Decision Record

## ADR-001: Pydantic v2 for Domain Models

**Date:** 2026-07-01  
**Context:** Need validated, immutable data structures across all modules  
**Decision:** Use Pydantic v2 with `BaseModel` for all domain objects  
**Alternatives:** Dataclasses, attrs, TypedDict  
**Consequences:** +validation, +serialization, +IDE support; −small overhead

## ADR-002: Repository Pattern for Database

**Date:** 2026-07-01  
**Context:** Future PostgreSQL migration should not require changing business logic  
**Decision:** Abstract all SQL behind repository classes  
**Alternatives:** Raw SQL everywhere, ORM (SQLAlchemy)  
**Consequences:** +testability, +migration path; −boilerplate

## ADR-003: JSON Only for Crash Recovery

**Date:** 2026-07-01  
**Context:** Need instant recovery without querying DB on restart  
**Decision:** Maintain `state/position_state.json` with atomic writes  
**Alternatives:** DB-only recovery, pickle, protobuf  
**Consequences:** +fast recovery, +human-readable; −duplicate data

## ADR-004: Broker Interface Pattern

**Date:** 2026-07-01  
**Context:** Architecture must support future live trading brokers  
**Decision:** Define abstract `BrokerInterface`; implement `PaperBroker` and `UpstoxBroker`  
**Alternatives:** Direct Upstox coupling, single broker class with flags  
**Consequences:** +extensibility, +testability, +separation of concerns

## ADR-005: Asyncio Over Threading

**Date:** 2026-07-01  
**Context:** WebSocket and periodic monitoring need concurrent I/O  
**Decision:** Use `asyncio` as the primary concurrency model  
**Alternatives:** threading, multiprocessing, trio  
**Consequences:** +efficient I/O, −learning curve, −CPU-bound limitations

## ADR-006: State Machine Enforced via Non-Raising `next_state`

**Date:** 2026-07-07  
**Context:** The state machine existed but was unused; the runner mutated `strategy_state`
directly and skipped `ENTERED`. Enforcing it with a raising `transition()` risked crashing a
live trade over a bookkeeping mismatch (e.g. re-entering `EXITING` on recovery).  
**Decision:** Route all runtime transitions through `next_state()`, which logs an unexpected
transition and applies it anyway (self-transitions allowed silently). Keep the raising
`transition()` for unit tests. Tighten transitions so a position-holding state must pass
through `EXITING` before `COMPLETED`.  
**Alternatives:** Raise on every invalid transition; leave the machine unused.  
**Consequences:** +invalid transitions surfaced in logs, +open legs can't be skipped;
−an anomaly is logged rather than hard-failed.

## ADR-007: Fail-Safe Stop-Loss on Missing Margin

**Date:** 2026-07-07  
**Context:** With `margin_used <= 0` the stop-loss percentage can't be sized, and the old
code returned "no exit" — running a naked short with zero downside protection.  
**Decision:** Treat a losing position with non-positive margin as a force-exit condition.
Prevent it upstream via config validation (`margin > 0`) and an entry abort when the margin
estimate is still non-positive.  
**Alternatives:** Skip the check (unprotected); halt the whole app.  
**Consequences:** +never runs unprotected; −may exit a position on a transient margin-read
failure (accepted as the safe default).

## ADR-008: Explicit `None` Checks Instead of `x or fallback`

**Date:** 2026-07-07  
**Context:** On expiry day a worthless leg settles at `0.0`, but `exit_price or current_price`
treats `0.0` as missing and computes P&L from a stale tick.  
**Decision:** Use explicit `is not None` checks wherever a legitimate `0.0` price/quantity can
occur (P&L, exit realization).  
**Alternatives:** Sentinel values; keep the truthy idiom.  
**Consequences:** +correct expiry-day P&L; −slightly more verbose.

## ADR-009: Margin Quantity in Shares, Not Lots

**Date:** 2026-07-07  
**Context:** Upstox `/charges/margin` rejected every request with `UDAPI1104 "Quantity should
be multiple of lot size"` because the bot sent raw lot counts; margin silently fell back to a
hardcoded value, mis-anchoring RoC and the stop-loss base.  
**Decision:** Send `lots × lot_size` (actual share quantity) in the margin request, matching
the real order/position sizing. Lot sizes stay config-driven (`NIFTY: 65`, `SENSEX: 20`).  
**Alternatives:** Post-scale in the broker layer; keep the fallback.  
**Consequences:** +true margin computed; −depends on correct configured lot sizes.

## ADR-010: Atomic DB Writes and Reset-able Singletons

**Date:** 2026-07-07  
**Context:** `execute()` + `commit()` took the shared cross-thread lock separately, so one
thread could commit another's pending write; process-global singletons also made the test
suite order-dependent.  
**Decision:** Add an atomic `execute_write()` (execute+commit under one lock span) used by all
repository writers, and `reset()` classmethods on the singletons driven by an autouse test
fixture.  
**Alternatives:** Per-thread connections; a full transaction context manager.  
**Consequences:** +write atomicity, +isolated tests; −writes serialize on one lock.
