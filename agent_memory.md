# Agent Memory

## Project Status

**Current Phase:** Complete — Version 1 Implementation

**Completed Modules:**
- Configuration (config.yaml + Pydantic loader)
- Logging (per-day file logging with independent loggers)
- Database (SQLite with WAL, repository pattern, schema)
- State Manager (JSON crash recovery with atomic writes)
- Broker Layer (interface + Upstox broker)
- WebSocket Manager (connect, subscribe, listen, reconnect)
- Instrument Resolver (expiry detection, ATM/sell strike selection)
- Paper Broker (instant fills at LTP)
- PnL Engine (position-level and portfolio MTM)
- Risk Manager (stop-loss at 1%, exit decisions)
- Exit Manager (scheduled exit at 15:27, SL exit)
- Strategy State Machine (validated transitions)
- Strategy Runner (full lifecycle coordination)
- Ratio Spread Strategy (entry, monitoring, exit)
- Scheduler (time-based triggers)
- Reports (PnL, Trade, Session, Statistics)
- Application Entry Point (startup, shutdown, main loop)
- Unit Tests (config, PnL, risk, state machine, resolver, state)

**Remaining Modules:**
- Integration tests (manual verification recommended)
- Live trading adapter (future)
- Dashboard (future)

---

## Current Architecture

Event-driven, async (asyncio) paper trading system for NIFTY/SENSEX weekly expiry ratio spreads. Uses Upstox WebSocket for market data, SQLite for persistence, JSON for crash recovery, and Rich for CLI reporting.

---

## Recently Completed

- Full project structure with 12+ modules
- Core domain models (Pydantic)
- Configuration loader with validation
- SQLite database with WAL mode and repository pattern
- JSON state manager with atomic writes
- Upstox broker integration (paper mode)
- WebSocket client with auto-reconnect
- Instrument resolver with ATM/sell strike selection
- PnL engine, risk manager, exit manager
- Strategy state machine
- Full strategy runner (entry, monitoring, MTM, exit)
- Scheduler for timed execution
- Rich CLI reports (PnL, trade, session, statistics)
- Application main loop with crash recovery
- 6 test suites (config, PnL, risk, state machine, resolver, state)

---

## Pending Tasks

1. Run `ruff check` and `mypy` to verify code quality
2. Run `pytest` to verify all tests pass
3. Install dependencies via `pip install -e ".[dev]"`
4. Manual end-to-end verification of the paper trading flow

---

## Design Decisions

- **Pydantic v2** for all domain models and configuration (immutable, validated)
- **Repository pattern** for database access (future PostgreSQL migration)
- **Broker interface** pattern (future live trading / multi-broker)
- **JSON for crash recovery only**, SQLite for historical data
- **Atomic file writes** for state file (write to .tmp, rename)
- **Asyncio** as primary concurrency model (no threads)
- **Event-driven** via WebSocket ticks → Market Cache → PnL Engine → Risk Manager
- **Strategy versioning** via `strategy_version` column in DB

---

## Database Version

Schema Version: 1.0

---

## Configuration Version

1.0

---

## Next Recommended Task

Run `pip install -e ".[dev]"` then `pytest` to verify all tests pass, followed by `ruff check .` and `mypy .` to ensure code quality.
