"""
Online Learning Controller — bounded intraday parameter adaptation.

After each completed trade, computes a diagnostic packet and updates
session parameters within pre-approved bounds.

HARD CONSTRAINTS (never violated):
  - Strategy type never changes
  - Entry/exit code logic never changes
  - New markets/instruments never enabled
  - Risk caps never removed
  - max_trades_remaining never increases
  - All params clamped to config bounds
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from .config_loader import OnlineLearningConfig, RiskConfig
from .logger import log_param_change

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class TradeDiagnostic:
    """Post-trade metrics computed after a position closes."""
    symbol: str
    side: str
    r_multiple: float               # e.g. 1.5 for winner, -1.0 for loser
    mae: float                      # max adverse excursion (negative = loss direction)
    mfe: float                      # max favorable excursion (positive = profit direction)
    slippage_bps: float             # (fill_price - limit_price) / limit_price * 10000
    spread_bps_at_entry: float
    entry_latency_ms: float         # ms from signal to entry fill
    partial_fill_rate: float        # filled_qty / requested_qty
    breakout_held_bars: int         # bars price stayed beyond breakout level
    vwap_reclaim: bool              # did price stay on correct side of VWAP through exit?
    was_winner: bool
    ts: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class LiveParams:
    """Current session's adjustable parameters (starts at config defaults)."""
    position_size_multiplier: float = 1.0
    cooldown_minutes: int = 0
    vwap_filter_strength: int = 2
    or_minutes: int = 5
    max_trades_remaining: int = 6

    # Read-only after set — banlist lives in RiskManager but mirrored here for logging
    symbol_banlist: dict[str, str] = field(default_factory=dict)


@dataclass
class ParamChangeLog:
    ts: str
    param: str
    old_value: object
    new_value: object
    reason: str


# ---------------------------------------------------------------------------
# Controller
# ---------------------------------------------------------------------------

class OnlineLearningController:
    """
    Maintains a rolling window of recent trade diagnostics and adjusts
    LiveParams after each completed trade.
    """

    def __init__(
        self,
        cfg: OnlineLearningConfig,
        risk_cfg: RiskConfig,
        initial_max_trades: int,
        app_logger: logging.Logger,
    ):
        self._cfg = cfg
        self._risk_cfg = risk_cfg
        self._log = app_logger

        self._window: deque[TradeDiagnostic] = deque(maxlen=cfg.rolling_window)
        self._all_diags: list[TradeDiagnostic] = []
        self._change_log: list[ParamChangeLog] = []

        # Initialise params from config defaults
        self._params = LiveParams(
            position_size_multiplier=cfg.position_size_multiplier.default,
            cooldown_minutes=int(cfg.cooldown_minutes.default),
            vwap_filter_strength=int(cfg.vwap_filter_strength.default),
            or_minutes=int(cfg.or_minutes.default),
            max_trades_remaining=initial_max_trades,
        )

        # Fake-breakout counter per symbol
        self._fake_breakouts: dict[str, int] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record_trade(self, diag: TradeDiagnostic) -> list[ParamChangeLog]:
        """
        Record a completed trade, evaluate the rolling window, and
        apply any bounded adjustments.  Returns new change log entries.
        """
        if not self._cfg.enabled:
            return []

        self._window.append(diag)
        self._all_diags.append(diag)
        self._params.max_trades_remaining = max(
            0, self._params.max_trades_remaining - 1
        )

        # Track fake breakouts
        if not diag.was_winner and diag.breakout_held_bars <= 2:
            self._fake_breakouts[diag.symbol] = self._fake_breakouts.get(diag.symbol, 0) + 1

        changes = self._evaluate_and_update()
        return changes

    def check_ban_after_trade(
        self, symbol: str, slippage_bps: float, spread_bps: float, halt: bool = False
    ) -> Optional[str]:
        """
        Check if a symbol should be banned. Returns ban reason or None.
        """
        if not self._cfg.enabled:
            return None

        reasons: list[str] = []

        if self._fake_breakouts.get(symbol, 0) >= self._cfg.fake_breakout_ban_count:
            reasons.append(f"fake_breakouts>={self._cfg.fake_breakout_ban_count}")

        if slippage_bps > self._cfg.slippage_ban_bps:
            reasons.append(f"slippage={slippage_bps:.1f}bps>{self._cfg.slippage_ban_bps}bps")

        if spread_bps > self._cfg.spread_ban_bps:
            reasons.append(f"spread={spread_bps:.1f}bps>{self._cfg.spread_ban_bps}bps")

        if halt:
            reasons.append("halt_detected")

        if reasons:
            reason = "; ".join(reasons)
            self._params.symbol_banlist[symbol] = reason
            logger.info("Symbol %s banned for session: %s", symbol, reason)
            return reason

        return None

    def get_params(self) -> LiveParams:
        return self._params

    def get_session_log(self) -> list[dict]:
        return [
            {
                "ts": c.ts,
                "param": c.param,
                "old_value": c.old_value,
                "new_value": c.new_value,
                "reason": c.reason,
            }
            for c in self._change_log
        ]

    # ------------------------------------------------------------------
    # Parameter evaluation
    # ------------------------------------------------------------------

    def _evaluate_and_update(self) -> list[ParamChangeLog]:
        """Analyse rolling window and apply bounded parameter adjustments."""
        if len(self._window) < max(2, self._cfg.rolling_window // 2):
            return []   # Not enough data yet

        diags = list(self._window)
        new_changes: list[ParamChangeLog] = []

        win_rate = sum(1 for d in diags if d.was_winner) / len(diags)
        avg_slippage = sum(d.slippage_bps for d in diags) / len(diags)
        vwap_reclaim_rate = sum(1 for d in diags if d.vwap_reclaim) / len(diags)

        # 1. Win rate low → reduce position size multiplier
        if win_rate < self._cfg.win_rate_low_threshold:
            new_mult = max(
                self._cfg.position_size_multiplier.min,
                self._params.position_size_multiplier * 0.75,
            )
            if new_mult < self._params.position_size_multiplier - 0.001:
                change = self._update_param(
                    "position_size_multiplier",
                    new_mult,
                    f"win_rate={win_rate:.2%} < {self._cfg.win_rate_low_threshold:.2%}",
                )
                new_changes.append(change)

        # 2. High slippage → increase cooldown
        if avg_slippage > self._cfg.slippage_high_bps:
            new_cool = min(
                int(self._cfg.cooldown_minutes.max),
                self._params.cooldown_minutes + 2,
            )
            if new_cool > self._params.cooldown_minutes:
                change = self._update_param(
                    "cooldown_minutes",
                    new_cool,
                    f"avg_slippage={avg_slippage:.1f}bps > {self._cfg.slippage_high_bps}bps",
                )
                new_changes.append(change)

        # 3. Low VWAP reclaim → tighten VWAP filter
        if vwap_reclaim_rate < self._cfg.vwap_reclaim_low_threshold:
            new_strength = min(
                int(self._cfg.vwap_filter_strength.max),
                self._params.vwap_filter_strength + 1,
            )
            if new_strength > self._params.vwap_filter_strength:
                change = self._update_param(
                    "vwap_filter_strength",
                    new_strength,
                    f"vwap_reclaim_rate={vwap_reclaim_rate:.2%} < "
                    f"{self._cfg.vwap_reclaim_low_threshold:.2%}",
                )
                new_changes.append(change)

        # 4. Repeated fake breakouts (3+ in window) → widen OR window
        fake_count = sum(
            1 for d in diags if not d.was_winner and d.breakout_held_bars <= 2
        )
        if fake_count >= 3:
            new_or = min(
                int(self._cfg.or_minutes.max),
                self._params.or_minutes + 2,
            )
            if new_or > self._params.or_minutes:
                change = self._update_param(
                    "or_minutes",
                    new_or,
                    f"fake_breakouts_in_window={fake_count}",
                )
                new_changes.append(change)

        return new_changes

    def _update_param(self, name: str, new_value: object, reason: str) -> ParamChangeLog:
        old_value = getattr(self._params, name)
        setattr(self._params, name, new_value)

        log_param_change(
            self._log,
            param=name,
            old_value=old_value,
            new_value=new_value,
            reason=reason,
        )

        entry = ParamChangeLog(
            ts=datetime.now(timezone.utc).isoformat(),
            param=name,
            old_value=old_value,
            new_value=new_value,
            reason=reason,
        )
        self._change_log.append(entry)
        return entry

    # ------------------------------------------------------------------
    # Rolling stats for reporting
    # ------------------------------------------------------------------

    def get_session_stats(self) -> dict:
        if not self._all_diags:
            return {}
        wins = [d for d in self._all_diags if d.was_winner]
        return {
            "total_trades": len(self._all_diags),
            "win_rate": len(wins) / len(self._all_diags),
            "avg_r": sum(d.r_multiple for d in self._all_diags) / len(self._all_diags),
            "avg_slippage_bps": sum(d.slippage_bps for d in self._all_diags) / len(self._all_diags),
            "param_changes_count": len(self._change_log),
            "current_params": {
                "position_size_multiplier": self._params.position_size_multiplier,
                "cooldown_minutes": self._params.cooldown_minutes,
                "vwap_filter_strength": self._params.vwap_filter_strength,
                "or_minutes": self._params.or_minutes,
            },
        }
