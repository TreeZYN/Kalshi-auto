"""
Simple paper trading engine.
Tracks virtual positions and P&L without sending real orders.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


@dataclass
class PaperPosition:
    ticker: str
    side: str           # "yes" or "no"
    quantity: float
    avg_price: float    # in dollars (0-1)
    realized_pnl: float = 0.0


@dataclass
class PaperOrder:
    client_order_id: str
    ticker: str
    side: str           # "bid" or "ask"
    quantity: float
    price: float
    status: str = "resting"  # resting, filled, cancelled
    created_at: datetime = field(default_factory=datetime.utcnow)
    filled_at: Optional[datetime] = None


class PaperEngine:
    def __init__(self, starting_balance: float = 1000.0):
        self.cash = starting_balance
        self.starting_balance = starting_balance
        self.positions: Dict[str, PaperPosition] = {}
        self.orders: Dict[str, PaperOrder] = {}
        self.trade_log: List[Dict] = []

    def place_order(
        self,
        ticker: str,
        side: str,
        quantity: float,
        price: float,
        client_order_id: str,
    ) -> Dict:
        """Simulate placing a limit order. Immediately 'fills' at the limit for simplicity
        in this educational version (real systems would track the book).
        """
        notional = quantity * price
        if side == "bid" and notional > self.cash:
            return {"error": "Insufficient paper cash"}

        order = PaperOrder(
            client_order_id=client_order_id,
            ticker=ticker,
            side=side,
            quantity=quantity,
            price=price,
        )
        self.orders[client_order_id] = order

        # Simple immediate fill simulation (for educational purposes)
        # In a real paper engine you would match against live book or delay fills
        self._fill_order(order)

        return {
            "order_id": client_order_id,
            "status": order.status,
            "ticker": ticker,
            "side": side,
            "quantity": quantity,
            "price": price,
        }

    def _fill_order(self, order: PaperOrder):
        qty = order.quantity
        px = order.price
        notional = qty * px

        if order.side == "bid":  # Buying YES
            self.cash -= notional
            key = f"{order.ticker}:yes"
            if key in self.positions:
                pos = self.positions[key]
                total_qty = pos.quantity + qty
                pos.avg_price = (pos.avg_price * pos.quantity + px * qty) / total_qty
                pos.quantity = total_qty
            else:
                self.positions[key] = PaperPosition(
                    ticker=order.ticker, side="yes", quantity=qty, avg_price=px
                )
        else:  # ask = selling YES
            key = f"{order.ticker}:yes"
            if key in self.positions and self.positions[key].quantity >= qty:
                pos = self.positions[key]
                pnl = (px - pos.avg_price) * qty
                pos.quantity -= qty
                pos.realized_pnl += pnl
                self.cash += notional
                if pos.quantity < 0.001:
                    del self.positions[key]
            else:
                # Short YES = long NO (simplified)
                key_no = f"{order.ticker}:no"
                # Treat as buying NO at (1 - price)
                no_price = 1.0 - px
                self.cash -= qty * no_price
                if key_no in self.positions:
                    pos = self.positions[key_no]
                    total_qty = pos.quantity + qty
                    pos.avg_price = (pos.avg_price * pos.quantity + no_price * qty) / total_qty
                    pos.quantity = total_qty
                else:
                    self.positions[key_no] = PaperPosition(
                        ticker=order.ticker, side="no", quantity=qty, avg_price=no_price
                    )

        order.status = "filled"
        order.filled_at = datetime.utcnow()

        self.trade_log.append({
            "time": order.filled_at.isoformat(),
            "ticker": order.ticker,
            "side": order.side,
            "qty": qty,
            "price": px,
            "client_order_id": order.client_order_id,
        })
        logger.info(f"PAPER FILL: {order.side} {qty} {order.ticker} @ {px:.4f}")

    def get_equity(self) -> float:
        """Rough equity = cash + mark-to-market of positions (using last known mid if available).
        For simplicity here we just return cash + cost basis.
        """
        pos_value = sum(p.quantity * p.avg_price for p in self.positions.values())
        return self.cash + pos_value

    def get_status(self) -> Dict:
        return {
            "cash": round(self.cash, 2),
            "equity": round(self.get_equity(), 2),
            "starting_balance": self.starting_balance,
            "unrealized_approx": round(self.get_equity() - self.starting_balance, 2),
            "num_positions": len(self.positions),
            "num_open_orders": len([o for o in self.orders.values() if o.status == "resting"]),
            "total_trades": len(self.trade_log),
        }