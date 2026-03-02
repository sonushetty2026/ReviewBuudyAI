"""
Unit tests for position sizing logic in RiskManager.
"""

import math
import pytest

from src.risk_manager import RiskManager
from src.config_loader import RiskConfig, CircuitBreakerConfig


def make_risk(
    max_notional: float = 600.0,
    max_loss: float = 20.0,
) -> RiskManager:
    cfg = RiskConfig(
        max_daily_loss_usd=75.0,
        max_loss_per_trade_usd=max_loss,
        max_trades_per_day=6,
        max_position_notional_usd=max_notional,
        max_concurrent_positions=1,
        consecutive_loss_limit=3,
        spread_max_bps=20.0,
        circuit_breaker=CircuitBreakerConfig(),
    )
    return RiskManager(cfg)


def compute_size(price, stop, max_notional=600.0, max_loss=20.0, mult=1.0):
    rm = make_risk(max_notional, max_loss)
    return rm.compute_position_size(price, stop, multiplier=mult)


# ---------------------------------------------------------------------------
# Basic sizing
# ---------------------------------------------------------------------------

def test_basic_sizing_notional_binding():
    """price=100, stop=99 → min(600/100=6, 20/1=20) = 6"""
    assert compute_size(100.0, 99.0) == 6


def test_basic_sizing_loss_binding():
    """price=50, stop=49 → min(600/50=12, 20/1=20) = 12"""
    assert compute_size(50.0, 49.0) == 12


def test_stop_wider_loss_binds():
    """price=100, stop=98 → min(6, 20/2=10) = 6 — notional still binds"""
    assert compute_size(100.0, 98.0) == 6


def test_small_stop_distance():
    """price=100, stop=99.50 → min(6, 20/0.50=40) = 6"""
    assert compute_size(100.0, 99.50) == 6


def test_large_stop_distance_loss_binds():
    """price=20, stop=15 → min(600/20=30, 20/5=4) = 4"""
    assert compute_size(20.0, 15.0) == 4


def test_high_price_notional_binds():
    """price=400, stop=395 → min(600/400=1.5→1, 20/5=4) = 1"""
    assert compute_size(400.0, 395.0) == 1


def test_very_high_price_notional_binds():
    """price=700, stop=693 → min(600/700≈0.857→0, ...) = 0 → reject"""
    assert compute_size(700.0, 693.0) == 0


def test_reject_zero_price():
    assert compute_size(0.0, 0.0) == 0


def test_reject_equal_prices():
    """stop == price → stop_dist = 0 → reject"""
    assert compute_size(100.0, 100.0) == 0


def test_reject_stop_above_entry_for_long():
    """stop > entry (bad for long, but sizing should still return > 0 based on abs distance)"""
    # abs(100 - 101) = 1  →  min(6, 20) = 6
    assert compute_size(100.0, 101.0) == 6


# ---------------------------------------------------------------------------
# Multiplier
# ---------------------------------------------------------------------------

def test_multiplier_reduces_size():
    """Full size = 6, half multiplier → 3"""
    assert compute_size(100.0, 99.0, mult=0.5) == 3


def test_multiplier_quarter():
    """Full size = 6, 0.25x → 1"""
    assert compute_size(100.0, 99.0, mult=0.25) == 1


def test_multiplier_zero_returns_zero():
    """0 multiplier → 0 shares"""
    assert compute_size(100.0, 99.0, mult=0.0) == 0


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_exact_notional_boundary():
    """price=600, stop=599, notional=600 → min(1.0, 20) = 1"""
    assert compute_size(600.0, 599.0) == 1


def test_small_price_high_loss_cap():
    """price=5, stop=4 → min(600/5=120, 20/1=20) = 20"""
    assert compute_size(5.0, 4.0) == 20


def test_floor_truncation():
    """price=200, stop=199 → min(600/200=3.0, 20/1=20) = 3"""
    assert compute_size(200.0, 199.0) == 3


def test_fractional_shares_floored():
    """price=150, stop=149 → min(4.0, 20) = 4"""
    assert compute_size(150.0, 149.0) == 4
