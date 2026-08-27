from pathlib import Path

import pytest
import yaml

from utils.config import AppConfig, ConfigLoader


@pytest.fixture
def sample_config() -> dict[str, object]:
    return {
        "config_version": "1.0",
        "application": {"timezone": "Asia/Kolkata", "paper_trading": True},
        "broker": {"name": "upstox", "api_key": "", "api_secret": "", "access_token": ""},
        "strategy": {"name": "ratio_spread"},
        "trading": {
            "entry_time": "09:27:00",
            "exit_time": "15:13:00",
            "monitor_interval": 1,
            "stop_loss_percent": 1.0,
            "strike_interval": 50,
            "buy_lots": 1,
            "sell_multiplier": 3,
        },
        "symbols": {"nifty": {"enabled": True}, "sensex": {"enabled": True}},
        "database": {"sqlite_path": "data/test_trading.db"},
        "state": {"state_file": "state/test_state.json"},
        "logging": {"log_directory": "logs/", "level": "INFO"},
        "reports": {"directory": "reports/"},
    }


def test_config_loading(sample_config: dict[str, object], tmp_path: Path) -> None:
    config_path = tmp_path / "test_config.yaml"
    with open(config_path, "w") as f:
        yaml.dump(sample_config, f)

    loader = ConfigLoader()
    config = loader.load(str(config_path))
    assert isinstance(config, AppConfig)
    assert config.trading.entry_time == "09:27:00"
    assert config.trading.exit_time == "15:13:00"
    assert config.trading.stop_loss_percent == 1.0


def test_config_time_validation() -> None:
    with pytest.raises(Exception):
        AppConfig.model_validate({"trading": {"entry_time": "invalid"}})


def test_strike_rounding() -> None:
    config = AppConfig()
    strike = round(25124 / config.trading.strike_interval) * config.trading.strike_interval
    assert strike == 25100
    strike = round(25126 / config.trading.strike_interval) * config.trading.strike_interval
    assert strike == 25150
    strike = round(25174 / config.trading.strike_interval) * config.trading.strike_interval
    assert strike == 25150
    strike = round(25181 / config.trading.strike_interval) * config.trading.strike_interval
    assert strike == 25200
