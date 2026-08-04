# Changelog

## v0.3.0 (2026-08-04)

Added automated post-session Git commit execution (`GitCommitRunner`) after completed trading sessions.

### Added
- `GitCommitRunner` service (`engine/git_commit_runner.py`) to run `python scripts/git-commit.py` post-session.
- Execution safety features:
  - Interpreter binding via `sys.executable`.
  - Absolute script path resolution using `pathlib` relative to project root.
  - Subprocess timeout protection (60s default) with graceful exception catching.
  - Duration measurement using `time.perf_counter()`.
  - Exactly-once execution guarantee backed by an in-memory `run_id` idempotency guard (`_executed_run_ids`).
- Hook integration in `app/main.py` immediately following report generation (`_generate_reports`).
- Expanded test suite in `tests/test_git_commit_runner.py` covering scheduled exit, manual exit, stop-loss exit, non-trading days, timeouts, non-zero return codes, and crash recovery.

Stability, correctness, and safety remediation across the paper build (full audit → fixes).

### Fixed — P&L & risk correctness
- Worthless-leg settlement: a legitimate `0.0` exit price is no longer discarded as
  "missing" (explicit `is not None` checks in `pnl_engine` / `exit_manager`), so expiry-day
  realized P&L is correct.
- Stop-loss now fails safe: a losing position with `margin_used <= 0` forces an exit instead
  of running unprotected.
- Stop-loss is evaluated on every tick (`handle_tick`), not only on the monitor timer, so a
  fast adverse move can't slip between wakeups. Added a stale-feed warning.
- Margin API request now sends share quantity (`lots × lot_size`) instead of the raw lot
  count, fixing the `UDAPI1104 "Quantity should be multiple of lot size"` rejection that
  forced a hardcoded margin fallback.
- Sell-strike selection honours the configured `sell_multiplier` (was hardcoded to 3).
- MTM excursion metrics seed from the first observed MTM (no more `0.0` sentinel skew).

### Fixed — lifecycle & persistence
- Graceful `stop()` now exits open positions and finalizes rather than leaving naked shorts.
- Crash-during-exit is recoverable: `EXITING` is persisted before placing exit orders,
  already-closed legs are skipped on retry, and exit order IDs are unique
  (`EXIT_{run_id}_{key}_{ts}`).
- `run_strategy` refuses re-entry while a position is already live.
- `_finalize_session` is idempotent and skips DB writes when no run row was created.
- WebSocket receive loop is now a supervisory loop that survives reconnects (bounded backoff,
  frame-size cap); the `listen()` task is tracked and cancelled on shutdown.
- SQLite writes are atomic (`execute_write` under a single lock); connections close on
  re-init; `get_by_date` returns the latest run; `daily_summary` upsert keeps `instrument`.
- State file writes fsync (file + directory); corrupt state loads as a fresh start.
- Stale prior-day state is discarded using the configured timezone, closing any open
  positions first.

### Changed — state machine now enforced
- All state changes route through `StrategyStateMachine.next_state` (log-and-continue,
  never raises mid-trade); transitions tightened so a position-holding state cannot jump
  straight to `COMPLETED` without passing through `EXITING`. Added the `ENTERED` step.

### Config
- `TradingConfig` numeric fields validated (`gt=0`); `entry_time` must precede `exit_time`.
- Missing/zero `lot_size` aborts entry instead of silently defaulting to 1.

### Tests & tooling
- Added `tests/conftest.py` (singleton-reset fixtures + `temp_db`), `tests/test_repository.py`
  (persistence), `tests/test_exit_flow.py` (exit / stop-loss money path), and
  `tests/test_full_session.py` (full entry → monitor → exit session). Expanded PnL, risk,
  resolver, state-machine, and state-manager suites.
- `ruff check .`, `mypy .` (strict), and `pytest` all clean — 48 tests passing.

### Notes
- Live-broker paths (real order placement, auth validation, margin-failure handling,
  fabricated instrument keys) remain documented `# TODO(live):` stubs — the build is
  paper-only (v1).

## v0.1.0 (2026-07-01)

- Initial project structure
- Configuration module with YAML loader and Pydantic validation
- Logging module with per-day file separation
- SQLite database with WAL mode, schema, and repository pattern
- JSON state manager with atomic writes for crash recovery
- Upstox broker integration (paper trading mode)
- WebSocket client with connect, subscribe, listen, auto-reconnect
- Instrument resolver with weekly expiry detection and strike selection
- Paper broker with instant LTP execution
- PnL engine for position-level and portfolio MTM
- Risk manager with configurable stop-loss (1%)
- Exit manager for scheduled (15:27) and stop-loss exits
- Strategy state machine with validated transitions
- Strategy runner coordinating the full lifecycle
- Ratio Spread strategy implementation
- Scheduler for time-based triggers
- Rich CLI reports (PnL, trade, session, statistics)
- Application entry point with startup/shutdown and crash recovery
- Unit tests for all core modules
