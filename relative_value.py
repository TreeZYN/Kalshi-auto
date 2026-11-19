"""
Very simple relative-value / structural check.
Looks for related markets that violate basic arbitrage bounds.
This is educational — real RV requires deeper modeling of the event graph.
"""

from typing import List, Dict
from .base import BaseStrategy, TradeSignal
import logging

logger = logging.getLogger(__name__)


class RelativeValueStrategy(BaseStrategy):
    def __init__(self):
        super().__init__("relative_value")

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
        # This is a placeholder. Real relative value needs:
        # - Proper event / series grouping
        # - Logical relationships (e.g. "Team A wins" + "Team B wins" should sum ~1 for binary)
        # - For multi-outcome, probabilities should sum near 1 after fees

        # Example heuristic: within the same series, look for obvious inconsistencies
        # (very simplified — do not rely on this alone)

        by_series: Dict[str, List] = {}
        for m in markets:
            series = m.get("series_ticker") or "unknown"
            by_series.setdefault(series, []).append(m)

        for series, group in by_series.items():
            if len(group) < 2:
                continue
            # Example: if two mutually exclusive outcomes both trade high
            # This is just illustrative
            high_yes = [m for m in group if float(m.get("yes_bid_dollars") or 0) > 0.70]
            if len(high_yes) >= 2:
                # Potential overpricing — could sell the richer one
                richest = max(high_yes, key=lambda x: float(x.get("yes_bid_dollars") or 0))
                ticker = richest.get("ticker")
                bid = float(richest.get("yes_bid_dollars") or 0)
                if bid > 0.75:
                    size = float(config.get("default_order_size_contracts", 5))
                    signals.append(TradeSignal(
                        ticker=ticker,
                        side="ask",
                        quantity=size,
                        price=round(bid - 0.02, 4),
                        reason=f"RV: multiple high YES in {series}, selling richest",
                        confidence=0.35,
                        notional=size * (bid - 0.02),
                    ))

        logger.info(f"RelativeValueStrategy generated {len(signals)} signals")
        return signals