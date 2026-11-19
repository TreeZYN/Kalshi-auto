"""
Simple maker / liquidity provision strategy.
Places conservative limit orders a few cents away from the mid.
Aims to earn the spread when filled, with tight risk controls upstream.
"""

from typing import List, Dict
from .base import BaseStrategy, TradeSignal
import logging

logger = logging.getLogger(__name__)


class MakerStrategy(BaseStrategy):
    def __init__(self):
        super().__init__("maker")

    def generate_signals(
        self,
        markets: List[Dict],
        orderbooks: Dict[str, Dict],
        positions: Dict,
        config: Dict,
    ) -> List[TradeSignal]:
        if not self.enabled:
            return []

        signals = []
        offset = config.get("price_offset_cents", 3) / 100.0
        size = float(config.get("default_order_size_contracts", 5))

        candidates = self.filter_markets(markets, config)

        for m in candidates[:15]:  # Limit number of simultaneous quotes
            ticker = m.get("ticker")
            if not ticker:
                continue

            # Prefer markets that are not extremely one-sided
            yes_bid = float(m.get("yes_bid_dollars") or m.get("yes_bid") or 0)
            yes_ask = float(m.get("yes_ask_dollars") or m.get("yes_ask") or 1)

            if yes_bid <= 0.02 or yes_ask >= 0.98:
                continue  # Too extreme, low edge for maker

            mid = (yes_bid + yes_ask) / 2.0
            spread = yes_ask - yes_bid
            if spread < 0.02:
                continue  # Tight market, harder for us

            # Place a bid below mid and an ask above mid
            bid_price = round(max(0.01, mid - offset), 4)
            ask_price = round(min(0.99, mid + offset), 4)

            # Only quote if we don't already have a large position
            pos_key = f"{ticker}:yes"
            current_pos = positions.get(pos_key)
            current_qty = current_pos.quantity if current_pos else 0

            if current_qty < size * 2:  # Room to buy more
                signals.append(TradeSignal(
                    ticker=ticker,
                    side="bid",
                    quantity=size,
                    price=bid_price,
                    reason=f"Maker bid @ {bid_price:.4f} (mid {mid:.4f})",
                    confidence=0.4,
                    notional=size * bid_price,
                ))

            if current_qty > -size * 2:
                signals.append(TradeSignal(
                    ticker=ticker,
                    side="ask",
                    quantity=size,
                    price=ask_price,
                    reason=f"Maker ask @ {ask_price:.4f} (mid {mid:.4f})",
                    confidence=0.4,
                    notional=size * ask_price,
                ))

        logger.info(f"MakerStrategy generated {len(signals)} signals from {len(candidates)} markets")
        return signals