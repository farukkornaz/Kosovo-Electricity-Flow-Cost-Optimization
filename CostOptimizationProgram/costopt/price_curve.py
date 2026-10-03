"""Arc price curves for cross-border capacity auctions.

Auction rule: pay-as-clear (JAO-style). The clearing price P(q) depends on the
quantity q we buy, and that single price applies to the whole quantity:

    total_cost(q) = q * P(q)

Because every extra MW also raises the price of the MWs already bought, the
marginal cost is above the clearing price. The solver works with marginal cost,
so a curve is handed to it as consecutive segments of increasing unit cost.
Segment unit costs are the average marginal cost over the segment, so the
piecewise-linear total cost is exact at every segment boundary.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class CostSegment:
    """One piece of a curve: `capacity` MW at `unit_cost` €/MWh."""

    capacity: int
    unit_cost: float


class PriceCurve(ABC):
    """Clearing price as a function of the quantity we buy on an arc."""

    capacity: int

    @abstractmethod
    def clearing_price(self, quantity: float) -> float:
        """Clearing price (€/MWh) when we buy `quantity` MW."""

    def total_cost(self, quantity: float) -> float:
        """Pay-as-clear cost: the clearing price is paid on every MW."""
        return quantity * self.clearing_price(quantity)

    def breakpoints(self, num_segments: int) -> np.ndarray:
        """Integer MW boundaries splitting [0, capacity] into near-equal segments."""
        if num_segments < 1:
            raise ValueError("num_segments must be >= 1")
        if self.capacity == 0:
            return np.array([0])
        num_segments = min(num_segments, self.capacity)
        return np.unique(np.round(np.linspace(0, self.capacity, num_segments + 1)).astype(int))

    def segments(self, num_segments: int = 10) -> list[CostSegment]:
        """Split the curve into segments with increasing marginal unit cost (none if closed)."""
        points = self.breakpoints(num_segments)
        segments = []
        for start, end in zip(points[:-1], points[1:]):
            width = int(end - start)
            unit_cost = (self.total_cost(end) - self.total_cost(start)) / width
            segments.append(CostSegment(width, unit_cost))
        return segments


@dataclass(frozen=True)
class LinearPriceCurve(PriceCurve):
    """P(q) = base_price + slope * q, for 0 <= q <= capacity.

    base_price: clearing price that would form without our bid (€/MWh).
    slope:      price increase per MW we buy (€/MWh per MW).
    capacity:   auctioned line capacity / ATC (MW). 0 means the line is closed.
    """

    base_price: float
    slope: float
    capacity: int

    def __post_init__(self):
        if self.capacity < 0:
            raise ValueError("capacity must be non-negative (0 = closed line)")
        if self.base_price < 0:
            raise ValueError("base_price must be non-negative")
        if self.slope < 0:
            raise ValueError("slope must be non-negative (price can't fall as we buy more)")

    def clearing_price(self, quantity: float) -> float:
        return self.base_price + self.slope * quantity

    def marginal_cost(self, quantity: float) -> float:
        """d/dq [q * P(q)] = base_price + 2 * slope * q."""
        return self.base_price + 2 * self.slope * quantity

    @classmethod
    def synthetic(
        cls,
        rng: np.random.Generator,
        capacity: int,
        base_price_range: tuple[float, float] = (5.0, 30.0),
        max_price_increase: tuple[float, float] = (5.0, 40.0),
    ) -> "LinearPriceCurve":
        """Random curve for testing: price rises by `max_price_increase` over the full capacity."""
        base_price = rng.uniform(*base_price_range)
        slope = rng.uniform(*max_price_increase) / capacity if capacity else 0.0
        return cls(round(base_price, 2), slope, capacity)
