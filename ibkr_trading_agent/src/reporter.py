"""
End-of-day report generator.

Outputs for each session:
  - trades.csv        — per-trade detail
  - summary.md        — human-readable session summary
  - equity_curve.png  — cumulative PnL over time
  - r_distribution.png — R-multiple histogram
  - pnl_by_hour.png   — PnL grouped by hour

Run standalone:  python -m src.reporter --config config/settings.yaml --date 2024-01-15
"""

from __future__ import annotations

import argparse
import csv
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class EODReporter:
    """Reads from SQLite and generates all report artefacts."""

    def __init__(self, storage, config):
        self._storage = storage
        self._cfg = config

    def generate_all(self, run_id: str, date_str: str,
                     ol_session_log: Optional[list] = None) -> str:
        """
        Generate all report files for *run_id*.
        Returns the path to the report directory.
        """
        report_dir = os.path.join(self._cfg.paths.report_dir, date_str)
        os.makedirs(report_dir, exist_ok=True)

        positions = self._storage.get_closed_positions_for_run(run_id)
        pnl_snaps = self._storage.get_pnl_snapshots_for_run(run_id)
        errors = self._storage.get_errors_for_run(run_id)
        orders = self._storage.get_orders_for_run(run_id)

        stats = self._compute_stats(positions, pnl_snaps)

        self._write_trades_csv(positions, os.path.join(report_dir, "trades.csv"))
        self._write_summary_md(
            stats, errors, ol_session_log or [],
            os.path.join(report_dir, "summary.md"), date_str,
        )
        self._plot_equity_curve(pnl_snaps, os.path.join(report_dir, "equity_curve.png"))
        self._plot_r_distribution(positions, os.path.join(report_dir, "r_distribution.png"))
        self._plot_pnl_by_hour(positions, os.path.join(report_dir, "pnl_by_hour.png"))

        logger.info("EOD report written to %s", report_dir)
        return report_dir

    # ------------------------------------------------------------------
    # CSV
    # ------------------------------------------------------------------

    def _write_trades_csv(self, positions: list[dict], path: str) -> None:
        if not positions:
            return
        fields = [
            "id", "symbol", "entry_price", "qty", "stop_price", "tp1_price", "tp2_price",
            "open_ts", "close_ts", "realized_pnl", "r_multiple", "mae", "mfe",
        ]
        with open(path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            w.writeheader()
            w.writerows(positions)

    # ------------------------------------------------------------------
    # Summary markdown
    # ------------------------------------------------------------------

    def _write_summary_md(
        self,
        stats: dict,
        errors: list[dict],
        ol_log: list[dict],
        path: str,
        date_str: str,
    ) -> None:
        lines: list[str] = []

        lines.append(f"# Session Report — {date_str}\n")
        lines.append(f"*Generated at {datetime.now(timezone.utc).isoformat()}*\n")
        lines.append("")

        lines.append("## P&L Summary\n")
        lines.append(f"| Metric | Value |")
        lines.append(f"|--------|-------|")
        lines.append(f"| Total Realized P&L | ${stats.get('total_pnl', 0):.2f} |")
        lines.append(f"| Total Trades | {stats.get('total_trades', 0)} |")
        lines.append(f"| Winning Trades | {stats.get('winners', 0)} |")
        lines.append(f"| Losing Trades | {stats.get('losers', 0)} |")
        lines.append(f"| Win Rate | {stats.get('win_rate', 0):.1%} |")
        lines.append(f"| Avg R Multiple | {stats.get('avg_r', 0):.3f}R |")
        lines.append(f"| Best Trade | ${stats.get('best_trade', 0):.2f} |")
        lines.append(f"| Worst Trade | ${stats.get('worst_trade', 0):.2f} |")
        lines.append(f"| Max Drawdown | ${stats.get('max_drawdown', 0):.2f} |")
        lines.append(f"| Est. Avg Slippage | {stats.get('avg_slippage_bps', 0):.1f} bps |")
        lines.append("")

        lines.append("## Trade Log\n")
        lines.append("| Symbol | Side | Entry | Exit | P&L | R |")
        lines.append("|--------|------|-------|------|-----|---|")
        for t in stats.get("_trades", []):
            side = "LONG" if t.get("qty", 0) > 0 else "SHORT"
            lines.append(
                f"| {t.get('symbol','')} | {side} "
                f"| {t.get('entry_price',0):.2f} | — "
                f"| ${t.get('realized_pnl',0):.2f} "
                f"| {t.get('r_multiple',0):.2f}R |"
            )
        lines.append("")

        if ol_log:
            lines.append("## Intraday Parameter Changes (Online Learning)\n")
            lines.append("| Time | Parameter | Old | New | Reason |")
            lines.append("|------|-----------|-----|-----|--------|")
            for c in ol_log:
                lines.append(
                    f"| {c.get('ts','')} | {c.get('param','')} "
                    f"| {c.get('old_value','')} | {c.get('new_value','')} "
                    f"| {c.get('reason','')} |"
                )
            lines.append("")

        if errors:
            lines.append("## Errors & Outages\n")
            for e in errors:
                lines.append(
                    f"- `{e.get('ts','')}` [{e.get('module','')}] "
                    f"{e.get('error_type','')}: {e.get('message','')}"
                )
            lines.append("")

        lines.append("---\n*Report auto-generated by IBKR Trading Agent*\n")

        with open(path, "w") as f:
            f.write("\n".join(lines))

    # ------------------------------------------------------------------
    # Plots
    # ------------------------------------------------------------------

    def _plot_equity_curve(self, pnl_snaps: list[dict], path: str) -> None:
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt

            if not pnl_snaps:
                return

            times = [p["ts"] for p in pnl_snaps]
            total_pnl = [p["total_pnl"] for p in pnl_snaps]

            fig, ax = plt.subplots(figsize=(12, 5))
            colors = ["green" if v >= 0 else "red" for v in total_pnl]
            ax.plot(range(len(total_pnl)), total_pnl, color="steelblue", linewidth=1.5)
            ax.fill_between(
                range(len(total_pnl)),
                total_pnl,
                0,
                where=[v >= 0 for v in total_pnl],
                alpha=0.3, color="green",
            )
            ax.fill_between(
                range(len(total_pnl)),
                total_pnl,
                0,
                where=[v < 0 for v in total_pnl],
                alpha=0.3, color="red",
            )
            ax.axhline(0, color="black", linewidth=0.5, linestyle="--")
            ax.set_title("Session Equity Curve")
            ax.set_xlabel("Snapshot #")
            ax.set_ylabel("Total P&L ($)")
            ax.grid(True, alpha=0.3)
            plt.tight_layout()
            plt.savefig(path, dpi=120)
            plt.close()
        except Exception as exc:
            logger.warning("equity_curve plot failed: %s", exc)

    def _plot_r_distribution(self, positions: list[dict], path: str) -> None:
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt

            if not positions:
                return

            rs = [p.get("r_multiple", 0) for p in positions if p.get("r_multiple") is not None]
            if not rs:
                return

            fig, ax = plt.subplots(figsize=(8, 4))
            colors = ["green" if r > 0 else "red" for r in rs]
            ax.bar(range(len(rs)), rs, color=colors, edgecolor="black", linewidth=0.5)
            ax.axhline(0, color="black", linewidth=0.8)
            ax.set_title("Per-Trade R Multiple")
            ax.set_xlabel("Trade #")
            ax.set_ylabel("R Multiple")
            ax.grid(True, alpha=0.3, axis="y")
            plt.tight_layout()
            plt.savefig(path, dpi=120)
            plt.close()
        except Exception as exc:
            logger.warning("r_distribution plot failed: %s", exc)

    def _plot_pnl_by_hour(self, positions: list[dict], path: str) -> None:
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            from collections import defaultdict

            if not positions:
                return

            hourly: dict[int, float] = defaultdict(float)
            for p in positions:
                ts = p.get("open_ts", "")
                pnl = p.get("realized_pnl", 0) or 0
                try:
                    hour = datetime.fromisoformat(ts).hour
                    hourly[hour] += pnl
                except Exception:
                    pass

            if not hourly:
                return

            hours = sorted(hourly)
            pnls = [hourly[h] for h in hours]
            colors = ["green" if p >= 0 else "red" for p in pnls]

            fig, ax = plt.subplots(figsize=(10, 4))
            ax.bar(hours, pnls, color=colors, edgecolor="black", linewidth=0.5)
            ax.axhline(0, color="black", linewidth=0.8)
            ax.set_title("P&L by Hour (UTC)")
            ax.set_xlabel("Hour (UTC)")
            ax.set_ylabel("P&L ($)")
            ax.set_xticks(hours)
            ax.grid(True, alpha=0.3, axis="y")
            plt.tight_layout()
            plt.savefig(path, dpi=120)
            plt.close()
        except Exception as exc:
            logger.warning("pnl_by_hour plot failed: %s", exc)

    # ------------------------------------------------------------------
    # Stats computation
    # ------------------------------------------------------------------

    def _compute_stats(self, positions: list[dict], pnl_snaps: list[dict]) -> dict:
        if not positions:
            return {
                "total_pnl": 0.0, "total_trades": 0, "winners": 0, "losers": 0,
                "win_rate": 0.0, "avg_r": 0.0, "best_trade": 0.0, "worst_trade": 0.0,
                "max_drawdown": 0.0, "avg_slippage_bps": 0.0, "_trades": [],
            }

        pnls = [p.get("realized_pnl", 0) or 0 for p in positions]
        rs = [p.get("r_multiple", 0) or 0 for p in positions]
        winners = [x for x in pnls if x > 0]
        losers = [x for x in pnls if x <= 0]

        # Max drawdown from PnL snapshots
        max_dd = 0.0
        if pnl_snaps:
            totals = [s.get("total_pnl", 0) for s in pnl_snaps]
            peak = totals[0]
            for v in totals:
                peak = max(peak, v)
                dd = peak - v
                max_dd = max(max_dd, dd)

        return {
            "total_pnl": sum(pnls),
            "total_trades": len(positions),
            "winners": len(winners),
            "losers": len(losers),
            "win_rate": len(winners) / len(positions),
            "avg_r": sum(rs) / len(rs) if rs else 0.0,
            "best_trade": max(pnls),
            "worst_trade": min(pnls),
            "max_drawdown": max_dd,
            "avg_slippage_bps": 0.0,  # placeholder (slippage tracked in diagnostics)
            "_trades": positions,
        }


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Generate EOD report from stored data.")
    parser.add_argument("--config", default="config/settings.yaml")
    parser.add_argument("--date", default=None, help="Session date YYYY-MM-DD (default: today)")
    parser.add_argument("--run-id", default=None, help="Specific run_id (default: most recent)")
    args = parser.parse_args()

    from .config_loader import load_config
    from .storage import Storage

    cfg = load_config(args.config)
    storage = Storage(cfg.paths.db)

    date_str = args.date or datetime.now(timezone.utc).strftime("%Y-%m-%d")

    if args.run_id:
        run_id = args.run_id
    else:
        runs = storage.get_all_runs()
        if not runs:
            print("No runs found in database.")
            sys.exit(1)
        run_id = runs[-1]["run_id"]
        print(f"Using most recent run: {run_id}")

    reporter = EODReporter(storage, cfg)
    report_dir = reporter.generate_all(run_id, date_str)
    print(f"Report written to: {report_dir}")


if __name__ == "__main__":
    main()
