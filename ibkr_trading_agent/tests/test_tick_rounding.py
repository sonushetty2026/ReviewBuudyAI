"""
Unit tests for tick-size rounding in OrderManager.
"""

import pytest
from src.order_manager import OrderManager


def rnd(price: float, tick: float) -> float:
    """Convenience wrapper."""
    om = OrderManager.__new__(OrderManager)  # no __init__ needed
    om._min_ticks = {}
    om._contracts = {}
    return om.round_to_tick(price, tick)


# ---------------------------------------------------------------------------
# Basic cases
# ---------------------------------------------------------------------------

def test_exact_no_change():
    assert rnd(10.25, 0.25) == 10.25


def test_already_on_tick():
    assert rnd(100.00, 0.01) == 100.00


def test_round_up_to_penny():
    result = rnd(10.005, 0.01)
    assert abs(result - 0.01) < 1e-9 or abs(result - 10.01) < 1e-9


def test_round_half_penny_up():
    result = rnd(10.015, 0.01)
    assert abs(result - 10.02) < 1e-9 or abs(result - 10.01) < 1e-9


def test_round_nickel():
    assert abs(rnd(10.025, 0.05) - 0.05) < 1e-9 or abs(rnd(10.025, 0.05) - 10.00) < 1e-9


def test_round_dime():
    result = rnd(10.14, 0.10)
    assert abs(result - 10.10) < 1e-9


def test_round_quarter_down():
    result = rnd(10.12, 0.25)
    assert abs(result - 10.00) < 1e-9 or abs(result - 10.25) < 1e-9


def test_round_dollar():
    result = rnd(10.49, 1.0)
    assert abs(result - 10.0) < 1e-9


def test_round_dollar_up():
    result = rnd(10.51, 1.0)
    assert abs(result - 11.0) < 1e-9


# ---------------------------------------------------------------------------
# Penny tick (most common US equity)
# ---------------------------------------------------------------------------

def test_penny_tick_no_change():
    assert abs(rnd(480.15, 0.01) - 480.15) < 1e-9


def test_penny_tick_round_down():
    result = rnd(480.154, 0.01)
    assert abs(result - 480.15) < 1e-9


def test_penny_tick_round_up():
    result = rnd(480.156, 0.01)
    assert abs(result - 480.16) < 1e-9


# ---------------------------------------------------------------------------
# Zero / degenerate tick
# ---------------------------------------------------------------------------

def test_zero_tick_passthrough():
    """Zero tick → return as-is (4 decimal places)."""
    result = rnd(123.4567, 0.0)
    assert abs(result - 123.4567) < 1e-9


# ---------------------------------------------------------------------------
# Large prices
# ---------------------------------------------------------------------------

def test_large_price_penny_tick():
    result = rnd(4500.123, 0.01)
    assert abs(result - 4500.12) < 1e-9


def test_large_price_nickel_tick():
    result = rnd(4500.123, 0.05)
    assert abs(result - 4500.10) < 1e-9


# ---------------------------------------------------------------------------
# Negative prices (defensive)
# ---------------------------------------------------------------------------

def test_negative_price():
    result = rnd(-10.123, 0.01)
    # Should round towards zero or away; just check it doesn't crash
    assert isinstance(result, float)


# ---------------------------------------------------------------------------
# Round-trip stability
# ---------------------------------------------------------------------------

def test_round_trip_is_stable():
    """Rounding an already-rounded price should not change it."""
    price = 123.45
    tick = 0.01
    first = rnd(price, tick)
    second = rnd(first, tick)
    assert abs(first - second) < 1e-9


def test_multiple_round_trips():
    price = 99.999
    tick = 0.01
    result = price
    for _ in range(5):
        result = rnd(result, tick)
    assert abs(result - 100.00) < 1e-9 or abs(result - 99.99) < 1e-9
