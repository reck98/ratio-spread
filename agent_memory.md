# Agent Memory

## Project Status

**Current Phase:** v1 paper build — implemented, audited, and remediated (2026-07-07)

**Completed Modules:**
- Configuration (config.yaml + Pydantic loader, validated numeric bounds, entry<exit)
- Logging (per-day file logging with independent loggers)
- Database (SQLite with WAL, repository pattern, atomic `execute_write`, schema)
- State Manager (JSON crash recovery, fsync durability, corrupt-load safe)
- Broker Layer (interface + Upstox broker, paper mode)
- WebSocket Manager (supervisory listen loop, bounded-backoff reconnect, frame cap)
- Instrument Resolver (expiry detection, ATM/sell strike selection via `sell_multiplier`)
- Paper Broker (instant fills at LTP)
- PnL Engine (position-level and portfolio MTM, correct on `0.0` settlement)
- Risk Manager (per-tick stop-loss at 1%, fail-safe on missing margin)
- Exit Manager (scheduled exit at 15:27, SL exit, crash-recoverable, unique order IDs)
- Strategy State Machine (enforced via `next_state`, tightened transitions)
- Strategy Runner (full lifecycle, re-entry guard, idempotent finalize)
- Ratio Spread Strategy (entry, monitoring, exit)
- Scheduler (time-based triggers, late-entry grace)
- Reports (PnL, Trade, Session, Statistics)
- Application Entry Point (startup, shutdown, main loop, crash recovery)
- Tests (9 suites incl. persistence, exit-flow, and full-session integration)

**Remaining (deferred):**
- Live trading adapter — documented `# TODO(live):` stubs (order placement, auth, margin)
- Telegram alerts, web dashboard, PostgreSQL, Docker, CI/CD (Low Priority backlog)

---

## Current Architecture

Event-driven, async (asyncio) paper trading system for NIFTY/SENSEX weekly expiry ratio spreads. Uses Upstox WebSocket for market data, SQLite for persistence, JSON for crash recovery, and Rich for CLI reporting.

---

## Recently Completed (2026-07-07 remediation)

- Full-project audit → fixes across P&L math, stop-loss/risk, and mid-session stability
- Worthless-leg (`0.0`) P&L correctness; fail-safe stop-loss; per-tick stop-loss evaluation
- Margin API quantity sent as `lots × lot_size` (fixes `UDAPI1104` rejection)
- Lifecycle hardening: graceful-stop exit, crash-during-exit recovery, unique exit IDs,
  re-entry guard, idempotent finalize
- WebSocket supervisory reconnect loop; tracked/cancelled `listen()` task
- Persistence: atomic writes, latest-run reads, `daily_summary` instrument-on-conflict,
  state-file fsync + corrupt-load safety, tz-aware stale-state discard
- State machine now enforced end-to-end; config numeric validation
- New/expanded test suites; `ruff` + `mypy --strict` + `pytest` all clean (48 tests)

See `CHANGELOG.md` (v0.2.0) and `DECISIONS.md` (ADR-006…010) for detail.

---

## Pending Tasks

- None blocking the paper build. Optional next step: drive a live paper session
  (`python app/main.py`) on an expiry day for a real end-to-end sanity check.
- User action item (not code): rotate the Upstox credentials in `.env`.

---

## Design Decisions

- **Pydantic v2** for all domain models and configuration (immutable, validated)
- **Repository pattern** for database access (future PostgreSQL migration)
- **Broker interface** pattern (future live trading / multi-broker)
- **JSON for crash recovery only**, SQLite for historical data
- **Atomic file writes + fsync** for the state file (write to .tmp, fsync, rename)
- **Atomic DB writes** via single-lock `execute_write` (repository writers)
- **Asyncio** as primary concurrency model (no threads)
- **Event-driven** via WebSocket ticks → Market Cache → PnL Engine → Risk Manager
- **State machine enforced** via non-raising `next_state` (log-and-continue)
- **Fail-safe stop-loss** when margin is missing; **explicit `None` checks** for `0.0` prices
- **Strategy versioning** via `strategy_version` column in DB

---

## Database Version

Schema Version: 1.0

---

## Configuration Version

1.0

---

## Next Recommended Task

Optionally run a live paper session (`python app/main.py`) on an expiry day to confirm the
end-to-end flow against the real market feed, then rotate the Upstox `.env` credentials.
