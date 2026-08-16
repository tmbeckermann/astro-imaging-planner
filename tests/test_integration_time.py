import math

import pytest

from astroplanner.integration_time import (
    diminishing_returns_table,
    elbow_hours,
    marginal_gain_pct,
    snr_at_time,
)


def test_snr_grows_with_sqrt_time_for_fixed_sub_length():
    snr_1h = snr_at_time(0.01, 10.0, 1.0, 3600.0, 45.0)
    snr_4h = snr_at_time(0.01, 10.0, 1.0, 4 * 3600.0, 45.0)
    assert snr_4h / snr_1h == pytest.approx(2.0, rel=1e-9)


def test_snr_curve_shape_is_independent_of_brightness_and_gear():
    # marginal_gain_pct takes no target/sky/read-noise args at all: the ratio
    # SNR(T+dt)/SNR(T) cancels every term that isn't T itself, for any mix of
    # target, sky and read-noise electrons, as long as sub length is fixed.
    faint = snr_at_time(1e-4, 1.0, 2.5, 10 * 3600.0, 30.0)
    faint_next = snr_at_time(1e-4, 1.0, 2.5, 11 * 3600.0, 30.0)
    bright = snr_at_time(5.0, 40.0, 0.5, 10 * 3600.0, 30.0)
    bright_next = snr_at_time(5.0, 40.0, 0.5, 11 * 3600.0, 30.0)
    assert (faint_next / faint - 1) == pytest.approx(bright_next / bright - 1, rel=1e-9)
    assert (faint_next / faint - 1) == pytest.approx(marginal_gain_pct(10 * 3600.0) / 100, rel=1e-9)


def test_marginal_gain_matches_closed_form():
    gain = marginal_gain_pct(10 * 3600.0, step_s=3600.0)
    expected = (math.sqrt(11 / 10) - 1) * 100
    assert gain == pytest.approx(expected, rel=1e-9)


def test_marginal_gain_shrinks_over_time():
    early = marginal_gain_pct(3600.0)
    late = marginal_gain_pct(20 * 3600.0)
    assert early > late > 0


def test_elbow_hours_matches_closed_form():
    hours = elbow_hours(threshold_pct=5.0)
    k = 1.05**2 - 1.0
    assert hours == pytest.approx((3600.0 / k) / 3600.0, rel=1e-9)
    # Same 9.76 as exposure.py's "swamp factor ~9.8" — both come from the same
    # (1+E/100)^2 - 1 term, just applied to hours instead of read-noise ratio.
    assert hours == pytest.approx(9.76, rel=1e-3)


def test_elbow_hours_grows_as_threshold_shrinks():
    loose = elbow_hours(threshold_pct=10.0)
    strict = elbow_hours(threshold_pct=2.0)
    assert loose < strict


def test_elbow_hours_caps_at_max_hours():
    assert elbow_hours(threshold_pct=0.01, max_hours=48.0) == 48.0


def test_diminishing_returns_table_snr_differs_by_target_brightness():
    faint = diminishing_returns_table(1e-4, 5.0, 1.0, 45.0, hours=(4,))[0]
    bright = diminishing_returns_table(2.0, 5.0, 1.0, 45.0, hours=(4,))[0]
    assert bright.snr > faint.snr


def test_diminishing_returns_table_gain_column_is_target_independent():
    faint = diminishing_returns_table(1e-4, 5.0, 1.0, 45.0)
    bright = diminishing_returns_table(2.0, 5.0, 1.0, 45.0)
    for a, b in zip(faint, bright):
        assert a.next_hour_gain_pct == pytest.approx(b.next_hour_gain_pct, rel=1e-9)


def test_diminishing_returns_table_is_monotonic():
    rows = diminishing_returns_table(0.02, 5.0, 1.0, 45.0)
    snrs = [r.snr for r in rows]
    gains = [r.next_hour_gain_pct for r in rows]
    assert snrs == sorted(snrs)
    assert gains == sorted(gains, reverse=True)


def test_snr_zero_at_zero_time():
    assert snr_at_time(0.05, 5.0, 1.0, 0.0, 45.0) == 0.0
