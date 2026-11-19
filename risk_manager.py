"""
Hard risk controls. These are not suggestions — they block trades.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional
from datetime import datetime, date
import logging

logger = logging.getLogger(__name__)


@dataclass
class RiskState:
    bankroll: float
    daily_pnl: float = 0.0
    open_exposure: float = 0.0
    positions: Dict[str, float] = field(default_factory=dict)  # ticker -> notional
    orders_this_hour: int = 0
    last_hour_reset: datetime = field(default_factory=datetime.utcnow)
    trading_halted_today: bool = False
    halt_reason: str = ""


class RiskManager:
    def __init__(
        self,
        bankroll: float,
        max_position_pct: float = 0.015,
        max_total_exposure_pct: float = 0.15,
        daily_loss_limit_pct: float = 0.04,
        max_orders_per_hour: int = 20,
    ):
        self.bankroll = bankroll
        self.max_position_pct = max_position_pct
        self.max_total_exposure_pct = max_total_exposure_pct
        self.daily_loss_limit_pct = daily_loss_limit_pct
        self.max_orders_per_hour = max_orders_per_hour

        self.state = RiskState(bankroll=bankroll)
        self._current_day = date.today()

    def _reset_daily_if_needed(self):
        today = date.today()
        if today != self._current_day:
            self.state.daily_pnl = 0.0
            self.state.trading_halted_today = False
            self.state.halt_reason = ""
            self._current_day = today
            logger.info("New trading day — risk counters reset")

    def _reset_hourly_if_needed(self):
        now = datetime.utcnow()
        if (now - self.state.last_hour_reset).total_seconds() >= 3600:
            self.state.orders_this_hour = 0
            self.state.last_hour_reset = now

    def update_pnl(self, realized_pnl: float):
        self._reset_daily_if_needed()
        self.state.daily_pnl += realized_pnl
        if self.state.daily_pnl <= -self.bankroll * self.daily_loss_limit_pct:
            self.state.trading_halted_today = True
            self.state.halt_reason = f"Daily loss limit hit: {self.state.daily_pnl:.2f}"
            logger.warning(self.state.halt_reason)

    def update_exposure(self, ticker: str, notional: float):
        """Update open exposure for a ticker (positive = long notional)."""
        old = self.state.positions.get(ticker, 0.0)
        self.state.positions[ticker] = notional
        self.state.open_exposure = self.state.open_exposure - abs(old) + abs(notional)

    def can_place_order(
        self,
        ticker: str,
        order_notional: float,
        is_new_position: bool = True,
    ) -> tuple[bool, str]:
        """
        Returns (allowed: bool, reason: str)
        """
        self._reset_daily_if_needed()
        self._reset_hourly_if_needed()

        if self.state.trading_halted_today:
            return False, self.state.halt_reason

        if self.state.orders_this_hour >= self.max_orders_per_hour:
            return False, f"Hourly order limit reached ({self.max_orders_per_hour})"

        max_pos = self.bankroll * self.max_position_pct
        if order_notional > max_pos:
            return False, f"Order notional ${order_notional:.2f} exceeds max position ${max_pos:.2f}"

        # Projected total exposure
        projected = self.state.open_exposure
        if is_new_position:
            projected += order_notional
        else:
            # For adds, be conservative
            projected += order_notional

        max_exposure = self.bankroll * self.max_total_exposure_pct
        if projected > max_exposure:
            return False, f"Projected exposure ${projected:.2f} exceeds max ${max_exposure:.2f}"

        return True, "OK"

    def record_order(self):
        self.state.orders_this_hour += 1

    def get_status(self) -> Dict:
        self._reset_daily_if_needed()
        return {
            "bankroll": self.bankroll,
            "daily_pnl": round(self.state.daily_pnl, 2),
            "open_exposure": round(self.state.open_exposure, 2),
            "exposure_pct": round(self.state.open_exposure / self.bankroll * 100, 2),
            "orders_this_hour": self.state.orders_this_hour,
            "trading_halted": self.state.trading_halted_today,
            "halt_reason": self.state.halt_reason,
            "num_positions": len([v for v in self.state.positions.values() if abs(v) > 0.01]),
        }