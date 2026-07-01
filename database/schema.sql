PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_version (
    version TEXT PRIMARY KEY,
    applied_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS strategy_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trading_date DATE NOT NULL,
    instrument TEXT NOT NULL,
    expiry_date DATE NOT NULL,
    entry_time DATETIME,
    exit_time DATETIME,
    stop_loss_hit BOOLEAN DEFAULT 0,
    exit_reason TEXT DEFAULT 'NONE',
    total_profit REAL DEFAULT 0.0,
    margin_used REAL DEFAULT 0.0,
    strategy_version TEXT DEFAULT 'ratio_spread_v1.0',
    atm_strike INTEGER,
    sell_call_strike INTEGER,
    sell_put_strike INTEGER,
    max_mtm REAL DEFAULT 0.0,
    min_mtm REAL DEFAULT 0.0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS orders (
    order_id TEXT PRIMARY KEY,
    strategy_run_id INTEGER NOT NULL,
    instrument_key TEXT NOT NULL,
    trading_symbol TEXT NOT NULL,
    option_type TEXT NOT NULL,
    strike INTEGER NOT NULL,
    side TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    entry_price REAL NOT NULL,
    execution_time DATETIME NOT NULL,
    order_status TEXT DEFAULT 'FILLED',
    FOREIGN KEY (strategy_run_id) REFERENCES strategy_runs(id)
);

CREATE TABLE IF NOT EXISTS positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy_run_id INTEGER NOT NULL,
    instrument_key TEXT NOT NULL,
    trading_symbol TEXT NOT NULL,
    option_type TEXT NOT NULL,
    strike INTEGER NOT NULL,
    expiry DATE NOT NULL,
    side TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    entry_price REAL NOT NULL,
    exit_price REAL,
    realized_pnl REAL DEFAULT 0.0,
    closed BOOLEAN DEFAULT 0,
    FOREIGN KEY (strategy_run_id) REFERENCES strategy_runs(id)
);

CREATE TABLE IF NOT EXISTS pnl_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy_run_id INTEGER NOT NULL,
    timestamp DATETIME NOT NULL,
    mtm REAL NOT NULL,
    profit_percentage REAL NOT NULL,
    FOREIGN KEY (strategy_run_id) REFERENCES strategy_runs(id)
);

CREATE TABLE IF NOT EXISTS daily_summary (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trading_date DATE UNIQUE NOT NULL,
    instrument TEXT NOT NULL,
    gross_profit REAL DEFAULT 0.0,
    gross_loss REAL DEFAULT 0.0,
    net_profit REAL DEFAULT 0.0,
    max_mtm REAL DEFAULT 0.0,
    min_mtm REAL DEFAULT 0.0,
    exit_reason TEXT DEFAULT 'NONE',
    margin_used REAL DEFAULT 0.0,
    strategy_version TEXT DEFAULT 'ratio_spread_v1.0'
);

CREATE TABLE IF NOT EXISTS configuration_snapshot (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy_run_id INTEGER NOT NULL,
    config_json TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (strategy_run_id) REFERENCES strategy_runs(id)
);

CREATE INDEX IF NOT EXISTS idx_strategy_runs_date ON strategy_runs(trading_date);
CREATE INDEX IF NOT EXISTS idx_orders_run ON orders(strategy_run_id);
CREATE INDEX IF NOT EXISTS idx_pnl_history_run ON pnl_history(strategy_run_id);
CREATE INDEX IF NOT EXISTS idx_pnl_history_ts ON pnl_history(timestamp);
CREATE INDEX IF NOT EXISTS idx_daily_summary_date ON daily_summary(trading_date);
