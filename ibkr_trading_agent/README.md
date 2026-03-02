# IBKR Automated Trading Agent

A production-quality, hands-free intraday trading agent for Interactive Brokers.
Implements **Gap & Go / Opening Range Breakout (ORB)** with a VWAP filter,
strict risk rails, full JSONL audit logs, and a bounded online learning pipeline.

> **Start with paper trading for at least one week before going live.**

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Install Dependencies](#install-dependencies)
3. [IB Gateway / TWS Setup](#ib-gateway--tws-setup)
4. [Running the Agent](#running-the-agent)
5. [Risk Settings](#risk-settings)
6. [Switching to Live Trading](#switching-to-live-trading)
7. [Offline Learning](#offline-learning)
8. [Reports](#reports)
9. [Tests](#tests)
10. [Project Structure](#project-structure)

---

## Architecture Overview

```
main.py (asyncio scheduler)
  ├── broker.py       — ib_insync connection, reconnect, circuit breaker
  ├── datafeed.py     — OHLCV bars, VWAP, ATR, Opening Range
  ├── signals.py      — ORB + VWAP + relative-strength signal generation
  ├── risk_manager.py — Central approval gate, daily PnL, all hard caps
  ├── order_manager.py — Bracket orders, fill monitoring, kill switch
  ├── online_learning.py — Bounded intraday param adaptation
  ├── dashboard.py    — Rich terminal UI
  ├── storage.py      — SQLite (runs, decisions, orders, fills, positions)
  └── logger.py       — Structured JSONL audit log
```

**Trading schedule (America/Los_Angeles)**

| Time  | Phase           | Action                              |
|-------|-----------------|-------------------------------------|
| 06:15 | PREP            | Connect, qualify contracts, subscribe data |
| 06:30 | OR_RECORDING    | Record Opening Range (no entries)   |
| 06:35 | TRADING         | Scan signals, submit bracket orders |
| 09:30 | WIND_DOWN       | No new entries, manage exits        |
| 09:45 | DONE            | Force-flatten, generate EOD report  |

---

## Install Dependencies

```bash
# From the repo root
pip install -r requirements.txt
```

**Requirements:**
```
ib_insync>=0.9.86
pandas>=2.0.0
numpy>=1.24.0
PyYAML>=6.0
rich>=13.0.0
jsonlines>=4.0.0
matplotlib>=3.7.0
pytest>=7.4.0
```

Python 3.11+ required (uses `zoneinfo`, `match` not used but 3.11 features assumed).

---

## IB Gateway / TWS Setup

### Step 1 — Enable API access in TWS or IB Gateway

1. Open **TWS** or **IB Gateway**
2. Go to **Edit → Global Configuration → API → Settings**
3. ✅ Enable **"Enable ActiveX and Socket Clients"**
4. Set **Socket port**:
   - TWS paper: `7497`  |  TWS live: `7496`
   - Gateway paper: `4002`  |  Gateway live: `4001`
5. ✅ Allow connections from `127.0.0.1`
6. Uncheck "Read-Only API" if you want to place orders

### Step 2 — Verify market data subscriptions

- For real-time data: ensure you have the required data subscriptions in Account Management
- The agent automatically falls back to **delayed data (15-min delay)** if real-time is not available and logs which is being used

### Step 3 — Paper trading first

- Log in to your **paper trading account** in TWS/Gateway
- The default config uses `port: 7497` (TWS paper mode)

---

## Running the Agent

### Paper mode (default — recommended first week)

```bash
python -m src.main --config config/settings.yaml
```

The dashboard will show `● CONNECTED (paper)` in the terminal.

### Dry-run mode (no orders, just logs decisions)

```bash
python -m src.main --config config/settings.yaml --dry-run
```
Or set `dry_run: true` in `config/settings.yaml`.
Useful for testing signal logic without any broker connection.

### Live mode (after validating paper results)

1. Edit `config/settings.yaml`:
   ```yaml
   mode:
     paper_only: false
     live_mode: true
   broker:
     port: 7496   # TWS live
   ```
2. Log in to your **live account** in TWS/Gateway
3. Run the agent — it will print a **5-second countdown** before placing live orders

---

## Risk Settings

All limits are in `config/settings.yaml` under the `risk:` section.

| Parameter | Default ($8k account) | Description |
|-----------|----------------------|-------------|
| `max_daily_loss_usd` | `160` | Flatten all and stop trading for the day |
| `max_loss_per_trade_usd` | `40` | Max dollars risked per trade (stop × qty) |
| `max_trades_per_day` | `8` | Hard cap on number of entries per session |
| `max_position_notional_usd` | `1200` | price × qty must not exceed this |
| `max_concurrent_positions` | `2` | Max simultaneous open positions |
| `consecutive_loss_limit` | `3` | Stop after N losses in a row |

### Circuit Breakers (auto-triggered, no manual intervention needed)

| Trigger | Default | Action |
|---------|---------|--------|
| No quote update | 30 seconds | Flatten all, stop trading |
| Order rejects | 3 in 5 minutes | Flatten all, stop trading |
| Order latency | >5 seconds | Flatten all, stop trading |

### Position sizing formula

```python
shares = floor(min(
    max_position_notional_usd / price,
    max_loss_per_trade_usd / stop_distance
) * position_size_multiplier)
```

Trades are rejected if `shares < 1`.

---

## Switching to Live Trading

**Checklist before going live:**

- [ ] Ran in paper mode for ≥ 5 sessions
- [ ] Win rate ≥ 40% in paper trading
- [ ] No circuit-breaker trips due to code bugs
- [ ] EOD reports show correct fills (not slippage > 2× stop distance)
- [ ] Reviewed `learn_output/recommendations.md` from offline learning
- [ ] Config change: `paper_only: false`, `live_mode: true`, correct port
- [ ] IB Gateway logged into live account

**Config change for live:**
```yaml
mode:
  paper_only: false   # ← change from true
  live_mode: true     # ← change from false
broker:
  port: 7496          # ← TWS live (or 4001 for Gateway live)
```

---

## Offline Learning

After market close, run the parameter optimiser on historical trade data:

```bash
python -m src.learn --config config/settings.yaml
```

This reads all closed trades from `data/trading.db`, runs grid search + walk-forward
evaluation, and writes:

- `learn_output/proposed_params.yaml` — best param set (for review only)
- `learn_output/recommendations.md` — human-readable analysis

> ⚠️ **These outputs are NEVER auto-applied.** You must manually copy any values
> you agree with into `config/settings.yaml`.

---

## Reports

End-of-day reports are generated automatically after each session and stored in:

```
reports/
  YYYY-MM-DD/
    trades.csv          — per-trade detail
    summary.md          — PnL, win rate, R distribution, errors
    equity_curve.png    — cumulative P&L over time
    r_distribution.png  — per-trade R multiples
    pnl_by_hour.png     — P&L grouped by hour
```

Generate manually for a specific run:
```bash
python -m src.reporter --config config/settings.yaml --date 2024-01-15
```

---

## Tests

```bash
# Run all unit tests (no broker needed)
python -m pytest tests/test_sizing.py tests/test_risk_manager.py tests/test_tick_rounding.py -v

# Smoke test (requires IB Gateway/TWS running on port 7497)
python tests/smoke_test.py --host 127.0.0.1 --port 7497 --symbol SPY
```

---

## Project Structure

```
ReviewBuudyAI/
├── config/
│   └── settings.yaml           ← Edit this for your account
├── src/
│   ├── __init__.py
│   ├── main.py                 ← Entry point
│   ├── config_loader.py        ← YAML → typed config
│   ├── logger.py               ← Structured JSONL logging
│   ├── storage.py              ← SQLite (runs/decisions/orders/fills/positions)
│   ├── broker.py               ← ib_insync wrapper + circuit breaker
│   ├── datafeed.py             ← OHLCV bars, VWAP, ATR, Opening Range
│   ├── risk_manager.py         ← Central risk gate + position sizing
│   ├── signals.py              ← ORB + VWAP + RS signal generation
│   ├── order_manager.py        ← Bracket orders, fills, kill switch
│   ├── online_learning.py      ← Bounded intraday param adaptation
│   ├── dashboard.py            ← Rich terminal UI
│   ├── reporter.py             ← EOD report (CSV, MD, plots)
│   └── learn.py                ← Offline grid search + walk-forward
├── tests/
│   ├── test_sizing.py          ← Position sizing unit tests
│   ├── test_risk_manager.py    ← Risk veto condition tests
│   ├── test_tick_rounding.py   ← Tick size rounding tests
│   └── smoke_test.py           ← IBKR connection + SPY quote test
├── data/
│   └── trading.db              ← SQLite (auto-created)
├── logs/
│   └── YYYY-MM-DD.jsonl        ← Decision audit log (auto-created)
├── reports/                    ← EOD reports (auto-created)
├── learn_output/               ← Offline learning outputs (auto-created)
└── requirements.txt
```

---

## Important Safety Notes

1. **Never store your IB password.** The agent connects via IB Gateway/TWS API only.
   Authentication is handled entirely by the Gateway/TWS application.

2. **Hard risk rails cannot be bypassed in code.** Every order goes through
   `RiskManager.approve_entry()` before submission.

3. **The online learning controller only adjusts bounded parameters** (position size
   multiplier, cooldown, VWAP filter strength, OR minutes). It never rewrites strategy
   logic or removes risk caps.

4. **Offline learning (`src.learn`) outputs require manual review** before any values
   are copied to `config/settings.yaml`. The agent never reads from `learn_output/`.

5. **If anything unexpected happens** (wrong fills, runaway losses), use Ctrl+C to
   trigger graceful shutdown. The agent will flatten all positions and generate an
   EOD report before exiting.
