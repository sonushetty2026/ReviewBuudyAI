"""
Unit tests for RiskManager veto conditions.
"""

import pytest
from src.risk_manager import RiskManager
from src.config_loader import RiskConfig, CircuitBreakerConfig


def make_risk(
    max_daily_loss: float = 75.0,
    max_loss_per_trade: float = 20.0,
    max_trades: int = 6,
    max_notional: float = 600.0,
    max_concurrent: int = 1,
    consecutive_limit: int = 3,
) -> RiskManager:
    cfg = RiskConfig(
        max_daily_loss_usd=max_daily_loss,
        max_loss_per_trade_usd=max_loss_per_trade,
        max_trades_per_day=max_trades,
        max_position_notional_usd=max_notional,
        max_concurrent_positions=max_concurrent,
        consecutive_loss_limit=consecutive_limit,
        spread_max_bps=20.0,
        circuit_breaker=CircuitBreakerConfig(),
    )
    return RiskManager(cfg)


# ---------------------------------------------------------------------------
# Circuit breaker
# ---------------------------------------------------------------------------

def test_circuit_breaker_veto():
    rm = make_risk()
    rm.trip_circuit_breaker("test")
    approved, reason = rm.approve_entry("SPY", "BUY", 100.0, 99.0, 5)
    assert not approved
    assert "circuit_breaker" in reason


def test_circuit_breaker_starts_clear():
    rm = make_risk()
    assert not rm.is_circuit_broken()


# ---------------------------------------------------------------------------
# Max trades per day
# ---------------------------------------------------------------------------

def test_max_trades_veto():
    rm = make_risk(max_trades=2)
    # Simulate 2 fills
    rm.record_entry_fill("SPY", "BUY", 100.0, 5)
    rm.record_exit("SPY", 101.0, 5)
    rm.record_entry_fill("QQQ", "BUY", 200.0, 2)
    rm.record_exit("QQQ", 201.0, 2)
    # Third entry should be vetoed
    approved, reason = rm.approve_entry("XLE", "BUY", 50.0, 49.0, 3)
    assert not approved
    assert "max_trades_per_day" in reason


def test_trades_allowed_before_cap():
    rm = make_risk(max_trades=6)
    approved, _ = rm.approve_entry("SPY", "BUY", 100.0, 99.0, 5)
    assert approved


# ---------------------------------------------------------------------------
# Daily loss limit
# ---------------------------------------------------------------------------

def test_daily_loss_veto_after_loss():
    rm = make_risk(max_daily_loss=30.0, max_loss_per_trade=25.0)
    # Record a big loss
    rm.record_entry_fill("SPY", "BUY", 100.0, 10)
    rm.record_exit("SPY", 97.0, 10)   # -$30 → limit hit
    # Next entry should be vetoed
    approved, reason = rm.approve_entry("QQQ", "BUY", 50.0, 49.0, 3)
    assert not approved


def test_trade_loss_exceeds_cap():
    rm = make_risk(max_loss_per_trade=20.0)
    # Entry=100, stop=97 → risk=3 per share × 10 shares = $30 > $20 cap
    approved, reason = rm.approve_entry("SPY", "BUY", 100.0, 97.0, 10)
    assert not approved
    assert "trade_loss_exceeds_cap" in reason


# ---------------------------------------------------------------------------
# Max concurrent positions
# ---------------------------------------------------------------------------

def test_concurrent_positions_veto():
    rm = make_risk(max_concurrent=1)
    # Open first position
    rm.record_entry_fill("SPY", "BUY", 100.0, 3)
    # Second position should be vetoed
    approved, reason = rm.approve_entry("QQQ", "BUY", 200.0, 199.0, 1)
    assert not approved
    assert "max_concurrent" in reason


def test_allows_entry_when_under_limit():
    rm = make_risk(max_concurrent=2)
    rm.record_entry_fill("SPY", "BUY", 100.0, 3)
    # Second position OK with limit=2
    approved, _ = rm.approve_entry("QQQ", "BUY", 200.0, 199.0, 1)
    assert approved


# ---------------------------------------------------------------------------
# Notional cap
# ---------------------------------------------------------------------------

def test_notional_veto():
    rm = make_risk(max_notional=600.0)
    # price=100, qty=7 → notional=700 > 600 → reject
    approved, reason = rm.approve_entry("SPY", "BUY", 100.0, 99.0, 7)
    assert not approved
    assert "notional_cap" in reason


def test_notional_at_exact_limit():
    rm = make_risk(max_notional=600.0)
    # price=100, qty=6 → notional=600 → OK
    approved, _ = rm.approve_entry("SPY", "BUY", 100.0, 99.0, 6)
    assert approved


# ---------------------------------------------------------------------------
# Stop distance validation
# ---------------------------------------------------------------------------

def test_stop_too_tight_veto():
    rm = make_risk()
    # stop_dist = 0.001 < 0.01 → reject
    approved, reason = rm.approve_entry("SPY", "BUY", 100.0, 99.999, 3)
    assert not approved
    assert "stop_too_tight" in reason


def test_stop_too_wide_veto():
    # max_loss_per_trade=50 so potential_loss=15*1=15 < 50 (loss check passes)
    # stop_dist=15 → 15% of price=100 → > 10% → stop_too_wide fires
    rm = make_risk(max_loss_per_trade=50.0)
    approved, reason = rm.approve_entry("SPY", "BUY", 100.0, 85.0, 1)
    assert not approved
    assert "stop_too_wide" in reason


def test_valid_stop_distance():
    rm = make_risk()
    # stop_dist = 2 → 2% → valid
    approved, _ = rm.approve_entry("SPY", "BUY", 100.0, 98.0, 3)
    assert approved


# ---------------------------------------------------------------------------
# Consecutive losses
# ---------------------------------------------------------------------------

def test_consecutive_loss_stop():
    rm = make_risk(consecutive_limit=3, max_loss_per_trade=50.0)
    # Three losses in a row
    for sym in ["SPY", "QQQ", "XLE"]:
        rm.record_entry_fill(sym, "BUY", 100.0, 1)
        rm.record_exit(sym, 99.0, 1)  # each -$1

    # 4th trade should be blocked
    approved, reason = rm.approve_entry("USO", "BUY", 10.0, 9.5, 1)
    assert not approved
    assert "consecutive_loss_limit" in reason


def test_win_resets_consecutive_losses():
    rm = make_risk(consecutive_limit=3, max_loss_per_trade=50.0, max_concurrent=3)
    # Two losses
    rm.record_entry_fill("SPY", "BUY", 100.0, 1)
    rm.record_exit("SPY", 99.0, 1)
    rm.record_entry_fill("QQQ", "BUY", 100.0, 1)
    rm.record_exit("QQQ", 99.0, 1)
    assert rm.consecutive_losses == 2
    # Win resets
    rm.record_entry_fill("XLE", "BUY", 50.0, 1)
    rm.record_exit("XLE", 52.0, 1)
    assert rm.consecutive_losses == 0


# ---------------------------------------------------------------------------
# PnL tracking
# ---------------------------------------------------------------------------

def test_realized_pnl_long_winner():
    rm = make_risk()
    rm.record_entry_fill("SPY", "BUY", 100.0, 5)
    pnl = rm.record_exit("SPY", 102.0, 5)
    assert abs(pnl - 10.0) < 0.001
    assert abs(rm.realized_pnl - 10.0) < 0.001


def test_realized_pnl_long_loser():
    rm = make_risk()
    rm.record_entry_fill("SPY", "BUY", 100.0, 5)
    pnl = rm.record_exit("SPY", 98.0, 5)
    assert abs(pnl - (-10.0)) < 0.001
    assert abs(rm.realized_pnl - (-10.0)) < 0.001


def test_daily_loss_remaining():
    rm = make_risk(max_daily_loss=75.0)
    rm.record_entry_fill("SPY", "BUY", 100.0, 5)
    rm.record_exit("SPY", 99.0, 5)  # -$5
    assert abs(rm.daily_loss_remaining - 70.0) < 0.01


# ---------------------------------------------------------------------------
# Symbol banlist
# ---------------------------------------------------------------------------

def test_banlist_veto():
    rm = make_risk()
    rm.add_to_banlist("SPY", "fake_breakout")
    approved, reason = rm.approve_entry("SPY", "BUY", 100.0, 99.0, 3)
    assert not approved
    assert "symbol_banned" in reason


def test_other_symbols_not_banned():
    rm = make_risk()
    rm.add_to_banlist("SPY", "test")
    approved, _ = rm.approve_entry("QQQ", "BUY", 200.0, 199.0, 1)
    assert approved


# ---------------------------------------------------------------------------
# Cooldown
# ---------------------------------------------------------------------------

def test_cooldown_blocks_entry():
    rm = make_risk()
    rm.set_cooldown(5)  # 5-minute cooldown
    approved, reason = rm.approve_entry("SPY", "BUY", 100.0, 99.0, 3)
    assert not approved
    assert "cooldown" in reason
