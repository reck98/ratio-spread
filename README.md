# Ratio Spread Bot

Fully automated expiry-day **Ratio Spread** algorithmic trading system for **NIFTY** and **SENSEX** weekly options.

**Mode:** Paper Trading (Version 1) — no real orders sent to broker.

---

## Prerequisites

- Python 3.12+
- Upstox API credentials (for WebSocket market data)
- Windows Task Scheduler (for daily 8 AM auto-start)

---

## Installation

```bash
# 1. Clone and enter the project
cd ratio-spread-bot

# 2. Install the package with dev dependencies
pip install -e ".[dev]"

# 3. Copy env template and fill in your Upstox credentials
copy .env.template .env
# Then edit .env with your API key, secret, and access token
```

---

## Configuration

### config.yaml (`config/config.yaml`)

All strategy parameters are here — no hardcoded values:

```yaml
trading:
  entry_time: "09:27:00"       # Entry time (IST)
  exit_time: "15:27:00"        # Scheduled exit time (IST)
  stop_loss_percent: 1.0       # Max loss % of margin
  strike_interval: 50          # ATM rounding interval
  buy_lots: 1                  # Lots to buy per leg
  sell_multiplier: 3           # Sell multiplier (1:3 ratio)

symbols:
  nifty:
    enabled: true
  sensex:
    enabled: true
```

### .env File

```env
UPSTOX_API_KEY=your_api_key_here
UPSTOX_API_SECRET=your_api_secret_here
UPSTOX_ACCESS_TOKEN=your_access_token_here
```

---

## Running the Engine

### Manual Start

```bash
python app/main.py
```

The system will:
1. Load config and connect to Upstox
2. Check if today is NIFTY expiry (falls back to SENSEX)
3. Wait until 09:27 IST
4. Construct and execute the ratio spread
5. Monitor MTM every second
6. Exit at 15:27 or on 1% stop-loss
7. Generate reports and shut down

### Scheduled Start (Windows Task Scheduler)

1. Open **Task Scheduler** → **Create Basic Task**
2. Trigger: **Daily** at **8:00 AM**
3. Action: **Start a program**
   - Program: `C:\path\to\python.exe`
   - Arguments: `app/main.py`
   - Start in: `C:\path\to\ratio-spread-bot`

The built-in safeguard ensures: if started after 09:32 (5 min grace), it skips trading.

---

## Viewing Reports

### Rich Console Reports

Reports are auto-printed to the console and saved as text files.

### Saved Report Files

```
reports/2026-07-01/
    pnl_report.txt       # PnL summary
    trade_report.txt     # Per-leg trade details
    session_report.txt   # Session statistics
    statistics.txt       # Win rate, max MTM, etc.
```

View them:

```bash
# PowerShell
Get-Content reports/2026-07-01/pnl_report.txt
Get-Content reports/2026-07-01/trade_report.txt
Get-Content reports/2026-07-01/statistics.txt
```

---

## Viewing Logs

```
logs/2026-07-01/
    strategy.log       # Strategy events (entry, exit, MTM)
    orders.log         # All order fills
    market_data.log    # Price updates
    websocket.log      # Connection status
    database.log       # DB operations
    reports.log        # Report generation
    error.log          # Errors and warnings
```

```bash
# Watch strategy logs in real-time
Get-Content logs/2026-07-01/strategy.log -Wait

# View today's errors
Get-Content logs/2026-07-01/error.log
```

---

## Database Queries

The SQLite database is at `data/trading.db`. Query it with `sqlite3` or any SQLite browser:

```bash
# Connect to the database
sqlite3 data/trading.db

# View all trading days
SELECT trading_date, instrument, total_profit, exit_reason FROM strategy_runs;

# PnL per day
SELECT trading_date, instrument, total_profit, margin_used,
       ROUND(total_profit / margin_used * 100, 2) AS return_pct
FROM strategy_runs
ORDER BY trading_date DESC;

# Per-day summary (includes gross profit/loss)
SELECT trading_date, instrument, gross_profit, gross_loss,
       net_profit, max_mtm, min_mtm, exit_reason
FROM daily_summary
ORDER BY trading_date DESC;

# All orders for a specific run
SELECT * FROM orders WHERE strategy_run_id = 1;

# MTM history (every second) for a run
SELECT timestamp, mtm, profit_percentage
FROM pnl_history
WHERE strategy_run_id = 1
ORDER BY timestamp;

# View configuration used for a run
SELECT config_json FROM configuration_snapshot WHERE strategy_run_id = 1;
```

---

## Development Commands

```bash
# Run all tests
pytest

# Run tests with verbose output
pytest -v

# Run a specific test file
pytest tests/test_pnl_engine.py -v

# Lint check
ruff check .

# Auto-fix lint issues
ruff check --fix .

# Type check
mypy .

# Format code
black .

# Full quality check (run before committing)
ruff check . && mypy . && pytest -q
```

---

## Project Structure

```
ratio-spread-bot/
├── app/                    # Application entry point
│   ├── main.py             # Start here
│   ├── startup.py          # Dependency injection
│   ├── scheduler.py        # Time triggers
│   └── shutdown.py         # Graceful shutdown
├── broker/                 # Upstox integration
│   ├── broker_interface.py # Abstract interface
│   ├── paper_broker.py     # Paper execution
│   ├── upstox_broker.py    # Upstox API
│   ├── websocket_client.py # Live market data
│   └── instrument_resolver.py
├── strategy/               # Trading logic
│   ├── base_strategy.py
│   └── ratio_spread.py     # Ratio spread implementation
├── engine/                 # Core engine
│   ├── strategy_runner.py  # Lifecycle coordinator
│   ├── pnl_engine.py       # MTM calculation
│   ├── risk_manager.py     # Stop-loss
│   ├── exit_manager.py     # Exit execution
│   ├── market_data_cache.py
│   └── strategy_state_machine.py
├── database/               # Persistence
│   ├── sqlite_manager.py
│   ├── repository.py
│   └── schema.sql
├── state/                  # Crash recovery
│   └── state_manager.py
├── reports/                # Rich CLI reports
├── utils/
│   ├── config.py           # Configuration loader
│   ├── logging.py          # Structured logging
│   └── models.py           # Pydantic domain models
├── tests/                  # Test suites
├── config/
│   └── config.yaml
├── .env.template
└── .gitignore
```

---

## Architecture

### Strategy Flow

```
08:00 Start (via Task Scheduler)
  → Initialize config, DB, WebSocket
  → Check NIFTY expiry → if not, check SENSEX
  → If no expiry today → shutdown

09:27 Enter ratio spread
  → Buy 1 ATM Call + 1 ATM Put
  → Sell 3 OTM Calls + 3 OTM Puts
  → Premium target = Buy Premium / 3

09:27 – 15:27 Monitor every second
  → Recalculate MTM
  → If loss >= 1% of margin → exit (stop-loss)

15:27 Exit all positions (if not already out)
  → Generate reports
  → Save state
  → Shutdown
```

### Crash Recovery

If the application crashes mid-session, restarting auto-detects the saved state in `state/position_state.json` and resumes monitoring without re-entering.
