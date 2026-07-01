# Changelog

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
