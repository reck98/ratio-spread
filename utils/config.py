import os
from datetime import time
from pathlib import Path
from typing import Optional

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator, model_validator


class ApplicationConfig(BaseModel):
    timezone: str = "Asia/Kolkata"
    paper_trading: bool = True


class BrokerConfig(BaseModel):
    name: str = "upstox"
    api_key: str = ""
    api_secret: str = ""
    access_token: str = ""


class StrategyConfig(BaseModel):
    name: str = "ratio_spread"


class TradingConfig(BaseModel):
    margin: float = Field(default=650000.0, gt=0)
    entry_time: str = "09:27:00"
    exit_time: str = "15:13:00"
    monitor_interval: int = Field(default=1, gt=0)
    stop_loss_percent: float = Field(default=1.0, gt=0)
    strike_interval: int = Field(default=50, gt=0)
    buy_lots: int = Field(default=1, gt=0)
    sell_multiplier: int = Field(default=3, gt=0)
    lot_sizes: dict[str, int] = Field(default_factory=lambda: {"NIFTY": 65, "SENSEX": 20})

    @field_validator("entry_time", "exit_time")
    @classmethod
    def validate_time_format(cls, v: str) -> str:
        try:
            time.fromisoformat(v)
        except ValueError:
            raise ValueError(f"Time must be in HH:MM:SS format: {v}")
        return v

    @model_validator(mode="after")
    def validate_entry_before_exit(self) -> "TradingConfig":
        if self.entry_time_obj() >= self.exit_time_obj():
            raise ValueError(
                f"entry_time ({self.entry_time}) must be before exit_time ({self.exit_time})"
            )
        return self

    def entry_time_obj(self) -> time:
        return time.fromisoformat(self.entry_time)

    def exit_time_obj(self) -> time:
        return time.fromisoformat(self.exit_time)


class SymbolConfig(BaseModel):
    enabled: bool = True


class SymbolsConfig(BaseModel):
    nifty: SymbolConfig = Field(default_factory=lambda: SymbolConfig(enabled=True))
    sensex: SymbolConfig = Field(default_factory=lambda: SymbolConfig(enabled=True))


class DatabaseConfig(BaseModel):
    sqlite_path: str = "data/trading.db"


class StateConfig(BaseModel):
    state_file: str = "state/position_state.json"
    control_file: str = "state/control.json"


class LoggingConfig(BaseModel):
    log_directory: str = "logs/"
    level: str = "INFO"


class ReportsConfig(BaseModel):
    directory: str = "reports/"


class AppConfig(BaseModel):
    config_version: str = "1.0"
    application: ApplicationConfig = Field(default_factory=ApplicationConfig)
    broker: BrokerConfig = Field(default_factory=BrokerConfig)
    strategy: StrategyConfig = Field(default_factory=StrategyConfig)
    trading: TradingConfig = Field(default_factory=TradingConfig)
    symbols: SymbolsConfig = Field(default_factory=SymbolsConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    state: StateConfig = Field(default_factory=StateConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    reports: ReportsConfig = Field(default_factory=ReportsConfig)

    def validate_paths(self) -> None:
        Path(self.database.sqlite_path).parent.mkdir(parents=True, exist_ok=True)
        Path(self.state.state_file).parent.mkdir(parents=True, exist_ok=True)
        Path(self.logging.log_directory).mkdir(parents=True, exist_ok=True)
        Path(self.reports.directory).mkdir(parents=True, exist_ok=True)


class ConfigLoader:
    _instance: Optional["ConfigLoader"] = None
    _config: Optional[AppConfig] = None

    def __new__(cls) -> "ConfigLoader":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Drop the cached singleton/config (used by tests to avoid cross-test leakage)."""
        cls._instance = None
        cls._config = None

    def load(
        self, path: str = "config/config.yaml", env_path: str = ".env", reload: bool = False,
    ) -> AppConfig:
        if self._config is not None and not reload:
            return self._config

        config_path = Path(path)
        if not config_path.exists():
            raise FileNotFoundError(f"Configuration file not found: {path}")

        with open(config_path, "r") as f:
            raw = yaml.safe_load(f)

        load_dotenv(dotenv_path=env_path)

        broker = raw.setdefault("broker", {})
        broker.setdefault("api_key", os.getenv("UPSTOX_API_KEY", ""))
        broker.setdefault("api_secret", os.getenv("UPSTOX_API_SECRET", ""))
        broker.setdefault("access_token", os.getenv("UPSTOX_ACCESS_TOKEN", ""))

        self._config = AppConfig.model_validate(raw)
        self._config.validate_paths()
        return self._config

    @property
    def config(self) -> AppConfig:
        if self._config is None:
            raise RuntimeError("Configuration not loaded. Call load() first.")
        return self._config
