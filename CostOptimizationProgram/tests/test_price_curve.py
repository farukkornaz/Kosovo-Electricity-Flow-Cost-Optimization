import numpy as np
import pytest

from costopt.price_curve import CostSegment, LinearPriceCurve


def test_pay_as_clear_total_cost():
    curve = LinearPriceCurve(base_price=40, slope=0.1, capacity=300)
    assert curve.clearing_price(100) == pytest.approx(50)
    assert curve.total_cost(100) == pytest.approx(5000)
    assert curve.marginal_cost(100) == pytest.approx(60)


def test_segments_hand_calculated():
    curve = LinearPriceCurve(base_price=40, slope=0.1, capacity=300)
    segments = curve.segments(3)
    assert [s.capacity for s in segments] == [100, 100, 100]
    assert [s.unit_cost for s in segments] == pytest.approx([50, 70, 90])


def test_segments_exact_at_breakpoints_and_increasing():
    curve = LinearPriceCurve(base_price=12.5, slope=0.07, capacity=457)
    segments = curve.segments(7)
    assert sum(s.capacity for s in segments) == 457
    costs = [s.unit_cost for s in segments]
    assert costs == sorted(costs)

    cumulative_q = np.cumsum([s.capacity for s in segments])
    cumulative_cost = np.cumsum([s.capacity * s.unit_cost for s in segments])
    for q, cost in zip(cumulative_q, cumulative_cost):
        assert cost == pytest.approx(curve.total_cost(q))


def test_zero_slope_is_flat_price():
    curve = LinearPriceCurve(base_price=20, slope=0, capacity=100)
    assert curve.segments(4) == [CostSegment(25, 20.0)] * 4


def test_more_segments_than_capacity():
    curve = LinearPriceCurve(base_price=10, slope=1, capacity=3)
    assert [s.capacity for s in curve.segments(10)] == [1, 1, 1]


def test_zero_capacity_is_closed_line():
    curve = LinearPriceCurve(base_price=10, slope=0.1, capacity=0)
    assert curve.segments(10) == []


@pytest.mark.parametrize("kwargs", [
    dict(base_price=10, slope=0.1, capacity=-1),
    dict(base_price=-1, slope=0.1, capacity=100),
    dict(base_price=10, slope=-0.1, capacity=100),
])
def test_invalid_curves(kwargs):
    with pytest.raises(ValueError):
        LinearPriceCurve(**kwargs)


def test_synthetic_is_reproducible():
    a = LinearPriceCurve.synthetic(np.random.default_rng(42), capacity=500)
    b = LinearPriceCurve.synthetic(np.random.default_rng(42), capacity=500)
    assert a == b
    assert a.slope > 0
