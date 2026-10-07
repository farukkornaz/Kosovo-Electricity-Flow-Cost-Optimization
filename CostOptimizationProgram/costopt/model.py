"""Network model: countries/zones as nodes, cross-border lines as arcs.

The model only describes the problem. It knows nothing about OR-Tools; the
solver translates it (super source, curve segments, integer scaling).

- Node:       a zone that power can pass through.
- SupplyNode: a zone we can buy from, up to `max_supply` MW at a fixed `unit_price`
  (negative when the spot price is, e.g. a midday solar surplus).
              It can also pass through power bought elsewhere.
- DemandNode: the single zone whose `demand` MW must be delivered.
- Arc:        a one-directional line; its auction price curve also sets its capacity.
              Capacity 0 (ATC 0) means the line is closed: kept in the data, never used.
              A two-way interconnector is modeled as two arcs.
"""
from dataclasses import dataclass

from costopt.price_curve import PriceCurve


class ModelValidationError(ValueError):
    """Raised when the model is inconsistent. `errors` lists every problem found."""

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("Invalid network model:\n  - " + "\n  - ".join(errors))


@dataclass(frozen=True)
class Node:
    id: str
    name: str
    lat: float
    lon: float


@dataclass(frozen=True)
class SupplyNode(Node):
    max_supply: int     # MW
    unit_price: float   # €/MWh, may be negative

    def __post_init__(self):
        if self.max_supply <= 0:
            raise ValueError(f"{self.id}: max_supply must be positive")


@dataclass(frozen=True)
class DemandNode(Node):
    demand: int         # MW

    def __post_init__(self):
        if self.demand <= 0:
            raise ValueError(f"{self.id}: demand must be positive")


@dataclass(frozen=True)
class Arc:
    from_node: str
    to_node: str
    curve: PriceCurve

    @property
    def id(self) -> str:
        return f"{self.from_node}->{self.to_node}"

    @property
    def capacity(self) -> int:
        return self.curve.capacity

    @property
    def is_closed(self) -> bool:
        return self.capacity == 0


class NetworkModel:
    def __init__(self, name: str = "network"):
        self.name = name
        self._nodes: dict[str, Node] = {}
        self._arcs: dict[str, Arc] = {}

    # --- building -----------------------------------------------------------

    def add_node(self, node: Node) -> Node:
        if node.id in self._nodes:
            raise ValueError(f"Duplicate node id: {node.id}")
        self._nodes[node.id] = node
        return node

    def add_arc(self, arc: Arc) -> Arc:
        for end in (arc.from_node, arc.to_node):
            if end not in self._nodes:
                raise ValueError(f"Arc {arc.id}: unknown node {end}")
        if arc.from_node == arc.to_node:
            raise ValueError(f"Arc {arc.id}: self-loop")
        if arc.id in self._arcs:
            raise ValueError(f"Duplicate arc: {arc.id}")
        self._arcs[arc.id] = arc
        return arc

    def validate(self) -> None:
        """Whole-model checks that can only run once building is finished."""
        errors = []
        demand_nodes = [n for n in self._nodes.values() if isinstance(n, DemandNode)]
        if len(demand_nodes) != 1:
            errors.append(f"Exactly one demand node required, found {len(demand_nodes)}")
        if not self.supply_nodes:
            errors.append("At least one supply node required")
        for node in self.supply_nodes:
            if not self.arcs_from(node.id):
                errors.append(f"Supply node {node.id} has no outgoing arc")
        for node in demand_nodes:
            if not self.arcs_to(node.id):
                errors.append(f"Demand node {node.id} has no incoming arc")
        if errors:
            raise ModelValidationError(errors)

    # --- queries ------------------------------------------------------------

    @property
    def nodes(self) -> list[Node]:
        return list(self._nodes.values())

    @property
    def arcs(self) -> list[Arc]:
        return list(self._arcs.values())

    def node(self, node_id: str) -> Node:
        return self._nodes[node_id]

    def arc(self, arc_id: str) -> Arc:
        return self._arcs[arc_id]

    @property
    def supply_nodes(self) -> list[SupplyNode]:
        return [n for n in self._nodes.values() if isinstance(n, SupplyNode)]

    @property
    def demand_node(self) -> DemandNode:
        demand_nodes = [n for n in self._nodes.values() if isinstance(n, DemandNode)]
        if len(demand_nodes) != 1:
            raise ModelValidationError([f"Exactly one demand node required, found {len(demand_nodes)}"])
        return demand_nodes[0]

    def arcs_from(self, node_id: str) -> list[Arc]:
        return [a for a in self._arcs.values() if a.from_node == node_id]

    def arcs_to(self, node_id: str) -> list[Arc]:
        return [a for a in self._arcs.values() if a.to_node == node_id]

    def summary(self) -> str:
        lines = [f"NetworkModel '{self.name}': {len(self._nodes)} nodes, {len(self._arcs)} arcs"]
        for node in self._nodes.values():
            if isinstance(node, SupplyNode):
                lines.append(f"  [supply] {node.id:4} {node.name:12} max {node.max_supply} MW @ {node.unit_price} €/MWh")
            elif isinstance(node, DemandNode):
                lines.append(f"  [demand] {node.id:4} {node.name:12} {node.demand} MW")
            else:
                lines.append(f"  [node]   {node.id:4} {node.name}")
        for arc in self._arcs.values():
            curve = arc.curve
            if arc.is_closed:
                lines.append(f"  {arc.id:8} closed (ATC 0)")
                continue
            lines.append(
                f"  {arc.id:8} cap {arc.capacity:5} MW, "
                f"price {curve.clearing_price(0):.2f} -> {curve.clearing_price(arc.capacity):.2f} €/MWh"
            )
        return "\n".join(lines)
