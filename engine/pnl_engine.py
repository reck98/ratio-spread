from utils.logging import LogManager
from utils.models import Position, Side


class PnLEngine:
    def __init__(self) -> None:
        self._logger = LogManager.get_logger("strategy")

    def calculate_position_pnl(self, position: Position) -> float:
        if position.closed and position.exit_price is not None:
            # Use the realized exit price. A legitimate 0.0 (worthless expiry) must
            # NOT be treated as missing — expiry-day settlement to zero is the norm.
            current = position.exit_price
        else:
            current = position.current_price
        if position.side == Side.BUY:
            return (current - position.entry_price) * position.quantity
        else:
            return (position.entry_price - current) * position.quantity

    def calculate_total_mtm(self, positions: list[Position]) -> float:
        total = sum(self.calculate_position_pnl(p) for p in positions)
        return total

    def calculate_loss_percentage(self, current_mtm: float, margin_used: float) -> float:
        if margin_used <= 0 or current_mtm >= 0:
            return 0.0
        return abs(current_mtm) / margin_used * 100.0

    def update_position_prices(self, positions: list[Position], current_prices: dict[str, float]) -> None:
        for pos in positions:
            if pos.instrument_key in current_prices:
                pos.current_price = current_prices[pos.instrument_key]
                pos.unrealized_pnl = self.calculate_position_pnl(pos)

    def calculate_metrics(self, positions: list[Position], current_mtm: float) -> dict[str, float]:
        gross_profit = 0.0
        gross_loss = 0.0
        for p in positions:
            pnl = self.calculate_position_pnl(p)
            if pnl > 0:
                gross_profit += pnl
            else:
                gross_loss += abs(pnl)
        return {
            "gross_profit": gross_profit,
            "gross_loss": gross_loss,
            "net_profit": gross_profit - gross_loss,
            "current_mtm": current_mtm,
        }
