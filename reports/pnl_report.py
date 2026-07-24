from pathlib import Path

from rich.console import Console
from rich.table import Table

from database.repository import DailySummaryRepository, StrategyRunRepository
from utils.logging import LogManager
from utils.models import StrategyContext


class PnLReport:
    def __init__(self, strategy_run_repo: StrategyRunRepository,
                 daily_summary_repo: DailySummaryRepository) -> None:
        self._run_repo = strategy_run_repo
        self._summary_repo = daily_summary_repo
        self._logger = LogManager.get_logger("reports")
        self._console = Console()

    def generate(self, context: StrategyContext, report_dir: str = "reports") -> None:
        report_path = Path(report_dir) / str(context.trading_date or "unknown") / "pnl_report.txt"
        report_path.parent.mkdir(parents=True, exist_ok=True)

        table = Table(title=f"PnL Report — {context.trading_date}")
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="green")

        table.add_row("Instrument", context.instrument.value if context.instrument else "N/A")
        table.add_row("ATM Strike", str(context.atm_strike or "N/A"))
        table.add_row("Sell Call Strike", str(context.sell_call_strike or "N/A"))
        table.add_row("Sell Put Strike", str(context.sell_put_strike or "N/A"))
        table.add_row("Entry Time", str(context.entry_time or "N/A"))
        table.add_row("Exit Time", str(context.exit_time or "N/A"))
        table.add_row("Margin Used", f"₹{context.margin_used:,.2f}")
        table.add_row("Final MTM", f"₹{context.current_mtm:,.2f}")
        table.add_row("Exit Reason", context.exit_reason.value)

        self._console.print(table)

        with open(report_path, "w") as f:
            f.write(f"PnL Report — {context.trading_date}\n")
            f.write(f"Instrument: {context.instrument.value if context.instrument else 'N/A'}\n")
            f.write(f"ATM Strike: {context.atm_strike}\n")
            f.write(f"Sell Call Strike: {context.sell_call_strike}\n")
            f.write(f"Sell Put Strike: {context.sell_put_strike}\n")
            f.write(f"Entry Time: {context.entry_time}\n")
            f.write(f"Exit Time: {context.exit_time}\n")
            f.write(f"Margin Used: Rs.{context.margin_used:,.2f}\n")
            f.write(f"Final MTM: Rs.{context.current_mtm:,.2f}\n")
            f.write(f"Exit Reason: {context.exit_reason.value}\n")

        self._logger.info("PnL report saved to %s", report_path)
