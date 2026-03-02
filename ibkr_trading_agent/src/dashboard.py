"""
Terminal dashboard — Rich Live display with real-time status.

Shows:
  - Connection status + trading phase
  - Current time (PST/PDT)
  - Watchlist: price, VWAP distance, OR levels, signal state, spread
  - Open positions: side, qty, entry, stop, TPs, unrealized PnL
  - Daily stats: realized PnL, trades remaining, loss remaining
  - Circuit breaker status
  - Online learning params
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from rich.columns import Columns
from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text


# ---------------------------------------------------------------------------
# Agent state snapshot (passed to dashboard every tick)
# ---------------------------------------------------------------------------

@dataclass
class WatchlistEntry:
    symbol: str
    price: float = math.nan
    vwap: float = math.nan
    or_high: Optional[float] = None
    or_low: Optional[float] = None
    spread_bps: float = math.nan
    signal_state: str = "WAIT"      # WAIT | RECORDING | WATCH | LONG! | SHORT! | BANNED
    or_complete: bool = False


@dataclass
class PositionEntry:
    symbol: str
    side: str
    qty: int
    entry_price: float
    stop_price: float
    tp1_price: float
    tp2_price: float
    current_price: float
    unrealized_pnl: float


@dataclass
class AgentState:
    connected: bool = False
    mode: str = "paper"             # paper | dry_run | live
    phase: str = "WAITING"          # WAITING | PREP | OR_RECORDING | TRADING | WIND_DOWN | DONE
    circuit_broken: bool = False
    circuit_reason: str = ""

    watchlist: list[WatchlistEntry] = field(default_factory=list)
    positions: list[PositionEntry] = field(default_factory=list)

    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    trades_today: int = 0
    trades_remaining: int = 6
    daily_loss_remaining: float = 75.0
    consecutive_losses: int = 0

    # Online learning
    ol_size_mult: float = 1.0
    ol_cooldown: int = 0
    ol_vwap_str: int = 2
    ol_or_min: int = 5

    tz: str = "America/Los_Angeles"


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

class Dashboard:
    """Rich Live terminal dashboard."""

    def __init__(self, tz: str = "America/Los_Angeles"):
        self._tz = ZoneInfo(tz)
        self._console = Console()
        self._live: Optional[Live] = None
        self._state: AgentState = AgentState()

    def start(self) -> None:
        self._live = Live(
            self._build(),
            console=self._console,
            refresh_per_second=1,
            screen=False,
        )
        self._live.start()

    def stop(self) -> None:
        if self._live:
            self._live.stop()

    def update(self, state: AgentState) -> None:
        self._state = state
        if self._live:
            self._live.update(self._build())

    # ------------------------------------------------------------------
    # Build renderables
    # ------------------------------------------------------------------

    def _build(self) -> Panel:
        s = self._state
        now_local = datetime.now(self._tz)
        time_str = now_local.strftime("%Y-%m-%d  %H:%M:%S %Z")

        # Header bar
        conn_color = "green" if s.connected else "red"
        conn_text = "CONNECTED" if s.connected else "DISCONNECTED"
        mode_badge = f"[bold cyan]{s.mode.upper()}[/bold cyan]"
        circuit_badge = (
            f"[bold red] ⚡ CIRCUIT BROKEN: {s.circuit_reason}[/bold red]"
            if s.circuit_broken else ""
        )

        header = (
            f"[{conn_color}]● {conn_text}[/{conn_color}]  {mode_badge}  "
            f"Phase: [bold yellow]{s.phase}[/bold yellow]  "
            f"{time_str}{circuit_badge}"
        )

        content = Layout()
        content.split_column(
            Layout(name="header", size=1),
            Layout(name="watchlist", size=len(s.watchlist) + 4),
            Layout(name="positions", size=max(3, len(s.positions) + 3)),
            Layout(name="stats", size=5),
        )

        content["header"].update(Text.from_markup(header))
        content["watchlist"].update(self._build_watchlist(s))
        content["positions"].update(self._build_positions(s))
        content["stats"].update(self._build_stats(s))

        return Panel(content, title="[bold]IBKR Trading Agent[/bold]",
                     border_style="blue", padding=(0, 1))

    def _build_watchlist(self, s: AgentState) -> Table:
        t = Table(title="Watchlist", show_header=True, header_style="bold magenta",
                  box=None, padding=(0, 1))
        t.add_column("Symbol", width=7)
        t.add_column("Price", justify="right", width=9)
        t.add_column("VWAP%", justify="right", width=8)
        t.add_column("OR-H", justify="right", width=8)
        t.add_column("OR-L", justify="right", width=8)
        t.add_column("Spread", justify="right", width=8)
        t.add_column("Signal", justify="center", width=10)

        for e in s.watchlist:
            price_str = f"{e.price:.2f}" if not math.isnan(e.price) else "—"

            if not math.isnan(e.price) and not math.isnan(e.vwap) and e.vwap > 0:
                vwap_pct = (e.price - e.vwap) / e.vwap * 100
                vwap_str = f"{vwap_pct:+.2f}%"
                vwap_color = "green" if vwap_pct > 0 else "red"
            else:
                vwap_str, vwap_color = "—", "white"

            or_h = f"{e.or_high:.2f}" if e.or_high else "—"
            or_l = f"{e.or_low:.2f}" if e.or_low else "—"
            spread = f"{e.spread_bps:.1f}bps" if not math.isnan(e.spread_bps) else "—"

            signal_colors = {
                "LONG!": "bold green", "SHORT!": "bold red",
                "WATCH": "yellow", "RECORDING": "cyan",
                "WAIT": "dim", "BANNED": "bold red",
            }
            sig_color = signal_colors.get(e.signal_state, "white")

            t.add_row(
                f"[bold]{e.symbol}[/bold]",
                price_str,
                f"[{vwap_color}]{vwap_str}[/{vwap_color}]",
                or_h, or_l, spread,
                f"[{sig_color}]{e.signal_state}[/{sig_color}]",
            )
        return t

    def _build_positions(self, s: AgentState) -> Table:
        t = Table(title="Open Positions", show_header=True, header_style="bold magenta",
                  box=None, padding=(0, 1))
        t.add_column("Symbol", width=7)
        t.add_column("Side", width=5)
        t.add_column("Qty", justify="right", width=5)
        t.add_column("Entry", justify="right", width=9)
        t.add_column("Stop", justify="right", width=9)
        t.add_column("TP1", justify="right", width=9)
        t.add_column("TP2", justify="right", width=9)
        t.add_column("Unreal P&L", justify="right", width=12)

        if not s.positions:
            t.add_row("—", "—", "—", "—", "—", "—", "—", "—")
        else:
            for p in s.positions:
                color = "green" if p.unrealized_pnl >= 0 else "red"
                side_color = "green" if p.side == "BUY" else "red"
                t.add_row(
                    f"[bold]{p.symbol}[/bold]",
                    f"[{side_color}]{p.side}[/{side_color}]",
                    str(p.qty),
                    f"{p.entry_price:.2f}",
                    f"{p.stop_price:.2f}",
                    f"{p.tp1_price:.2f}",
                    f"{p.tp2_price:.2f}",
                    f"[{color}]{p.unrealized_pnl:+.2f}[/{color}]",
                )
        return t

    def _build_stats(self, s: AgentState) -> Table:
        t = Table(show_header=False, box=None, padding=(0, 2))
        t.add_column("Key", width=25)
        t.add_column("Value", width=15)
        t.add_column("Key2", width=25)
        t.add_column("Value2", width=15)

        pnl_color = "green" if s.realized_pnl >= 0 else "red"
        total_pnl = s.realized_pnl + s.unrealized_pnl
        total_color = "green" if total_pnl >= 0 else "red"

        t.add_row(
            "Realized P&L",
            f"[{pnl_color}]{s.realized_pnl:+.2f}[/{pnl_color}]",
            "Trades Today",
            f"{s.trades_today} / {s.trades_today + s.trades_remaining}",
        )
        t.add_row(
            "Total P&L",
            f"[{total_color}]{total_pnl:+.2f}[/{total_color}]",
            "Loss Remaining",
            f"${s.daily_loss_remaining:.2f}",
        )
        t.add_row(
            "Consecutive Losses",
            str(s.consecutive_losses),
            "OL: size/cool/vwap/or",
            f"{s.ol_size_mult:.2f} / {s.ol_cooldown}m / {s.ol_vwap_str} / {s.ol_or_min}m",
        )
        return t
