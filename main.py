#!/usr/bin/env python3
"""
Kalshi Low-Effort Auto Trader
=============================
Demo + Paper trading by default.
Strong risk controls.
"""

import os
import sys
import time
import yaml
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, List

from rich.console import Console
from rich.table import Table
from rich.live import Live
from rich.panel import Panel

from kalshi_client import KalshiClient
from risk_manager import RiskManager
from paper_engine import PaperEngine
from strategies.maker import MakerStrategy
from strategies.relative_value import RelativeValueStrategy

console = Console()


def setup_logging(config: Dict):
    log_file = config.get("log_file", "logs/trader.log")
    Path(log_file).parent.mkdir(parents=True, exist_ok=True)
    level = getattr(logging, config.get("log_level", "INFO").upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler(sys.stdout),
        ],
    )
    return logging.getLogger("main")


def load_config(path: str = "config.yaml") -> Dict:
    if not Path(path).exists():
        console.print(f"[red]Config file {path} not found. Copy config.example.yaml to config.yaml and edit it.[/red]")
        sys.exit(1)
    with open(path) as f:
        return yaml.safe_load(f)


def print_banner(config: Dict):
    mode = []
    if config.get("use_demo", True):
        mode.append("DEMO")
    else:
        mode.append("PRODUCTION")
    if config.get("paper_trading", True):
        mode.append("PAPER")
    if config.get("live_trading", False):
        mode.append("LIVE ORDERS ENABLED")
    else:
        mode.append("NO LIVE ORDERS")

    console.print(Panel.fit(
        f"[bold]Kalshi Auto Trader[/bold]\n"
        f"Mode: {' + '.join(mode)}\n"
        f"Bankroll: ${config.get('bankroll_usd', 0):,.0f}\n"
        f"[yellow]This does not guarantee profits. You can lose money.[/yellow]",
        title="Starting",
        border_style="cyan",
    ))


def main():
    config = load_config()
    logger = setup_logging(config)
    print_banner(config)

    # Safety gate
    if config.get("live_trading") and not config.get("use_demo"):
        if config.get("require_manual_confirm_live", True):
            console.print("[bold red]LIVE PRODUCTION TRADING REQUESTED[/bold red]")
            confirm = input("Type 'I UNDERSTAND THE RISKS' to continue: ")
            if confirm.strip() != "I UNDERSTAND THE RISKS":
                console.print("Aborting.")
                sys.exit(0)

    client = KalshiClient(
        api_key_id=config.get("api_key_id") or "",
        private_key_path=config.get("private_key_path") or "",
        use_demo=config.get("use_demo", True),
    )

    risk = RiskManager(
        bankroll=float(config.get("bankroll_usd", 1000)),
        max_position_pct=float(config.get("max_position_pct", 0.015)),
        max_total_exposure_pct=float(config.get("max_total_exposure_pct", 0.15)),
        daily_loss_limit_pct=float(config.get("daily_loss_limit_pct", 0.04)),
        max_orders_per_hour=int(config.get("max_orders_per_hour", 20)),
    )

    paper = PaperEngine(starting_balance=float(config.get("bankroll_usd", 1000)))

    strategies = []
    if config.get("enable_maker_strategy", True):
        strategies.append(MakerStrategy())
    if config.get("enable_relative_value", True):
        strategies.append(RelativeValueStrategy())

    logger.info(f"Loaded {len(strategies)} strategies")
    interval = int(config.get("scan_interval_seconds", 60))

    console.print(f"\n[green]Running every {interval}s. Press Ctrl+C to stop cleanly.[/green]\n")

    cycle = 0
    try:
        while True:
            cycle += 1
            logger.info(f"=== Cycle {cycle} ===")

            # 1. Fetch markets
            try:
                markets_resp = client.get_markets(status="open", limit=100)
                markets = markets_resp.get("markets", [])
                logger.info(f"Fetched {len(markets)} open markets")
            except Exception as e:
                logger.error(f"Failed to fetch markets: {e}")
                time.sleep(interval)
                continue

            # 2. Generate signals
            all_signals = []
            orderbooks = {}  # Can be expanded to fetch real books
            positions = paper.positions if config.get("paper_trading") else {}

            for strat in strategies:
                try:
                    sigs = strat.generate_signals(markets, orderbooks, positions, config)
                    all_signals.extend(sigs)
                except Exception as e:
                    logger.error(f"Strategy {strat.name} failed: {e}")

            # 3. Risk filter + execute
            executed = 0
            for sig in all_signals:
                allowed, reason = risk.can_place_order(
                    ticker=sig.ticker,
                    order_notional=sig.notional or (sig.quantity * sig.price),
                    is_new_position=True,
                )
                if not allowed:
                    logger.debug(f"Blocked {sig.ticker}: {reason}")
                    continue

                # Execute
                if config.get("paper_trading", True):
                    result = paper.place_order(
                        ticker=sig.ticker,
                        side=sig.side,
                        quantity=sig.quantity,
                        price=sig.price,
                        client_order_id=f"paper-{cycle}-{sig.ticker}-{sig.side}",
                    )
                    if "error" not in result:
                        risk.record_order()
                        risk.update_exposure(sig.ticker, sig.notional or 0)
                        executed += 1
                        logger.info(f"PAPER: {sig.reason}")
                elif config.get("live_trading", False):
                    # Real order path
                    try:
                        count_str = f"{sig.quantity:.2f}"
                        price_str = f"{sig.price:.4f}"
                        result = client.create_order(
                            ticker=sig.ticker,
                            side=sig.side,
                            count=count_str,
                            price=price_str,
                            post_only=config.get("prefer_post_only", True),
                        )
                        risk.record_order()
                        executed += 1
                        logger.info(f"LIVE ORDER: {sig.reason} → {result.get('order', {}).get('order_id')}")
                    except Exception as e:
                        logger.error(f"Live order failed: {e}")

            # 4. Status
            risk_status = risk.get_status()
            paper_status = paper.get_status()

            table = Table(title=f"Status — Cycle {cycle} — {datetime.now().strftime('%H:%M:%S')}")
            table.add_column("Metric")
            table.add_column("Value")
            table.add_row("Mode", "PAPER" if config.get("paper_trading") else "LIVE")
            table.add_row("Signals this cycle", str(len(all_signals)))
            table.add_row("Executed", str(executed))
            table.add_row("Paper Cash", f"${paper_status['cash']:.2f}")
            table.add_row("Paper Equity", f"${paper_status['equity']:.2f}")
            table.add_row("Open Exposure", f"${risk_status['open_exposure']:.2f} ({risk_status['exposure_pct']}%)")
            table.add_row("Daily PnL (risk)", f"${risk_status['daily_pnl']:.2f}")
            table.add_row("Trading Halted", str(risk_status['trading_halted']))
            table.add_row("Orders this hour", str(risk_status['orders_this_hour']))
            console.print(table)

            if risk_status["trading_halted"]:
                console.print(f"[red]Trading halted: {risk_status['halt_reason']}[/red]")
                # Still sleep but skip trading
                time.sleep(interval)
                continue

            time.sleep(interval)

    except KeyboardInterrupt:
        console.print("\n[yellow]Shutting down cleanly...[/yellow]")
        if config.get("live_trading") and not config.get("paper_trading"):
            console.print("Attempting to cancel open orders...")
            try:
                client.cancel_all_orders()
            except Exception as e:
                console.print(f"Cancel failed: {e}")
        console.print("[green]Stopped.[/green]")
        logger.info("Shutdown complete")


if __name__ == "__main__":
    main()