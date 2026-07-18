# Architecture

## System Overview

Event-driven paper trading system for expiry-day NIFTY/SENSEX ratio spreads.

## Module Relationships

```
app/main.py (entry point)
  ├── app/startup.py     — dependency injection
  ├── app/scheduler.py   — time triggers
  ├── app/shutdown.py    — graceful shutdown
  │
  ├── strategy/
  │     ├── base_strategy.py    # Abstract base
  │     └── ratio_spread.py
  │           └── engine/strategy_runner.py
  │                 ├── engine/pnl_engine.py
  │                 ├── engine/risk_manager.py
  │                 ├── engine/exit_manager.py
  │                 ├── engine/market_data_cache.py
  │                 └── engine/strategy_state_machine.py
  │
  ├── broker/
  │     ├── broker_interface.py
  │     ├── upstox_broker.py
  │     ├── paper_broker.py
  │     ├── websocket_client.py
  │     ├── instrument_resolver.py
  │     └── MarketDataFeed_pb2.py   # Protobuf stubs
  │
  ├── database/
  │     ├── sqlite_manager.py
  │     └── repository.py
  │
  ├── state/state_manager.py
  ├── reports/ (4 report generators)
  └── utils/
        ├── config.py
        ├── logging.py
        └── models.py
```

## Data Flow

```
WebSocket Tick → MarketDataCache → StrategyRunner → PnLEngine → RiskManager → ExitManager
                                       ↓
                               StateManager (JSON)
                                       ↓
                                 SQLite (DB)
                                       ↓
                                 Reports (Rich)
```

## State Machine

```
IDLE → WAITING_FOR_ENTRY → SELECTING_INSTRUMENTS → BUILDING_POSITION → ENTERED → MONITORING → EXITING → COMPLETED
```

Transitions are enforced through `StrategyStateMachine` — the runner and exit manager route
every state change via `next_state()` (which logs an unexpected transition rather than
raising, so a bookkeeping mismatch never crashes a live trade).

`COMPLETED` is reachable directly only from the pre-position states
(`IDLE`, `WAITING_FOR_ENTRY`, `SELECTING_INSTRUMENTS`) for failure aborts. A position-holding
state (`BUILDING_POSITION`, `ENTERED`, `MONITORING`) must pass through `EXITING` first, so a
run is never marked complete while it still holds open legs.

## Configuration Flow

```
config.yaml → ConfigLoader (singleton) → AppConfig (Pydantic, immutable) → All modules
```
