import sqlite3
from pathlib import Path
from statistics import mean, stdev
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

BASE = Path(__file__).resolve().parent.parent
DB_PATH = BASE / "data" / "trading.db"

console = Console()


def fmt_rs(value: float) -> str:
    if value > 0:
        return f"+Rs.{value:,.2f}"
    elif value < 0:
        return f"-Rs.{abs(value):,.2f}"
    return "Rs.0.00"


def read_data() -> dict[str, Any]:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute(
        """SELECT * FROM strategy_runs ORDER BY trading_date"""
    )
    runs = [dict(r) for r in cur.fetchall()]

    cur.execute(
        """SELECT p.* FROM positions p
           JOIN strategy_runs r ON p.strategy_run_id = r.id
           ORDER BY r.trading_date, p.id"""
    )
    positions = [dict(p) for p in cur.fetchall()]

    cur.execute(
        """SELECT * FROM daily_summary ORDER BY trading_date"""
    )
    summaries = {s["trading_date"]: dict(s) for s in cur.fetchall()}

    run_ids = [r["id"] for r in runs]
    pnl_history: dict[int, list[dict[str, Any]]] = {}
    for rid in run_ids:
        cur.execute(
            "SELECT mtm FROM pnl_history WHERE strategy_run_id = ? ORDER BY id",
            (rid,),
        )
        rows = cur.fetchall()
        pnl_history[rid] = [r["mtm"] for r in rows]

    conn.close()
    return {
        "runs": runs,
        "positions": positions,
        "summaries": summaries,
        "pnl_history": pnl_history,
    }


def compute_metrics(data: dict[str, Any]) -> dict[str, Any]:
    runs = data["runs"]

    if not runs:
        return {}

    total_profit = sum(r.get("total_profit", 0) or 0 for r in runs)
    total_margin = sum(r.get("margin_used", 0) or 0 for r in runs)

    winning = [r for r in runs if (r.get("total_profit") or 0) > 0]
    losing = [r for r in runs if (r.get("total_profit") or 0) < 0]
    win_count = len(winning)
    loss_count = len(losing)
    total_trades = len(runs)
    win_rate = (win_count / total_trades * 100) if total_trades > 0 else 0.0

    daily_returns = []
    for r in runs:
        margin = r.get("margin_used", 0) or 0
        profit = r.get("total_profit", 0) or 0
        if margin > 0:
            daily_returns.append(profit / margin * 100)

    avg_pnl = total_profit / total_trades if total_trades > 0 else 0.0
    best_day = max(runs, key=lambda r: r.get("total_profit", 0) or 0) if runs else None
    worst_day = min(runs, key=lambda r: r.get("total_profit", 0) or 0) if runs else None
    overall_roc = (total_profit / total_margin * 100) if total_margin > 0 else 0.0

    max_drawdown_pct = 0.0
    for rid, mtm_series in data["pnl_history"].items():
        run = next((r for r in runs if r["id"] == rid), None)
        margin = run["margin_used"] if run and run.get("margin_used") else 1
        peak = -1e9
        for mtm in mtm_series:
            if mtm > peak:
                peak = mtm
            if peak > margin * 0.01:
                dd = (peak - mtm) / margin * 100
                if dd > max_drawdown_pct:
                    max_drawdown_pct = dd

    sharp_ratio = None
    if len(daily_returns) >= 2:
        rf_daily = 0.05 / 252
        excess = [ret - rf_daily * 100 for ret in daily_returns]
        std_ret = stdev(excess)
        if std_ret > 0:
            sharp_ratio = mean(excess) / std_ret * (252 ** 0.5)

    return {
        "total_trades": total_trades,
        "win_count": win_count,
        "loss_count": loss_count,
        "win_rate": win_rate,
        "total_profit": total_profit,
        "avg_pnl": avg_pnl,
        "best_day": dict(best_day) if best_day else None,
        "worst_day": dict(worst_day) if worst_day else None,
        "total_margin": total_margin,
        "overall_roc": overall_roc,
        "max_drawdown_pct": max_drawdown_pct,
        "sharp_ratio": sharp_ratio,
    }


def render(data: dict[str, Any]) -> None:
    runs = data["runs"]
    metrics = compute_metrics(data)

    if not runs:
        console.print(Panel("No trading data found.", title="PnL Report"))
        return

    first_date = runs[0]["trading_date"]
    last_date = runs[-1]["trading_date"]

    header_panel = Panel(
        Text.from_markup(
            f"Period: [cyan]{first_date}[/] to [cyan]{last_date}[/]\n"
            f"Trading days: [yellow]{metrics['total_trades']}[/]"
        ),
        title="[bold]Overall PnL Report[/]",
        border_style="green",
    )
    console.print(header_panel)
    console.print()

    day_table = Table(
        title="Per-Day Summary",
        title_style="bold",
        header_style="bold cyan",
        border_style="blue",
    )
    day_table.add_column("Date", style="white")
    day_table.add_column("Instrument", style="yellow")
    day_table.add_column("Exit Reason")
    day_table.add_column("Margin", justify="right")
    day_table.add_column("Net PnL", justify="right")
    day_table.add_column("RoC", justify="right")
    day_table.add_column("Max DD", justify="right")

    for r in runs:
        dd = 0.0
        rid = r["id"]
        if rid in data["pnl_history"] and data["pnl_history"][rid]:
            mtm_series = data["pnl_history"][rid]
            peak = -1e9
            margin = r.get("margin_used", 0) or 1
            for mtm in mtm_series:
                if mtm > peak:
                    peak = mtm
                if peak > margin * 0.01:
                    dd_candidate = (peak - mtm) / margin * 100
                    if dd_candidate > dd:
                        dd = dd_candidate

        pnl = r.get("total_profit", 0) or 0
        margin = r.get("margin_used", 0) or 0
        roc = (pnl / margin * 100) if margin > 0 else 0.0
        pnl_str = Text(fmt_rs(pnl))
        pnl_str.stylize("green" if pnl >= 0 else "red")

        day_table.add_row(
            r["trading_date"],
            r.get("instrument", ""),
            r.get("exit_reason", ""),
            f"Rs.{margin:,.2f}" if margin >= 0 else f"-Rs.{abs(margin):,.2f}",
            pnl_str,
            f"{roc:+.2f}%",
            f"{dd:.2f}%",
        )

    console.print(day_table)
    console.print()

    if data["positions"]:
        pos_table = Table(
            title="Position Breakdown",
            title_style="bold",
            header_style="bold cyan",
            border_style="blue",
        )
        pos_table.add_column("Date", style="white")
        pos_table.add_column("Symbol", style="yellow")
        pos_table.add_column("Side")
        pos_table.add_column("Qty", justify="right")
        pos_table.add_column("Entry", justify="right")
        pos_table.add_column("Exit", justify="right")
        pos_table.add_column("PnL", justify="right")

        run_lookup = {r["id"]: r for r in runs}
        for p in data["positions"]:
            run = run_lookup.get(p.get("strategy_run_id", 0))
            pnl = p.get("realized_pnl", 0) or 0
            pnl_text = Text(fmt_rs(pnl))
            pnl_text.stylize("green" if pnl >= 0 else "red")
            pos_table.add_row(
                run["trading_date"] if run else "",
                p.get("trading_symbol", ""),
                p.get("side", ""),
                str(p.get("quantity", 0)),
                f"{p.get('entry_price', 0):.2f}",
                f"{p.get('exit_price', 0):.2f}" if p.get("exit_price") else "N/A",
                pnl_text,
            )

        console.print(pos_table)
        console.print()

    stat_table = Table(
        title="Overall Statistics",
        title_style="bold",
        header_style="bold cyan",
        border_style="blue",
        show_header=False,
    )
    stat_table.add_column("Metric", style="white")
    stat_table.add_column("Value", style="green")

    stat_table.add_row("Total Trades", str(metrics["total_trades"]))
    stat_table.add_row(
        "Winning / Losing",
        f"{metrics['win_count']} ({metrics['win_rate']:.1f}%) / {metrics['loss_count']}",
    )
    stat_table.add_row("Total PnL", fmt_rs(metrics["total_profit"]))
    stat_table.add_row("Average PnL / Day", fmt_rs(metrics["avg_pnl"]))
    if metrics["best_day"]:
        stat_table.add_row(
            "Best Day",
            f"{fmt_rs(metrics['best_day']['total_profit'])} ({metrics['best_day']['trading_date']})",
        )
    if metrics["worst_day"]:
        stat_table.add_row(
            "Worst Day",
            f"{fmt_rs(metrics['worst_day']['total_profit'])} ({metrics['worst_day']['trading_date']})",
        )
    stat_table.add_row("Total Margin Deployed", f"Rs.{metrics['total_margin']:,.2f}")
    stat_table.add_row("Return on Capital", f"{metrics['overall_roc']:.2f}%")
    stat_table.add_row("Max Drawdown", f"{metrics['max_drawdown_pct']:.2f}%")
    sharpe_str = f"{metrics['sharp_ratio']:.2f}" if metrics["sharp_ratio"] is not None else "N/A (< 2 days)"
    stat_table.add_row("Sharpe Ratio (ann.)", sharpe_str)

    console.print(stat_table)


def main() -> None:
    data = read_data()
    render(data)


if __name__ == "__main__":
    main()
