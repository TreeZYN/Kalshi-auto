from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from dataclasses import dataclass


@dataclass
class TradeSignal:
    ticker: str
    side: str               # "bid" or "ask"
    quantity: float
    price: float            # dollars 0-1
    reason: str
    confidence: float = 0.5 # 0-1
    notional: float = 0.0


class BaseStrategy(ABC):
    def __init__(self, name: str):
        self.name = name
        self.enabled = True

    @abstractmethod
    def generate_signals(
        self,
        markets: List[Dict],
        orderbooks: Dict[str, Dict],
        positions: Dict,
        config: Dict,
    ) -> List[TradeSignal]:
        """Return list of TradeSignal objects."""
        pass

    def filter_markets(self, markets: List[Dict], config: Dict) -> List[Dict]:
        """Basic liquidity and series filters."""
        min_liq = config.get("min_liquidity_usd", 500)
        allowed = config.get("allowed_series") or []
        excluded = config.get("excluded_series") or []

        filtered = []
        for m in markets:
            ticker = m.get("ticker", "")
            series = m.get("series_ticker") or ticker.split("-")[0] if "-" in ticker else ""

            if allowed and series not in allowed and ticker not in allowed:
                continue
            if series in excluded or ticker in excluded:
                continue

            # Rough liquidity proxy
            volume = float(m.get("volume") or m.get("volume_fp") or 0)
            oi = float(m.get("open_interest") or m.get("open_interest_fp") or 0)
            if volume < min_liq and oi < min_liq:
                continue

            filtered.append(m)
        return filtered