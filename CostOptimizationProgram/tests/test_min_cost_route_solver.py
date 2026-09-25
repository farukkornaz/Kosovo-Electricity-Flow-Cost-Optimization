from pathlib import Path

import pytest

from costopt.data_loader import load_model
from costopt.min_cost_route_solver import MinCostRouteSolver
from costopt.model import Arc, DemandNode, NetworkModel, Node, SupplyNode
from costopt.price_curve import LinearPriceCurve
from costopt.solution import SolveStatus, decompose_paths

SAMPLE = Path(__file__).parent.parent / "data" / "sample_network.json"


def flat(price, capacity):
    return LinearPriceCurve(base_price=price, slope=0, capacity=capacity)


def test_cheapest_supplier_first():
    # A: 50 + 10 transport = 60, B: 60 + 10 = 70 -> A fully, rest from B.
    model = NetworkModel()
    model.add_node(SupplyNode("A", "A", 0, 0, max_supply=100, unit_price=50))
    model.add_node(SupplyNode("B", "B", 0, 1, max_supply=100, unit_price=60))
    model.add_node(DemandNode("D", "D", 1, 0, demand=150))
    model.add_arc(Arc("A", "D", flat(10, 200)))
    model.add_arc(Arc("B", "D", flat(10, 200)))

    result = MinCostRouteSolver().solve(model)
    assert result.status is SolveStatus.OPTIMAL
    assert result.supply("A").quantity == 100
    assert result.supply("B").quantity == 50
    assert result.total_cost == pytest.approx(100 * 60 + 50 * 70)
    assert result.objective == pytest.approx(result.total_cost)


def test_pay_as_clear_splits_over_parallel_routes():
    # One route: 100 MW * P(100) = 100 * 20 = 2000 €.
    # Two identical routes, 50 MW each: 2 * 50 * P(50) = 2 * 50 * 15 = 1500 €.
    model = NetworkModel()
    model.add_node(SupplyNode("S", "S", 0, 0, max_supply=1000, unit_price=0))
    model.add_node(Node("X", "X", 1, 0))
    model.add_node(Node("Y", "Y", -1, 0))
    model.add_node(DemandNode("D", "D", 0, 1, demand=100))
    for mid in ("X", "Y"):
        model.add_arc(Arc("S", mid, LinearPriceCurve(base_price=10, slope=0.1, capacity=100)))
        model.add_arc(Arc(mid, "D", flat(0, 1000)))

    result = MinCostRouteSolver(num_segments=10).solve(model)
    assert result.arc("S->X").flow == 50
    assert result.arc("S->Y").flow == 50
    assert result.arc("S->X").clearing_price == pytest.approx(15)
    assert result.transport_cost == pytest.approx(1500)


def test_infeasible_delivers_max():
    model = NetworkModel()
    model.add_node(SupplyNode("A", "A", 0, 0, max_supply=500, unit_price=50))
    model.add_node(DemandNode("D", "D", 1, 0, demand=300))
    model.add_arc(Arc("A", "D", flat(10, 120)))

    result = MinCostRouteSolver().solve(model)
    assert result.status is SolveStatus.INFEASIBLE
    assert result.delivered == 120
    assert result.supply("A").quantity == 120


def test_sample_network_consistency():
    model = load_model(SAMPLE)
    result = MinCostRouteSolver().solve(model)
    assert result.status is SolveStatus.OPTIMAL
    assert result.delivered == model.demand_node.demand

    for s in result.supplies:
        assert 0 <= s.quantity <= s.max_supply
    for a in result.arcs:
        assert 0 <= a.flow <= a.capacity
        assert sum(a.segment_flows) == a.flow

    # flow conservation at every node except the demand node
    for node in model.nodes:
        if node.id == result.demand_node:
            continue
        bought = result.supply(node.id).quantity if isinstance(node, SupplyNode) else 0
        inflow = sum(result.arc(a.id).flow for a in model.arcs_to(node.id))
        outflow = sum(result.arc(a.id).flow for a in model.arcs_from(node.id))
        assert bought + inflow == outflow, node.id

    # paths start at a supply node, end at the demand node, and add up exactly
    assert sum(p.flow for p in result.paths) == result.delivered
    assert sum(p.total_cost for p in result.paths) == pytest.approx(result.total_cost)
    for p in result.paths:
        assert isinstance(model.node(p.nodes[0]), SupplyNode)
        assert p.nodes[-1] == result.demand_node

    # segment interpolation lies above the convex curve, and close to it
    assert result.objective >= result.total_cost - 1e-6
    assert result.objective == pytest.approx(result.total_cost, rel=1e-3)


def test_more_segments_never_worse():
    model = load_model(SAMPLE)
    coarse = MinCostRouteSolver(num_segments=2).solve(model)
    fine = MinCostRouteSolver(num_segments=50).solve(model)
    assert fine.total_cost <= coarse.total_cost + 1e-6


def test_decompose_paths_cancels_zero_cost_cycle():
    model = NetworkModel()
    model.add_node(SupplyNode("S", "S", 0, 0, max_supply=10, unit_price=1))
    model.add_node(Node("A", "A", 0, 1))
    model.add_node(Node("B", "B", 0, 2))
    model.add_node(DemandNode("D", "D", 0, 3, demand=10))
    for a, b in (("S", "A"), ("A", "B"), ("B", "A"), ("B", "D")):
        model.add_arc(Arc(a, b, flat(0, 100)))
    # 10 MW S->A->B->D, plus a 5 MW A<->B cycle
    flows = {"S->A": 10, "A->B": 15, "B->A": 5, "B->D": 10}
    assert decompose_paths(model, {"S": 10}, flows) == [(("S", "A", "B", "D"), 10)]
