from pathlib import Path

from rich.console import Console
from rich.table import Table

from utils.logging import LogManager
from utils.models import StrategyContext, StrategyMetrics


class StatisticsReport:
    def __init__(self) -> None:
        self._logger = LogManager.get_logger("reports")
        self._console = Console()

    def generate(self, context: StrategyContext, metrics: StrategyMetrics,
                 report_dir: str = "reports") -> None:
        report_path = Path(report_dir) / str(context.trading_date or "unknown") / "statistics.txt"
        report_path.parent.mkdir(parents=True, exist_ok=True)

        table = Table(title=f"Statistics — {context.trading_date}")
        table.add_column("Statistic", style="cyan")
        table.add_column("Value", style="green")

        total_positions = len(context.positions)
        won = sum(1 for p in context.positions if p.realized_pnl > 0)
        lost = sum(1 for p in context.positions if p.realized_pnl < 0)

        win_rate = (won / total_positions * 100) if total_positions > 0 else 0.0

        table.add_row("Total Positions", str(total_positions))
        table.add_row("Won", str(won))
        table.add_row("Lost", str(lost))
        table.add_row("Win Rate", f"{win_rate:.1f}%")
        table.add_row("Gross PnL", f"₹{context.current_mtm:,.2f}")
        table.add_row("Margin Used", f"₹{context.margin_used:,.2f}")
        if context.margin_used > 0:
            roc = context.current_mtm / context.margin_used * 100
            table.add_row("Return on Capital", f"{roc:.2f}%")

        self._console.print(table)

        with open(report_path, "w") as f:
            f.write(f"Statistics — {context.trading_date}\n\n")
            f.write(f"Total Positions: {total_positions}\n")
            f.write(f"Won: {won}\n")
            f.write(f"Lost: {lost}\n")
            f.write(f"Win Rate: {win_rate:.1f}%\n")
            f.write(f"Gross PnL: Rs.{context.current_mtm:,.2f}\n")
            f.write(f"Margin Used: Rs.{context.margin_used:,.2f}\n")
            if context.margin_used > 0:
                f.write(f"Return on Capital: {roc:.2f}%\n")

        self._logger.info("Statistics report saved to %s", report_path)
