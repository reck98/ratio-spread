from pathlib import Path

from rich.console import Console
from rich.table import Table

from utils.logging import LogManager
from utils.models import StrategyContext, StrategyMetrics


class SessionReport:
    def __init__(self) -> None:
        self._logger = LogManager.get_logger("reports")
        self._console = Console()

    def generate(self, context: StrategyContext, metrics: StrategyMetrics,
                 report_dir: str = "reports") -> None:
        report_path = Path(report_dir) / str(context.trading_date or "unknown") / "session_report.txt"
        report_path.parent.mkdir(parents=True, exist_ok=True)

        table = Table(title=f"Session Report — {context.trading_date}")
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="green")

        table.add_row("Strategy State", context.strategy_state.value)
        table.add_row("Exit Reason", context.exit_reason.value)
        table.add_row("Highest MTM", f"₹{metrics.highest_mtm:,.2f}")
        table.add_row("Lowest MTM", f"₹{metrics.lowest_mtm:,.2f}")
        table.add_row("Max Favorable Excursion", f"₹{metrics.max_favorable_excursion:,.2f}")
        table.add_row("Max Adverse Excursion", f"₹{metrics.max_adverse_excursion:,.2f}")
        table.add_row("Final PnL", f"₹{context.current_mtm:,.2f}")

        self._console.print(table)

        with open(report_path, "w") as f:
            f.write(f"Session Report — {context.trading_date}\n\n")
            f.write(f"Strategy State: {context.strategy_state.value}\n")
            f.write(f"Exit Reason: {context.exit_reason.value}\n")
            f.write(f"Highest MTM: Rs.{metrics.highest_mtm:,.2f}\n")
            f.write(f"Lowest MTM: Rs.{metrics.lowest_mtm:,.2f}\n")
            f.write(f"Max Favorable Excursion: Rs.{metrics.max_favorable_excursion:,.2f}\n")
            f.write(f"Max Adverse Excursion: Rs.{metrics.max_adverse_excursion:,.2f}\n")
            f.write(f"Final PnL: Rs.{context.current_mtm:,.2f}\n")

        self._logger.info("Session report saved to %s", report_path)
