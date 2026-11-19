#!/usr/bin/env python3
"""
Kalshi Auto Trader - Streamlit Dashboard
========================================
- Simple Demo/Paper/Live toggle
- Quick-start with $10 / $20 / $50
- Full transparency into bot decision pathways
- Browse markets and place bets quickly
"""

import streamlit as st
import yaml
import time
import uuid
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Any
import pandas as pd
import traceback

from kalshi_client import KalshiClient
from risk_manager import RiskManager
from paper_engine import PaperEngine
from strategies.maker import MakerStrategy
from strategies.relative_value import RelativeValueStrategy
from strategies.base import TradeSignal

# ------------------------------------------------------------
# Page setup
# ------------------------------------------------------------
st.set_page_config(
    page_title="Kalshi Auto Trader",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
    .stAlert {margin-top: 0.5rem;}
    div[data-testid="stMetricValue"] {font-size: 1.3rem;}
    .quick-start-btn {font-size: 1.2rem !important; padding: 0.8rem !important;}
</style>
""", unsafe_allow_html=True)

# ------------------------------------------------------------
# Session state
# ------------------------------------------------------------
def init_state():
    defaults = {
        "config": None,
        "client": None,
        "risk": None,
        "paper": None,
        "last_markets": [],
        "last_signals": [],
        "authenticated": False,
        "pathway_log": [],          # Transparency log
        "last_scan_detail": {},     # Full pathway of last scan
        "quick_started": False,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

    if st.session_state.config is None:
        cfg_path = Path("config.yaml")
        if cfg_path.exists():
            with open(cfg_path) as f:
                st.session_state.config = yaml.safe_load(f)
        else:
            with open("config.example.yaml") as f:
                st.session_state.config = yaml.safe_load(f)

init_state()
config = st.session_state.config

def log_pathway(step: str, detail: Any = None):
    """Record a step in the decision pathway for transparency."""
    entry = {
        "time": datetime.now().strftime("%H:%M:%S.%f")[:-3],
        "step": step,
        "detail": str(detail)[:500] if detail is not None else "",
    }
    st.session_state.pathway_log.append(entry)
    # Keep last 200 entries
    if len(st.session_state.pathway_log) > 200:
        st.session_state.pathway_log = st.session_state.pathway_log[-200:]

def get_env_flags(mode: str):
    mode = mode or "demo_paper"
    use_demo = mode.startswith("demo")
    paper = "paper" in mode
    live = "live" in mode and not paper
    return use_demo, paper, live

# ------------------------------------------------------------
# Sidebar
# ------------------------------------------------------------
with st.sidebar:
    st.title("Kalshi Auto Trader")
    st.caption("Low-effort • Transparent decisions")

    # ----- Quick Start -----
    st.markdown("### ⚡ Quick Start")
    st.write("Start immediately with a small paper bankroll (Demo + Paper mode forced).")

    qs1, qs2, qs3 = st.columns(3)
    def do_quick_start(amount: float):
        config["mode"] = "demo_paper"
        config["bankroll_usd"] = amount
        config["auto_trade"] = True
        config["max_position_pct"] = 0.20          # Allow larger relative size for tiny bankrolls
        config["max_total_exposure_pct"] = 0.60
        config["daily_loss_limit_pct"] = 0.25
        st.session_state.config = config
        st.session_state.risk = RiskManager(
            bankroll=amount,
            max_position_pct=0.20,
            max_total_exposure_pct=0.60,
            daily_loss_limit_pct=0.25,
            max_orders_per_hour=40,
        )
        st.session_state.paper = PaperEngine(starting_balance=amount)
        st.session_state.quick_started = True
        st.session_state.pathway_log = []
        log_pathway("QUICK START", f"Bankroll set to ${amount} • Mode forced to demo_paper • Auto-trade ON")
        st.rerun()

    with qs1:
        if st.button("$10", use_container_width=True, help="Paper bankroll $10"):
            do_quick_start(10.0)
    with qs2:
        if st.button("$20", use_container_width=True, help="Paper bankroll $20"):
            do_quick_start(20.0)
    with qs3:
        if st.button("$50", use_container_width=True, help="Paper bankroll $50"):
            do_quick_start(50.0)

    if st.session_state.quick_started:
        st.success(f"Quick-started with ${config.get('bankroll_usd', 0):.0f} (Paper)")

    st.markdown("---")
    st.subheader("1. Mode")

    mode_options = {
        "Demo + Paper (Safest)": "demo_paper",
        "Demo + Live Orders": "demo_live",
        "Production Data + Paper": "prod_paper",
        "⚠️ PRODUCTION + LIVE MONEY": "prod_live",
    }
    current_mode = config.get("mode", "demo_paper")
    label = next((k for k, v in mode_options.items() if v == current_mode), "Demo + Paper (Safest)")
    selected_label = st.selectbox("Trading Mode", list(mode_options.keys()),
                                  index=list(mode_options.keys()).index(label))
    new_mode = mode_options[selected_label]
    if new_mode != current_mode:
        config["mode"] = new_mode
        st.session_state.config = config
        st.rerun()

    use_demo, is_paper, is_live = get_env_flags(config.get("mode", "demo_paper"))

    if is_live and not use_demo:
        st.error("🚨 REAL MONEY MODE")
    elif is_live:
        st.warning("Demo Live orders")
    else:
        st.success("Paper / Safe mode")

    st.markdown("---")
    st.subheader("2. Kalshi Keys (optional)")

    st.caption("Generate keys in Kalshi → Account → API Keys. Use Demo keys first.")
    api_key_id = st.text_input("API Key ID", value=config.get("api_key_id", ""))
    private_key_pem = st.text_area("Private Key PEM", value=config.get("private_key_pem", ""), height=80)

    if st.button("Connect Keys", use_container_width=True):
        config["api_key_id"] = api_key_id.strip()
        config["private_key_pem"] = private_key_pem.strip()
        key_path = Path("tmp_private_key.pem")
        if private_key_pem.strip():
            key_path.write_text(private_key_pem.strip())
            config["private_key_path"] = str(key_path)
        st.session_state.config = config
        try:
            client = KalshiClient(
                api_key_id=config.get("api_key_id", ""),
                private_key_path=config.get("private_key_path", ""),
                use_demo=use_demo,
            )
            if config.get("api_key_id"):
                bal = client.get_balance()
                st.session_state.authenticated = True
                st.success("Connected")
                log_pathway("AUTH", f"Authenticated successfully. Balance response received.")
            else:
                st.session_state.authenticated = False
                st.info("Public data only")
            st.session_state.client = client
        except Exception as e:
            st.error(f"Connect failed: {e}")
            log_pathway("AUTH ERROR", str(e))
            st.session_state.authenticated = False

    st.markdown("---")
    st.subheader("3. Risk")
    bankroll = st.number_input("Bankroll ($)", value=float(config.get("bankroll_usd", 1000)), min_value=5.0, step=5.0)
    max_pos_pct = st.slider("Max per position %", 1.0, 30.0, float(config.get("max_position_pct", 0.015))*100, 0.5) / 100
    max_exp_pct = st.slider("Max total exposure %", 5.0, 80.0, float(config.get("max_total_exposure_pct", 0.15))*100, 1.0) / 100
    daily_loss_pct = st.slider("Daily loss stop %", 2.0, 40.0, float(config.get("daily_loss_limit_pct", 0.04))*100, 1.0) / 100
    auto_trade = st.toggle("Auto-trade under risk rules", value=config.get("auto_trade", False))

    config.update({
        "bankroll_usd": bankroll,
        "max_position_pct": max_pos_pct,
        "max_total_exposure_pct": max_exp_pct,
        "daily_loss_limit_pct": daily_loss_pct,
        "auto_trade": auto_trade,
    })
    st.session_state.config = config

    st.caption("Not financial advice. You can lose money.")

# ------------------------------------------------------------
# Initialize engines
# ------------------------------------------------------------
if st.session_state.client is None:
    st.session_state.client = KalshiClient(use_demo=use_demo)

if st.session_state.risk is None or abs(st.session_state.risk.bankroll - bankroll) > 0.01:
    st.session_state.risk = RiskManager(
        bankroll=bankroll,
        max_position_pct=max_pos_pct,
        max_total_exposure_pct=max_exp_pct,
        daily_loss_limit_pct=daily_loss_pct,
    )

if st.session_state.paper is None:
    st.session_state.paper = PaperEngine(starting_balance=bankroll)

client: KalshiClient = st.session_state.client
risk: RiskManager = st.session_state.risk
paper: PaperEngine = st.session_state.paper

# ------------------------------------------------------------
# Main header + metrics
# ------------------------------------------------------------
st.title("📈 Kalshi Decision Dashboard")

risk_status = risk.get_status()
paper_status = paper.get_status()

m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("Mode", config.get("mode", "demo_paper").replace("_", " ").title())
m2.metric("Paper Equity", f"${paper_status['equity']:.2f}", f"{paper_status['unrealized_approx']:+.2f}")
m3.metric("Exposure", f"${risk_status['open_exposure']:.2f}", f"{risk_status['exposure_pct']:.1f}%")
m4.metric("Daily PnL", f"${risk_status['daily_pnl']:.2f}")
m5.metric("Auth", "✅" if st.session_state.authenticated else "Public")

if risk_status["trading_halted"]:
    st.error(f"Trading halted: {risk_status['halt_reason']}")

# ------------------------------------------------------------
# Tabs
# ------------------------------------------------------------
tab_quick, tab_browse, tab_bot, tab_pathways, tab_positions = st.tabs([
    "⚡ Quick Start & Status",
    "🔍 Browse & Place Bets",
    "🤖 Bot Recommendations",
    "🔎 Pathways (Transparency)",
    "📊 Positions",
])

# ==================== QUICK START TAB ====================
with tab_quick:
    st.subheader("One-click start")
    st.write("Choose a small paper bankroll. The app switches to **Demo + Paper**, sets risk limits appropriate for the size, turns Auto-trade on, and is ready to scan immediately.")

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        if st.button("Start with $10", use_container_width=True, type="primary"):
            do_quick_start(10.0)
    with c2:
        if st.button("Start with $20", use_container_width=True, type="primary"):
            do_quick_start(20.0)
    with c3:
        if st.button("Start with $50", use_container_width=True, type="primary"):
            do_quick_start(50.0)
    with c4:
        if st.button("Reset to defaults", use_container_width=True):
            st.session_state.quick_started = False
            config["mode"] = "demo_paper"
            config["bankroll_usd"] = 1000.0
            config["auto_trade"] = False
            st.session_state.config = config
            st.session_state.risk = None
            st.session_state.paper = None
            st.rerun()

    if st.session_state.quick_started:
        st.success(f"Running with ${config.get('bankroll_usd'):.0f} paper bankroll • Auto-trade is ON • Mode is Demo + Paper")
        st.info("Go to the **Bot Recommendations** tab and click **Run Bot Scan Now** to generate the first decisions.")

    st.markdown("---")
    st.write("**Current risk settings**")
    st.json(risk.get_status())

# ==================== BROWSE TAB ====================
with tab_browse:
    st.subheader("Market Browser")
    col_a, col_b = st.columns([3, 1])
    with col_a:
        search = st.text_input("Filter ticker / title / series", "")
    with col_b:
        if st.button("🔄 Refresh Markets", use_container_width=True):
            log_pathway("FETCH MARKETS", "Requesting open markets from Kalshi API")
            try:
                resp = client.get_markets(status="open", limit=100)
                st.session_state.last_markets = resp.get("markets", [])
                log_pathway("FETCH MARKETS OK", f"Received {len(st.session_state.last_markets)} markets")
                st.success(f"Loaded {len(st.session_state.last_markets)} markets")
            except Exception as e:
                log_pathway("FETCH MARKETS ERROR", str(e))
                st.error(f"Failed: {e}")

    markets = st.session_state.last_markets
    if search:
        q = search.lower()
        markets = [m for m in markets if q in (m.get("ticker") or "").lower()
                   or q in (m.get("title") or "").lower()
                   or q in (m.get("series_ticker") or "").lower()]

    if not markets:
        st.info("Click **Refresh Markets** to load data.")
    else:
        rows = []
        for m in markets[:120]:
            yes_bid = float(m.get("yes_bid_dollars") or m.get("yes_bid") or 0)
            yes_ask = float(m.get("yes_ask_dollars") or m.get("yes_ask") or 1)
            rows.append({
                "Ticker": m.get("ticker"),
                "Title": (m.get("title") or "")[:55],
                "Yes Bid": round(yes_bid, 3),
                "Yes Ask": round(yes_ask, 3),
                "Mid": round((yes_bid + yes_ask)/2, 3),
                "Volume": m.get("volume") or m.get("volume_fp") or 0,
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, height=320)

        st.markdown("### Quick Place Order")
        selected = st.selectbox("Ticker", [r["Ticker"] for r in rows])
        if selected:
            m = next((x for x in markets if x.get("ticker") == selected), None)
            if m:
                yes_bid = float(m.get("yes_bid_dollars") or m.get("yes_bid") or 0)
                yes_ask = float(m.get("yes_ask_dollars") or m.get("yes_ask") or 1)
                mid = (yes_bid + yes_ask) / 2
                st.write(f"**{m.get('title')}**  |  Bid {yes_bid:.3f} / Ask {yes_ask:.3f}")

                oc1, oc2, oc3, oc4 = st.columns(4)
                with oc1:
                    side = st.selectbox("Side", ["bid (Buy YES)", "ask (Sell YES)"])
                with oc2:
                    qty = st.number_input("Contracts", 1.0, 200.0, float(config.get("default_order_size_contracts", 5)), 1.0)
                with oc3:
                    price = st.number_input("Limit Price", 0.01, 0.99, round(mid, 2), 0.01)
                with oc4:
                    st.write("")
                    st.write("")
                    if st.button("Place Order", type="primary", use_container_width=True):
                        side_clean = "bid" if "bid" in side else "ask"
                        notional = qty * price
                        log_pathway("MANUAL ORDER ATTEMPT", f"{side_clean} {qty} {selected} @ {price}")
                        allowed, reason = risk.can_place_order(selected, notional)
                        if not allowed:
                            log_pathway("RISK BLOCK", reason)
                            st.error(f"Risk blocked: {reason}")
                        else:
                            if is_paper or not is_live:
                                result = paper.place_order(selected, side_clean, qty, price, str(uuid.uuid4()))
                                risk.record_order()
                                risk.update_exposure(selected, notional)
                                log_pathway("PAPER FILL", result)
                                st.success(f"Paper order: {result}")
                            else:
                                try:
                                    result = client.create_order(selected, side_clean, f"{qty:.2f}", f"{price:.4f}",
                                                                post_only=config.get("prefer_post_only", True))
                                    risk.record_order()
                                    log_pathway("LIVE ORDER", result)
                                    st.success(f"Live order submitted")
                                except Exception as e:
                                    log_pathway("LIVE ORDER ERROR", str(e))
                                    st.error(str(e))

# ==================== BOT RECOMMENDATIONS TAB ====================
with tab_bot:
    st.subheader("Bot Decision Engine")
    st.write("The bot fetches markets, runs each enabled strategy, applies risk checks, and produces signals with reasons.")

    if st.button("🧠 Run Bot Scan Now", type="primary", use_container_width=True):
        st.session_state.pathway_log = []  # fresh log for this scan
        st.session_state.last_scan_detail = {"started": datetime.now().isoformat(), "steps": []}

        def add_detail(msg, data=None):
            st.session_state.last_scan_detail["steps"].append({"msg": msg, "data": data})
            log_pathway(msg, data)

        with st.spinner("Running full decision pathway..."):
            try:
                add_detail("1. FETCH", "Calling Kalshi /markets (open)")
                resp = client.get_markets(status="open", limit=100)
                markets = resp.get("markets", [])
                st.session_state.last_markets = markets
                add_detail("1. FETCH OK", f"{len(markets)} markets received")

                strategies = []
                if config.get("enable_maker_strategy", True):
                    strategies.append(MakerStrategy())
                    add_detail("2. STRATEGY LOAD", "MakerStrategy enabled")
                if config.get("enable_relative_value", True):
                    strategies.append(RelativeValueStrategy())
                    add_detail("2. STRATEGY LOAD", "RelativeValueStrategy enabled")

                all_signals = []
                for strat in strategies:
                    add_detail(f"3. RUN {strat.name}", "Generating signals...")
                    sigs = strat.generate_signals(markets, {}, paper.positions, config)
                    add_detail(f"3. RUN {strat.name} DONE", f"{len(sigs)} raw signals")
                    all_signals.extend(sigs)

                # Risk filter
                actionable = []
                blocked = []
                for sig in all_signals:
                    notional = sig.notional or (sig.quantity * sig.price)
                    allowed, reason = risk.can_place_order(sig.ticker, notional)
                    if allowed:
                        actionable.append(sig)
                        add_detail("4. RISK PASS", f"{sig.side} {sig.ticker} @ {sig.price} — {sig.reason}")
                    else:
                        sig.reason = f"{sig.reason} [BLOCKED: {reason}]"
                        blocked.append(sig)
                        add_detail("4. RISK BLOCK", f"{sig.ticker}: {reason}")

                st.session_state.last_signals = actionable + blocked
                add_detail("5. SUMMARY", f"{len(actionable)} actionable / {len(blocked)} blocked / {len(all_signals)} total")

                # Auto-execute if enabled
                if config.get("auto_trade") and actionable:
                    add_detail("6. AUTO-TRADE", f"Executing {len(actionable)} signals under risk rules")
                    for sig in actionable:
                        notional = sig.notional or sig.quantity * sig.price
                        if is_paper or not is_live:
                            result = paper.place_order(sig.ticker, sig.side, sig.quantity, sig.price, str(uuid.uuid4()))
                            risk.record_order()
                            risk.update_exposure(sig.ticker, notional)
                            add_detail("6. PAPER EXEC", f"{sig.side} {sig.quantity} {sig.ticker} @ {sig.price}")
                        else:
                            try:
                                client.create_order(sig.ticker, sig.side, f"{sig.quantity:.2f}", f"{sig.price:.4f}", post_only=True)
                                risk.record_order()
                                add_detail("6. LIVE EXEC", f"{sig.side} {sig.ticker}")
                            except Exception as e:
                                add_detail("6. LIVE ERROR", str(e))

                st.success(f"Scan complete — {len(actionable)} actionable signals")
            except Exception as e:
                add_detail("ERROR", traceback.format_exc())
                st.error(f"Scan failed: {e}")

    signals = st.session_state.last_signals
    if signals:
        st.markdown("### Signals")
        for i, sig in enumerate(signals):
            blocked = "BLOCKED" in sig.reason
            with st.expander(f"{'🚫' if blocked else '✅'} {sig.side.upper()} {sig.quantity} × {sig.ticker} @ {sig.price:.3f}", expanded=(i < 4 and not blocked)):
                st.write(sig.reason)
                st.caption(f"Confidence: {sig.confidence:.0%} • Notional ≈ ${sig.notional or sig.quantity*sig.price:.2f}")
                if not blocked and st.button("Execute", key=f"ex_{i}"):
                    notional = sig.notional or sig.quantity * sig.price
                    log_pathway("MANUAL EXEC FROM SIGNAL", f"{sig.ticker}")
                    if is_paper or not is_live:
                        result = paper.place_order(sig.ticker, sig.side, sig.quantity, sig.price, str(uuid.uuid4()))
                        risk.record_order()
                        risk.update_exposure(sig.ticker, notional)
                        st.success("Paper executed")
                    else:
                        try:
                            client.create_order(sig.ticker, sig.side, f"{sig.quantity:.2f}", f"{sig.price:.4f}")
                            risk.record_order()
                            st.success("Live order sent")
                        except Exception as e:
                            st.error(str(e))
    else:
        st.info("Click **Run Bot Scan Now** to generate recommendations.")

# ==================== PATHWAYS TAB (Transparency) ====================
with tab_pathways:
    st.subheader("Decision Pathways — Full Transparency")
    st.write("This shows every step the bot took to obtain information and make trade decisions. Use it to understand and audit the logic.")

    colp1, colp2 = st.columns(2)
    with colp1:
        if st.button("Clear pathway log"):
            st.session_state.pathway_log = []
            st.session_state.last_scan_detail = {}
            st.rerun()
    with colp2:
        st.caption(f"{len(st.session_state.pathway_log)} events recorded")

    # Last full scan detail
    if st.session_state.last_scan_detail.get("steps"):
        st.markdown("### Last Bot Scan Pathway")
        for step in st.session_state.last_scan_detail["steps"]:
            st.markdown(f"**{step['msg']}**")
            if step.get("data"):
                st.code(str(step["data"])[:600], language=None)

    st.markdown("### Live Event Log (most recent first)")
    if st.session_state.pathway_log:
        log_df = pd.DataFrame(st.session_state.pathway_log[::-1])
        st.dataframe(log_df, use_container_width=True, height=400)
    else:
        st.info("No pathway events yet. Run a bot scan or place an order to see the decision trail.")

    st.markdown("---")
    st.markdown("### What the pathways cover")
    st.markdown("""
- **FETCH** — calls to Kalshi market data endpoints  
- **STRATEGY LOAD / RUN** — which strategies executed and how many signals they produced  
- **RISK PASS / BLOCK** — every risk check and why a trade was allowed or rejected  
- **AUTO-TRADE / PAPER EXEC / LIVE EXEC** — actual order placement decisions  
- **AUTH** — key connection attempts  
- **MANUAL ORDER** — anything you place by hand  

All of this stays on your machine. Nothing is sent to external AI services during trading.
""")

# ==================== POSITIONS TAB ====================
with tab_positions:
    st.subheader("Positions & Risk")
    st.json(risk.get_status())
    st.subheader("Paper Engine")
    st.json(paper.get_status())
    if paper.positions:
        pos_rows = [{"Key": k, "Side": p.side, "Qty": p.quantity,
                     "Avg Price": round(p.avg_price, 4), "Realized": round(p.realized_pnl, 2)}
                    for k, p in paper.positions.items()]
        st.dataframe(pd.DataFrame(pos_rows), use_container_width=True)
    else:
        st.write("No open paper positions.")

    if paper.trade_log:
        st.markdown("### Recent fills")
        st.dataframe(pd.DataFrame(paper.trade_log[::-1][:30]), use_container_width=True)

# Footer
st.markdown("---")
st.caption("Kalshi Auto Trader • Transparent decision pathways • Not financial advice • You can lose money • Prefer Demo + Paper")
