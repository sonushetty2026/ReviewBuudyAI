"""
Offline Learning Module — post-session parameter optimisation.

Reads all historical trade data from SQLite, performs grid search +
walk-forward evaluation, and writes:
  - learn_output/proposed_params.yaml  (best params — for human review only)
  - learn_output/recommendations.md   (human-readable analysis)

NOTE: These outputs are NEVER auto-applied to live trading.
      The user must manually copy values into config/settings.yaml.

Run: python -m src.learn --config config/settings.yaml
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import sys
from datetime import datetime, timezone
from itertools import product
from typing import Any, Optional

import yaml

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Param grid
# ---------------------------------------------------------------------------

PARAM_GRID = {
    "or_minutes": [3, 5, 8, 10, 15],
    "vwap_filter_strength": [1, 2, 3],
    "take_profit_r1": [1.0, 1.5, 2.0],
    "partial_exit_pct_at_r1": [0.33, 0.50, 0.67],
}


# ---------------------------------------------------------------------------
# Simulation utilities
# ---------------------------------------------------------------------------

def simulate_trade(trade: dict, params: dict) -> dict:
    """
    Re-simulate a historical trade with alternative parameters.
    This is a simplified re-evaluation based on stored MAE/MFE.
    Returns a dict with simulated_pnl, simulated_r.
    """
    entry = trade.get("entry_price", 0)
    stop = trade.get("stop_price", 0)
    qty = trade.get("qty", 0)
    mae = trade.get("mae", 0) or 0
    mfe = trade.get("mfe", 0) or 0
    actual_pnl = trade.get("realized_pnl", 0) or 0

    if entry <= 0 or stop <= 0 or qty <= 0:
        return {"simulated_pnl": actual_pnl, "simulated_r": 0.0}

    risk_per_share = abs(entry - stop)
    if risk_per_share <= 0:
        return {"simulated_pnl": actual_pnl, "simulated_r": 0.0}

    r1 = params.get("take_profit_r1", 1.5)
    partial_pct = params.get("partial_exit_pct_at_r1", 0.5)

    # Simulate: did MFE reach TP1?
    tp1_r = r1
    tp2_r = r1 + 0.5  # assume TP2 = TP1 + 0.5R

    tp1_hit = mfe >= tp1_r / 100.0  # mfe stored as fraction
    tp2_hit = mfe >= tp2_r / 100.0
    stop_hit = mae <= -(1.0 / 100.0)  # stopped if MAE > 1%

    tp1_qty = max(1, int(math.floor(qty * partial_pct)))
    tp2_qty = qty - tp1_qty

    if tp1_hit and tp2_hit:
        sim_pnl = (tp1_qty * risk_per_share * r1) + (tp2_qty * risk_per_share * tp2_r)
    elif tp1_hit:
        sim_pnl = tp1_qty * risk_per_share * r1 + tp2_qty * (-risk_per_share)
    elif stop_hit:
        sim_pnl = -qty * risk_per_share
    else:
        sim_pnl = actual_pnl  # no change

    sim_r = sim_pnl / (risk_per_share * qty) if risk_per_share > 0 else 0.0
    return {"simulated_pnl": round(sim_pnl, 2), "simulated_r": round(sim_r, 4)}


def evaluate_params(trades: list[dict], params: dict) -> dict:
    """Evaluate a parameter set against a list of trades."""
    if not trades:
        return {"total_pnl": 0.0, "win_rate": 0.0, "avg_r": 0.0, "sharpe": 0.0, "n": 0}

    pnls: list[float] = []
    rs: list[float] = []
    for t in trades:
        result = simulate_trade(t, params)
        pnls.append(result["simulated_pnl"])
        rs.append(result["simulated_r"])

    total = sum(pnls)
    wins = sum(1 for p in pnls if p > 0)
    avg_r = sum(rs) / len(rs) if rs else 0.0

    # Simple Sharpe-like ratio
    if len(pnls) > 1:
        mean_pnl = total / len(pnls)
        std_pnl = math.sqrt(sum((p - mean_pnl) ** 2 for p in pnls) / len(pnls))
        sharpe = (mean_pnl / std_pnl) if std_pnl > 0 else 0.0
    else:
        sharpe = 0.0

    return {
        "total_pnl": round(total, 2),
        "win_rate": wins / len(trades),
        "avg_r": round(avg_r, 4),
        "sharpe": round(sharpe, 4),
        "n": len(trades),
    }


def grid_search(trades: list[dict], param_grid: dict) -> list[dict]:
    """Evaluate all parameter combinations. Returns results sorted by Sharpe."""
    keys = list(param_grid.keys())
    values = list(param_grid.values())
    results: list[dict] = []

    for combo in product(*values):
        params = dict(zip(keys, combo))
        metrics = evaluate_params(trades, params)
        results.append({**params, **metrics})

    results.sort(key=lambda x: x.get("sharpe", 0), reverse=True)
    return results


def walk_forward_eval(
    trades: list[dict], params: dict, train_frac: float = 0.70
) -> dict:
    """
    Simple walk-forward split.
    train: first train_frac of days
    test:  remaining days
    """
    if not trades:
        return {"train": {}, "test": {}, "params": params}

    n_train = max(1, int(len(trades) * train_frac))
    train = trades[:n_train]
    test = trades[n_train:]

    return {
        "params": params,
        "train": evaluate_params(train, params),
        "test": evaluate_params(test, params) if test else {},
    }


# ---------------------------------------------------------------------------
# Report writing
# ---------------------------------------------------------------------------

def write_proposed_params(params: dict, cfg_path: str, out_path: str) -> None:
    """Write proposed_params.yaml merging best params over existing config."""
    try:
        with open(cfg_path) as f:
            base = yaml.safe_load(f) or {}
    except Exception:
        base = {}

    # Update only strategy params
    strategy = base.get("strategy", {})
    if "or_minutes" in params:
        strategy["or_minutes"] = params["or_minutes"]
    if "vwap_filter_strength" in params:
        strategy["vwap_filter_strength"] = params["vwap_filter_strength"]
    if "take_profit_r1" in params:
        strategy["take_profit_r1"] = params["take_profit_r1"]
    if "partial_exit_pct_at_r1" in params:
        strategy["partial_exit_pct_at_r1"] = params["partial_exit_pct_at_r1"]
    base["strategy"] = strategy
    base["_generated_at"] = datetime.now(timezone.utc).isoformat()
    base["_note"] = "REVIEW ONLY — do not auto-apply. Copy values to settings.yaml manually."

    with open(out_path, "w") as f:
        yaml.dump(base, f, default_flow_style=False, sort_keys=False)


def write_recommendations(
    grid_results: list[dict],
    wf_result: dict,
    trades: list[dict],
    out_path: str,
) -> None:
    lines = ["# Offline Learning Recommendations\n"]
    lines.append(f"*Generated {datetime.now(timezone.utc).isoformat()}*\n")
    lines.append(f"**Total historical trades analysed: {len(trades)}**\n\n")

    lines.append("## Top 5 Parameter Sets (In-Sample)\n")
    lines.append("| or_min | vwap_str | tp_r1 | partial | P&L | WinRate | AvgR | Sharpe |")
    lines.append("|--------|----------|-------|---------|-----|---------|------|--------|")
    for r in grid_results[:5]:
        lines.append(
            f"| {r.get('or_minutes')} | {r.get('vwap_filter_strength')} "
            f"| {r.get('take_profit_r1')} | {r.get('partial_exit_pct_at_r1')} "
            f"| ${r.get('total_pnl', 0):.2f} "
            f"| {r.get('win_rate', 0):.1%} "
            f"| {r.get('avg_r', 0):.3f}R "
            f"| {r.get('sharpe', 0):.3f} |"
        )
    lines.append("")

    lines.append("## Walk-Forward Evaluation (Best Params)\n")
    wf_params = wf_result.get("params", {})
    wf_train = wf_result.get("train", {})
    wf_test = wf_result.get("test", {})
    lines.append(f"**Params:** {json.dumps(wf_params, indent=2)}\n")
    lines.append(f"- Train P&L: ${wf_train.get('total_pnl', 0):.2f}  "
                 f"WinRate: {wf_train.get('win_rate', 0):.1%}  "
                 f"Sharpe: {wf_train.get('sharpe', 0):.3f}")
    if wf_test:
        lines.append(f"- Test  P&L: ${wf_test.get('total_pnl', 0):.2f}  "
                     f"WinRate: {wf_test.get('win_rate', 0):.1%}  "
                     f"Sharpe: {wf_test.get('sharpe', 0):.3f}")
    lines.append("")

    lines.append("## Recommendations\n")
    best = grid_results[0] if grid_results else {}
    if best:
        lines.append(f"1. Consider `or_minutes: {best.get('or_minutes', 5)}` "
                     f"(currently performs best in-sample)")
        lines.append(f"2. Consider `vwap_filter_strength: {best.get('vwap_filter_strength', 2)}`")
        lines.append(f"3. Consider `take_profit_r1: {best.get('take_profit_r1', 1.5)}`")
    lines.append("")

    lines.append("## ⚠️ Important\n")
    lines.append("> These are suggestions based on historical data only.")
    lines.append("> **Do not auto-apply.** Review carefully and update `config/settings.yaml`")
    lines.append("> manually if the walk-forward results confirm the in-sample findings.\n")

    with open(out_path, "w") as f:
        f.write("\n".join(lines))


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    logging.basicConfig(level=logging.INFO)

    parser = argparse.ArgumentParser(description="Offline learning: grid search + walk-forward.")
    parser.add_argument("--config", default="config/settings.yaml")
    args = parser.parse_args()

    from .config_loader import load_config
    from .storage import Storage

    cfg = load_config(args.config)
    storage = Storage(cfg.paths.db)

    os.makedirs(cfg.paths.learn_dir, exist_ok=True)

    trades = storage.get_all_positions()
    if not trades:
        print("No historical trades found. Run the agent for at least one session first.")
        sys.exit(0)

    closed = [t for t in trades if t.get("close_ts")]
    logger.info("Analysing %d closed trades …", len(closed))

    grid_results = grid_search(closed, PARAM_GRID)
    best_params = {k: grid_results[0][k] for k in PARAM_GRID} if grid_results else {}
    wf = walk_forward_eval(closed, best_params)

    proposed_path = os.path.join(cfg.paths.learn_dir, "proposed_params.yaml")
    recs_path = os.path.join(cfg.paths.learn_dir, "recommendations.md")

    write_proposed_params(best_params, args.config, proposed_path)
    write_recommendations(grid_results, wf, closed, recs_path)

    print(f"\nOffline learning complete.")
    print(f"  Proposed params : {proposed_path}")
    print(f"  Recommendations : {recs_path}")
    print(f"\nBest in-sample params:")
    for k, v in best_params.items():
        print(f"  {k}: {v}")
    print(f"\nRemember: review and apply manually to config/settings.yaml.")


if __name__ == "__main__":
    main()
