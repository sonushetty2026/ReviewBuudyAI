"""
Configuration loader — parses and validates config/settings.yaml into typed dataclasses.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml


class ConfigError(Exception):
    """Raised when the configuration is invalid or contradictory."""


# ---------------------------------------------------------------------------
# Nested config dataclasses
# ---------------------------------------------------------------------------

@dataclass
class ModeConfig:
    paper_only: bool = True
    live_mode: bool = False
    dry_run: bool = False


@dataclass
class BrokerConfig:
    host: str = "127.0.0.1"
    port: int = 7497
    client_id: int = 1
    timeout_sec: int = 30
    reconnect_attempts: int = 5
    reconnect_backoff_sec: float = 2.0


@dataclass
class CircuitBreakerConfig:
    data_feed_stale_sec: int = 30
    order_reject_count: int = 3
    order_reject_window_sec: int = 300
    order_latency_sec: float = 5.0


@dataclass
class RiskConfig:
    max_daily_loss_usd: float = 75.0
    max_loss_per_trade_usd: float = 20.0
    max_trades_per_day: int = 6
    max_position_notional_usd: float = 600.0
    max_concurrent_positions: int = 1
    consecutive_loss_limit: int = 3
    spread_max_bps: float = 20.0
    circuit_breaker: CircuitBreakerConfig = field(default_factory=CircuitBreakerConfig)


@dataclass
class StrategyConfig:
    name: str = "ORB_VWAP"
    allow_shorts: bool = False
    or_minutes: int = 5
    vwap_filter_strength: int = 2
    atr_lookback: int = 14
    entry_limit_offset: float = 0.02
    stale_entry_cancel_sec: int = 60
    take_profit_r1: float = 1.5
    take_profit_r2: float = 2.0
    partial_exit_pct_at_r1: float = 0.5
    rs_lookback_bars: int = 3
    min_breakout_volume_ratio: float = 1.2


@dataclass
class ScheduleConfig:
    timezone: str = "America/Los_Angeles"
    prep_time: str = "06:15"
    market_open: str = "06:30"
    or_end_time: str = "06:35"
    trading_start: str = "06:35"
    trading_cutoff: str = "09:30"
    eod_flatten_time: str = "09:45"


@dataclass
class WatchlistFilters:
    min_price: float = 5.0
    max_spread_bps: float = 20.0
    min_premarket_volume: int = 50000


@dataclass
class WatchlistConfig:
    always_include: list[str] = field(
        default_factory=lambda: ["SPY", "QQQ", "XLE", "XOP", "USO", "GLD"]
    )
    extra: list[str] = field(default_factory=list)
    filters: WatchlistFilters = field(default_factory=WatchlistFilters)

    @property
    def symbols(self) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for s in self.always_include + self.extra:
            if s not in seen:
                seen.add(s)
                result.append(s)
        return result


@dataclass
class BoundedParam:
    min: float
    max: float
    default: float


@dataclass
class OnlineLearningConfig:
    enabled: bool = True
    rolling_window: int = 5
    position_size_multiplier: BoundedParam = field(
        default_factory=lambda: BoundedParam(min=0.25, max=1.0, default=1.0)
    )
    cooldown_minutes: BoundedParam = field(
        default_factory=lambda: BoundedParam(min=0, max=15, default=0)
    )
    vwap_filter_strength: BoundedParam = field(
        default_factory=lambda: BoundedParam(min=1, max=3, default=2)
    )
    or_minutes: BoundedParam = field(
        default_factory=lambda: BoundedParam(min=5, max=15, default=5)
    )
    win_rate_low_threshold: float = 0.30
    slippage_high_bps: float = 30.0
    vwap_reclaim_low_threshold: float = 0.40
    fake_breakout_ban_count: int = 2
    slippage_ban_bps: float = 50.0
    spread_ban_bps: float = 25.0


@dataclass
class PathsConfig:
    db: str = "data/trading.db"
    log_dir: str = "logs"
    report_dir: str = "reports"
    learn_dir: str = "learn_output"


@dataclass
class AppConfig:
    mode: ModeConfig
    broker: BrokerConfig
    risk: RiskConfig
    strategy: StrategyConfig
    schedule: ScheduleConfig
    watchlist: WatchlistConfig
    online_learning: OnlineLearningConfig
    paths: PathsConfig


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

def _dict_get(d: dict, *keys, default=None):
    """Safe nested dict access."""
    for key in keys:
        if not isinstance(d, dict):
            return default
        d = d.get(key, default)
    return d


def load_config(path: str) -> AppConfig:
    """
    Load and validate YAML configuration from *path*.
    Raises ConfigError on invalid or contradictory values.
    """
    config_path = Path(path)
    if not config_path.exists():
        raise ConfigError(f"Config file not found: {path}")

    with config_path.open() as f:
        raw = yaml.safe_load(f)

    if not isinstance(raw, dict):
        raise ConfigError("Config file must be a YAML mapping at the top level.")

    # ---- mode ----
    m = raw.get("mode", {})
    mode = ModeConfig(
        paper_only=bool(m.get("paper_only", True)),
        live_mode=bool(m.get("live_mode", False)),
        dry_run=bool(m.get("dry_run", False)),
    )

    # Safety gate: live_mode=True requires paper_only=False
    if mode.live_mode and mode.paper_only:
        raise ConfigError(
            "Contradictory config: live_mode=true requires paper_only=false. "
            "Set paper_only: false explicitly to enable live trading."
        )

    # ---- broker ----
    b = raw.get("broker", {})
    broker = BrokerConfig(
        host=str(b.get("host", "127.0.0.1")),
        port=int(b.get("port", 7497)),
        client_id=int(b.get("client_id", 1)),
        timeout_sec=int(b.get("timeout_sec", 30)),
        reconnect_attempts=int(b.get("reconnect_attempts", 5)),
        reconnect_backoff_sec=float(b.get("reconnect_backoff_sec", 2.0)),
    )

    # ---- risk ----
    r = raw.get("risk", {})
    cb = r.get("circuit_breaker", {})
    risk = RiskConfig(
        max_daily_loss_usd=float(r.get("max_daily_loss_usd", 75.0)),
        max_loss_per_trade_usd=float(r.get("max_loss_per_trade_usd", 20.0)),
        max_trades_per_day=int(r.get("max_trades_per_day", 6)),
        max_position_notional_usd=float(r.get("max_position_notional_usd", 600.0)),
        max_concurrent_positions=int(r.get("max_concurrent_positions", 1)),
        consecutive_loss_limit=int(r.get("consecutive_loss_limit", 3)),
        spread_max_bps=float(r.get("spread_max_bps", 20.0)),
        circuit_breaker=CircuitBreakerConfig(
            data_feed_stale_sec=int(cb.get("data_feed_stale_sec", 30)),
            order_reject_count=int(cb.get("order_reject_count", 3)),
            order_reject_window_sec=int(cb.get("order_reject_window_sec", 300)),
            order_latency_sec=float(cb.get("order_latency_sec", 5.0)),
        ),
    )

    # Validate risk limits
    if risk.max_daily_loss_usd <= 0:
        raise ConfigError("max_daily_loss_usd must be > 0")
    if risk.max_loss_per_trade_usd <= 0:
        raise ConfigError("max_loss_per_trade_usd must be > 0")
    if risk.max_loss_per_trade_usd > risk.max_daily_loss_usd:
        raise ConfigError(
            "max_loss_per_trade_usd cannot exceed max_daily_loss_usd"
        )

    # ---- strategy ----
    s = raw.get("strategy", {})
    strategy = StrategyConfig(
        name=str(s.get("name", "ORB_VWAP")),
        allow_shorts=bool(s.get("allow_shorts", False)),
        or_minutes=int(s.get("or_minutes", 5)),
        vwap_filter_strength=int(s.get("vwap_filter_strength", 2)),
        atr_lookback=int(s.get("atr_lookback", 14)),
        entry_limit_offset=float(s.get("entry_limit_offset", 0.02)),
        stale_entry_cancel_sec=int(s.get("stale_entry_cancel_sec", 60)),
        take_profit_r1=float(s.get("take_profit_r1", 1.5)),
        take_profit_r2=float(s.get("take_profit_r2", 2.0)),
        partial_exit_pct_at_r1=float(s.get("partial_exit_pct_at_r1", 0.5)),
        rs_lookback_bars=int(s.get("rs_lookback_bars", 3)),
        min_breakout_volume_ratio=float(s.get("min_breakout_volume_ratio", 1.2)),
    )

    # ---- schedule ----
    sc = raw.get("schedule", {})
    schedule = ScheduleConfig(
        timezone=str(sc.get("timezone", "America/Los_Angeles")),
        prep_time=str(sc.get("prep_time", "06:15")),
        market_open=str(sc.get("market_open", "06:30")),
        or_end_time=str(sc.get("or_end_time", "06:35")),
        trading_start=str(sc.get("trading_start", "06:35")),
        trading_cutoff=str(sc.get("trading_cutoff", "09:30")),
        eod_flatten_time=str(sc.get("eod_flatten_time", "09:45")),
    )

    # ---- watchlist ----
    wl = raw.get("watchlist", {})
    wl_filters = wl.get("filters", {})

    # Merge always_include + all named sub-groups into extra
    all_symbols: list[str] = list(wl.get("always_include", ["SPY", "QQQ", "XLE", "XOP", "USO", "GLD"]))
    for group_key in ("sector_liquid", "energy_majors", "defense_aero", "ai_highbeta"):
        group = wl.get(group_key, [])
        if isinstance(group, list):
            all_symbols.extend(group)
    extra_symbols = list(wl.get("extra", []))

    watchlist = WatchlistConfig(
        always_include=all_symbols,
        extra=extra_symbols,
        filters=WatchlistFilters(
            min_price=float(wl_filters.get("min_price", 5.0)),
            max_spread_bps=float(wl_filters.get("max_spread_bps", 20.0)),
            min_premarket_volume=int(wl_filters.get("min_premarket_volume", 50000)),
        ),
    )

    # ---- online learning ----
    ol = raw.get("online_learning", {})

    def _bounded(sub: dict, key: str, defaults: tuple) -> BoundedParam:
        d = ol.get(key, {})
        if not isinstance(d, dict):
            d = {}
        lo, hi, dflt = defaults
        return BoundedParam(
            min=float(d.get("min", lo)),
            max=float(d.get("max", hi)),
            default=float(d.get("default", dflt)),
        )

    online_learning = OnlineLearningConfig(
        enabled=bool(ol.get("enabled", True)),
        rolling_window=int(ol.get("rolling_window", 5)),
        position_size_multiplier=_bounded(ol, "position_size_multiplier", (0.25, 1.0, 1.0)),
        cooldown_minutes=_bounded(ol, "cooldown_minutes", (0, 15, 0)),
        vwap_filter_strength=_bounded(ol, "vwap_filter_strength", (1, 3, 2)),
        or_minutes=_bounded(ol, "or_minutes", (5, 15, 5)),
        win_rate_low_threshold=float(ol.get("win_rate_low_threshold", 0.30)),
        slippage_high_bps=float(ol.get("slippage_high_bps", 30.0)),
        vwap_reclaim_low_threshold=float(ol.get("vwap_reclaim_low_threshold", 0.40)),
        fake_breakout_ban_count=int(ol.get("fake_breakout_ban_count", 2)),
        slippage_ban_bps=float(ol.get("slippage_ban_bps", 50.0)),
        spread_ban_bps=float(ol.get("spread_ban_bps", 25.0)),
    )

    # ---- paths ----
    p = raw.get("paths", {})
    paths = PathsConfig(
        db=str(p.get("db", "data/trading.db")),
        log_dir=str(p.get("log_dir", "logs")),
        report_dir=str(p.get("report_dir", "reports")),
        learn_dir=str(p.get("learn_dir", "learn_output")),
    )

    # Ensure runtime directories exist
    for d in [paths.log_dir, paths.report_dir, paths.learn_dir, str(Path(paths.db).parent)]:
        os.makedirs(d, exist_ok=True)

    return AppConfig(
        mode=mode,
        broker=broker,
        risk=risk,
        strategy=strategy,
        schedule=schedule,
        watchlist=watchlist,
        online_learning=online_learning,
        paths=paths,
    )
