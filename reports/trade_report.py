from pathlib import Path

from rich.console import Console
from rich.table import Table

from database.repository import OrderRepository, PositionRepository
from utils.logging import LogManager
from utils.models import StrategyContext


class TradeReport:
    def __init__(self, order_repo: OrderRepository, position_repo: PositionRepository) -> None:
        self._order_repo = order_repo
        self._position_repo = position_repo
        self._logger = LogManager.get_logger("reports")
        self._console = Console()

    def generate(self, context: StrategyContext, report_dir: str = "reports") -> None:
        report_path = Path(report_dir) / str(context.trading_date or "unknown") / "trade_report.txt"
        report_path.parent.mkdir(parents=True, exist_ok=True)

        table = Table(title=f"Trade Report — {context.trading_date}")
        table.add_column("Symbol", style="cyan")
        table.add_column("Side", style="yellow")
        table.add_column("Qty", justify="right")
        table.add_column("Entry", justify="right")
        table.add_column("Exit", justify="right")
        table.add_column("PnL", justify="right")

        with open(report_path, "w") as f:
            f.write(f"Trade Report — {context.trading_date}\n\n")
            f.write(f"{'Symbol':<25} {'Side':<6} {'Qty':<6} {'Entry':<10} {'Exit':<10} {'PnL':<10}\n")
            f.write("-" * 70 + "\n")

            for pos in context.positions:
                entry = pos.entry_price
                exit_px = pos.exit_price or pos.current_price
                pnl = pos.realized_pnl if pos.closed else 0
                table.add_row(pos.trading_symbol, pos.side.value, str(pos.quantity),
                              f"{entry:.2f}", f"{exit_px:.2f}", f"{pnl:.2f}")
                f.write(f"{pos.trading_symbol:<25} {pos.side.value:<6} {pos.quantity:<6} "
                        f"{entry:<10.2f} {exit_px:<10.2f} {pnl:<10.2f}\n")

            f.write(f"\nTotal PnL: Rs.{context.current_mtm:,.2f}\n")

        self._console.print(table)
        self._logger.info("Trade report saved to %s", report_path)
