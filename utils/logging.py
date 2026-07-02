import sys
from datetime import date
from logging import FileHandler, Formatter, Logger, StreamHandler, getLogger
from pathlib import Path


class LogManager:
    _loggers: dict[str, Logger] = {}

    @classmethod
    def initialize(cls, log_directory: str, trading_date: date, level: str = "INFO") -> None:
        log_dir = Path(log_directory) / trading_date.isoformat()
        log_dir.mkdir(parents=True, exist_ok=True)

        log_files = {
            "strategy": log_dir / "strategy.log",
            "orders": log_dir / "orders.log",
            "market_data": log_dir / "market_data.log",
            "websocket": log_dir / "websocket.log",
            "database": log_dir / "database.log",
            "reports": log_dir / "reports.log",
            "error": log_dir / "error.log",
        }

        formatter = Formatter("%(asctime)s %(levelname)-8s %(name)-15s %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

        root = getLogger()
        root.handlers.clear()
        root.setLevel(level.upper())

        console = StreamHandler(sys.stdout)
        console.setFormatter(formatter)
        console.setLevel(level.upper())
        root.addHandler(console)

        for name, log_file in log_files.items():
            logger = getLogger(name)
            logger.setLevel(level.upper())
            logger.handlers.clear()
            logger.propagate = True

            handler = FileHandler(log_file, encoding="utf-8")
            handler.setFormatter(formatter)
            logger.addHandler(handler)

            cls._loggers[name] = logger

    @classmethod
    def get_logger(cls, name: str) -> Logger:
        if name in cls._loggers:
            return cls._loggers[name]
        logger = getLogger(name)
        cls._loggers[name] = logger
        return logger
