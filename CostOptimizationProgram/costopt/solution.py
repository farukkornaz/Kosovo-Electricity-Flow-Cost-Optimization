"""Solver-independent result of a min cost route problem.

All costs are true pay-as-clear costs computed from the final flows:
    arc cost    = flow * P(flow)
    supply cost = quantity * unit_price
`objective` is what the solver minimized (piecewise-linear segment costs). It can
be slightly above `total_cost`, because the segments interpolate the curve linearly.

Path costs share each arc's cost pro rata: every MW on an arc pays that arc's
clearing price, so the path costs add up exactly to `total_cost`.
"""
from dataclasses import asdict, dataclass
from enum import Enum

from costopt.model import NetworkModel


class SolveStatus(Enum):
    OPTIMAL = "optimal"
    # Demand can't be fully met. Flows show the cheapest way to deliver as much as possible.
    INFEASIBLE = "infeasible"
    ERROR = "error"


@dataclass(frozen=True)
class SupplyResult:
    node_id: str
    quantity: int           # MW bought
    max_supply: int
    unit_price: float       # €/MWh
    cost: float             # €


@dataclass(frozen=True)
class ArcResult:
    arc_id: str
    from_node: str
    to_node: str
    flow: int               # MW
    capacity: int
    clearing_price: float   # P(flow), €/MWh
    cost: float             # flow * P(flow), €
    segment_flows: tuple[int, ...]

    @property
    def utilization(self) -> float:
        return self.flow / self.capacity if self.capacity else 0.0


@dataclass(frozen=True)
class RoutePath:
    nodes: tuple[str, ...]  # supply node ... demand node
    flow: int               # MW
    supply_cost: float      # €
    transport_cost: float   # €

    @property
    def total_cost(self) -> float:
        return self.supply_cost + self.transport_cost

    @property
    def unit_cost(self) -> float:
        """€/MWh delivered on this path."""
        return self.total_cost / self.flow

    @property
    def label(self) -> str:
        return "→".join(self.nodes)


@dataclass(frozen=True)
class SolutionResult:
    status: SolveStatus
    message: str
    demand_node: str
    demand: int
    delivered: int
    supplies: tuple[SupplyResult, ...]
    arcs: tuple[ArcResult, ...]
    paths: tuple[RoutePath, ...]
    objective: float        # € the solver minimized (segment approximation)
    num_segments: int

    @property
    def supply_cost(self) -> float:
        return sum(s.cost for s in self.supplies)

    @property
    def transport_cost(self) -> float:
        return sum(a.cost for a in self.arcs)

    @property
    def total_cost(self) -> float:
        return self.supply_cost + self.transport_cost

    @property
    def unit_cost(self) -> float:
        """Average €/MWh delivered."""
        return self.total_cost / self.delivered if self.delivered else 0.0

    def supply(self, node_id: str) -> SupplyResult:
        return next(s for s in self.supplies if s.node_id == node_id)

    def arc(self, arc_id: str) -> ArcResult:
        return next(a for a in self.arcs if a.arc_id == arc_id)

    def to_dict(self) -> dict:
        data = asdict(self)
        data["status"] = self.status.value
        data["supply_cost"] = self.supply_cost
        data["transport_cost"] = self.transport_cost
        data["total_cost"] = self.total_cost
        data["unit_cost"] = self.unit_cost
        return data

    def summary(self) -> str:
        lines = [
            f"Status: {self.status.value} — {self.message}",
            f"Delivered to {self.demand_node}: {self.delivered} / {self.demand} MW",
        ]
        if self.status is SolveStatus.ERROR:
            return "\n".join(lines)
        lines += [
            f"Total cost:     {self.total_cost:12,.2f} €  ({self.unit_cost:.2f} €/MWh)",
            f"  Supply:       {self.supply_cost:12,.2f} €",
            f"  Transport:    {self.transport_cost:12,.2f} €",
            f"Solver objective (segment approx., {self.num_segments} segments): {self.objective:,.2f} €",
            "",
            "Supply      Bought /  Max   Price      Cost",
        ]
        for s in self.supplies:
            lines.append(
                f"  {s.node_id:6} {s.quantity:7} / {s.max_supply:4}  {s.unit_price:6.2f}  {s.cost:10,.2f}"
            )
        lines += ["", "Arc         Flow /  Cap   Use  Clearing P     Cost"]
        for a in self.arcs:
            if a.capacity == 0:
                lines.append(f"  {a.arc_id:8} closed (ATC 0)")
                continue
            lines.append(
                f"  {a.arc_id:8} {a.flow:5} / {a.capacity:4}  {a.utilization:4.0%}  "
                f"{a.clearing_price:10.2f}  {a.cost:9,.2f}"
            )
        lines += ["", "Paths"]
        for p in self.paths:
            lines.append(
                f"  {p.label:14} {p.flow:5} MW  supply {p.supply_cost:10,.2f} €  "
                f"transport {p.transport_cost:9,.2f} €  = {p.total_cost:10,.2f} € ({p.unit_cost:.2f} €/MWh)"
            )
        return "\n".join(lines)


def decompose_paths(
    model: NetworkModel, supply_flows: dict[str, int], arc_flows: dict[str, int]
) -> list[tuple[tuple[str, ...], int]]:
    """Split arc flows into supply→demand paths, as (nodes, MW) pairs.

    Walks from each supply node along arcs with remaining flow until the demand node.
    A flow cycle (only possible with zero-cost arcs) is cancelled when found; it carries
    nothing to the demand node.
    """
    sink = model.demand_node.id
    remaining = {arc_id: flow for arc_id, flow in arc_flows.items() if flow > 0}
    paths = []
    for source, quantity in supply_flows.items():
        left = quantity
        while left > 0:
            nodes, arcs = [source], []
            while nodes[-1] != sink:
                arc = next((a for a in model.arcs_from(nodes[-1]) if remaining.get(a.id, 0) > 0), None)
                if arc is None:
                    raise RuntimeError(f"Flow conservation broken at {nodes[-1]}")
                if arc.to_node in nodes:
                    start = nodes.index(arc.to_node)
                    cycle = arcs[start:] + [arc]
                    amount = min(remaining[a.id] for a in cycle)
                    for a in cycle:
                        remaining[a.id] -= amount
                    del nodes[start + 1:], arcs[start:]
                    continue
                nodes.append(arc.to_node)
                arcs.append(arc)
            amount = min([left] + [remaining[a.id] for a in arcs])
            for a in arcs:
                remaining[a.id] -= amount
            left -= amount
            paths.append((tuple(nodes), amount))
    return sorted(paths, key=lambda p: -p[1])


def build_solution(
    model: NetworkModel,
    status: SolveStatus,
    message: str,
    supply_flows: dict[str, int],
    segment_flows: dict[str, tuple[int, ...]],
    objective: float,
    num_segments: int,
) -> SolutionResult:
    """Turn raw solver flows into a SolutionResult with true costs and paths."""
    supplies = tuple(
        # + 0.0 turns the -0.0 of an unused negative-price supplier into 0.0
        SupplyResult(n.id, supply_flows[n.id], n.max_supply, n.unit_price, supply_flows[n.id] * n.unit_price + 0.0)
        for n in model.supply_nodes
    )
    arcs = []
    for arc in model.arcs:
        flow = sum(segment_flows[arc.id])
        price = arc.curve.clearing_price(flow)
        arcs.append(ArcResult(
            arc.id, arc.from_node, arc.to_node, flow, arc.capacity, price, flow * price,
            tuple(segment_flows[arc.id]),
        ))
    price_on = {a.arc_id: a.clearing_price for a in arcs}

    paths = []
    for nodes, flow in decompose_paths(model, supply_flows, {a.arc_id: a.flow for a in arcs}):
        arc_ids = [f"{a}->{b}" for a, b in zip(nodes[:-1], nodes[1:])]
        paths.append(RoutePath(
            nodes, flow,
            supply_cost=flow * model.node(nodes[0]).unit_price,
            transport_cost=sum(flow * price_on[arc_id] for arc_id in arc_ids),
        ))

    demand_node = model.demand_node
    return SolutionResult(
        status, message, demand_node.id, demand_node.demand, sum(supply_flows.values()),
        supplies, tuple(arcs), tuple(paths), objective, num_segments,
    )


def error_solution(model: NetworkModel, message: str, num_segments: int) -> SolutionResult:
    demand_node = model.demand_node
    return SolutionResult(
        SolveStatus.ERROR, message, demand_node.id, demand_node.demand, 0,
        (), (), (), 0.0, num_segments,
    )
