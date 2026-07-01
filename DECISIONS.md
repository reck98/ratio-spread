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
