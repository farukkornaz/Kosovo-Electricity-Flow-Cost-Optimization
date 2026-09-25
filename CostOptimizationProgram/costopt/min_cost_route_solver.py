"""Cheapest way to deliver the demand, with OR-Tools SimpleMinCostFlow.

Translation of the NetworkModel (see examples/Flows/minimum-cost-flow-2.py for the core idea):
- A virtual super source supplies exactly the demand.
- super source -> each supply node: capacity = max_supply, unit cost = unit_price.
- Each arc becomes parallel sub-arcs, one per price curve segment, with increasing
  marginal unit costs. The solver fills cheaper segments first, which reproduces the
  pay-as-clear cost q * P(q) at segment boundaries.
- OR-Tools needs integer costs, so €/MWh are scaled by `cost_scale` (100 = cents).

CLI:
    python -m costopt.min_cost_route_solver data/sample_network.json [--segments 10] [--json out.json]
"""
import argparse
import json

from ortools.graph.python import min_cost_flow

from costopt.data_loader import load_model
from costopt.model import NetworkModel
from costopt.solution import SolutionResult, SolveStatus, build_solution, error_solution


class MinCostRouteSolver:
    def __init__(self, num_segments: int = 10, cost_scale: int = 100):
        self.num_segments = num_segments
        self.cost_scale = cost_scale

    def _scaled(self, cost: float) -> int:
        return round(cost * self.cost_scale)

    def solve(self, model: NetworkModel) -> SolutionResult:
        model.validate()
        index = {node.id: i for i, node in enumerate(model.nodes)}
        super_source = len(index)
        smcf = min_cost_flow.SimpleMinCostFlow()

        supply_arcs = {
            node.id: smcf.add_arc_with_capacity_and_unit_cost(
                super_source, index[node.id], node.max_supply, self._scaled(node.unit_price)
            )
            for node in model.supply_nodes
        }
        segment_arcs = {
            arc.id: [
                smcf.add_arc_with_capacity_and_unit_cost(
                    index[arc.from_node], index[arc.to_node], segment.capacity, self._scaled(segment.unit_cost)
                )
                for segment in arc.curve.segments(self.num_segments)
            ]
            for arc in model.arcs
        }

        demand_node = model.demand_node
        smcf.set_node_supply(super_source, demand_node.demand)
        smcf.set_node_supply(index[demand_node.id], -demand_node.demand)

        status = smcf.solve()
        if status == smcf.OPTIMAL:
            result_status, message = SolveStatus.OPTIMAL, "demand fully met"
        elif status == smcf.INFEASIBLE:
            # Demand can't be met; find the cheapest way to deliver as much as possible.
            status = smcf.solve_max_flow_with_min_cost()
            if status != smcf.OPTIMAL:
                return error_solution(model, f"max flow fallback failed: {status.name}", self.num_segments)
            result_status = SolveStatus.INFEASIBLE
            message = f"demand can't be fully met, delivering max {smcf.maximum_flow()} MW"
        else:
            return error_solution(model, f"solver returned {status.name}", self.num_segments)

        return build_solution(
            model,
            result_status,
            message,
            supply_flows={node_id: int(smcf.flow(a)) for node_id, a in supply_arcs.items()},
            segment_flows={arc_id: tuple(int(smcf.flow(a)) for a in arcs) for arc_id, arcs in segment_arcs.items()},
            objective=smcf.optimal_cost() / self.cost_scale,
            num_segments=self.num_segments,
        )


def main():
    parser = argparse.ArgumentParser(description="Solve the min cost route problem for a network model.")
    parser.add_argument("model", help="model JSON file")
    parser.add_argument("--segments", type=int, default=10, help="price curve segments per arc")
    parser.add_argument("--json", help="also write the full result to this JSON file")
    args = parser.parse_args()

    result = MinCostRouteSolver(num_segments=args.segments).solve(load_model(args.model))
    print(result.summary())
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(result.to_dict(), f, indent=2, ensure_ascii=False)
        print(f"\nSaved {args.json}")


if __name__ == "__main__":
    main()
