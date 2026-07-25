from datetime import date

from broker.instrument_resolver import InstrumentResolver
from broker.paper_broker import PaperBroker
from broker.upstox_broker import UpstoxBroker
from broker.websocket_client import WebSocketManager
from database.repository import (
    ConfigSnapshotRepository,
    DailySummaryRepository,
    OrderRepository,
    PnLHistoryRepository,
    PositionRepository,
    StrategyRunRepository,
)
from database.sqlite_manager import SQLiteManager
from engine.exit_manager import ExitManager
from engine.market_data_cache import MarketDataCache
from engine.pnl_engine import PnLEngine
from engine.risk_manager import RiskManager
from engine.strategy_runner import StrategyRunner
from reports.pnl_report import PnLReport
from reports.session_report import SessionReport
from reports.statistics import StatisticsReport
from reports.trade_report import TradeReport
from state.control_manager import ControlManager
from state.state_manager import StateManager
from strategy.ratio_spread import RatioSpreadStrategy
from utils.config import AppConfig, ConfigLoader
from utils.logging import LogManager


class ApplicationComponents:
    def __init__(self) -> None:
        self.config: AppConfig
        self.db: SQLiteManager
        self.market_cache: MarketDataCache
        self.pnl_engine: PnLEngine
        self.risk_manager: RiskManager
        self.state_manager: StateManager
        self.control_manager: ControlManager
        self.upstox_broker: UpstoxBroker
        self.paper_broker: PaperBroker
        self.instrument_resolver: InstrumentResolver
        self.websocket_manager: WebSocketManager
        self.strategy: RatioSpreadStrategy
        self.strategy_run_repo: StrategyRunRepository
        self.order_repo: OrderRepository
        self.position_repo: PositionRepository
        self.pnl_history_repo: PnLHistoryRepository
        self.daily_summary_repo: DailySummaryRepository
        self.config_snapshot_repo: ConfigSnapshotRepository
        self.pnl_report: PnLReport
        self.trade_report: TradeReport
        self.session_report: SessionReport
        self.statistics_report: StatisticsReport


class Startup:
    @staticmethod
    async def initialize() -> ApplicationComponents:
        loader = ConfigLoader()
        config = loader.load()

        trading_date = date.today()
        LogManager.initialize(config.logging.log_directory, trading_date, config.logging.level)
        logger = LogManager.get_logger("startup")
        logger.info("Starting Ratio Spread Bot v0.1.0")

        components = ApplicationComponents()
        components.config = config

        db: SQLiteManager | None = None
        upstox: UpstoxBroker | None = None
        try:
            db = SQLiteManager()
            db.initialize(config.database.sqlite_path)
            components.db = db
            logger.info("Database initialized")

            components.market_cache = MarketDataCache()
            components.pnl_engine = PnLEngine()
            components.risk_manager = RiskManager(config.trading.stop_loss_percent)

            state_manager = StateManager()
            state_manager.initialize(config.state.state_file)
            components.state_manager = state_manager
            logger.info("State manager initialized")

            control_manager = ControlManager(
                control_file_path=config.state.control_file,
                logger=logger,
            )
            components.control_manager = control_manager
            logger.info("Control manager initialized")

            upstox = UpstoxBroker(config)
            await upstox.connect()
            await upstox.authenticate()
            components.upstox_broker = upstox

            paper_broker = PaperBroker(upstox, margin=config.trading.margin)
            await paper_broker.connect()
            components.paper_broker = paper_broker
        except Exception as e:
            logger.exception("Startup failed during initialization: %s", e)
            # Release resources opened before the failure so we don't leak the DB
            # connection or the aiohttp session.
            if upstox is not None:
                await upstox.disconnect()
            if db is not None:
                db.close()
            raise

        components.instrument_resolver = InstrumentResolver(paper_broker)

        ws = WebSocketManager(config.broker.access_token)
        components.websocket_manager = ws

        components.strategy_run_repo = StrategyRunRepository(db)
        components.order_repo = OrderRepository(db)
        components.position_repo = PositionRepository(db)
        components.pnl_history_repo = PnLHistoryRepository(db)
        components.daily_summary_repo = DailySummaryRepository(db)
        components.config_snapshot_repo = ConfigSnapshotRepository(db)

        exit_manager = ExitManager(
            broker=paper_broker,
            pnl_engine=components.pnl_engine,
            market_cache=components.market_cache,
            state_manager=state_manager,
            order_repo=components.order_repo,
            position_repo=components.position_repo,
        )

        runner = StrategyRunner(
            config=config,
            broker=paper_broker,
            instrument_resolver=components.instrument_resolver,
            market_cache=components.market_cache,
            pnl_engine=components.pnl_engine,
            risk_manager=components.risk_manager,
            exit_manager=exit_manager,
            state_manager=state_manager,
            control_manager=control_manager,
            strategy_run_repo=components.strategy_run_repo,
            order_repo=components.order_repo,
            position_repo=components.position_repo,
            pnl_history_repo=components.pnl_history_repo,
            daily_summary_repo=components.daily_summary_repo,
            config_snapshot_repo=components.config_snapshot_repo,
        )

        components.strategy = RatioSpreadStrategy(runner=runner)

        components.pnl_report = PnLReport(components.strategy_run_repo, components.daily_summary_repo)
        components.trade_report = TradeReport(components.order_repo, components.position_repo)
        components.session_report = SessionReport()
        components.statistics_report = StatisticsReport()

        logger.info("Startup complete")
        return components
