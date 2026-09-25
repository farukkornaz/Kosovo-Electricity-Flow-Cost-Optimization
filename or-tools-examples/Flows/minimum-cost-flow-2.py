"""Min cost flow with a single demand node and priced, capacity-limited suppliers.

Only the demand amount is known. How much each supply node provides is decided
by the solver. Supply nodes have a unit supply cost, and arcs have a unit
transport cost.

A virtual "super source" node is added. It has an arc to every supply node, with
capacity = that node's max supply and unit cost = that node's unit supply cost.
The super source supplies exactly the demand, so the flow on each
super source -> supplier arc is how much that supplier provides.
"""
import numpy as np

from ortools.graph.python import min_cost_flow


def main():
    smcf = min_cost_flow.SimpleMinCostFlow()

    # Real network (same graph as minimum-cost-flow.py).
    start_nodes = np.array([0, 0, 1, 1, 1, 2, 2, 3, 4])
    end_nodes = np.array([1, 2, 2, 3, 4, 3, 4, 4, 2])
    capacities = np.array([15, 8, 20, 4, 10, 15, 4, 20, 5])
    unit_costs = np.array([4, 4, 2, 2, 6, 1, 3, 2, 3])
    num_nodes = 5

    # Single demand node and its required amount.
    demand_node = 4
    demand = 20

    # Candidate supply nodes: max supply amount and unit supply cost.
    supply_nodes = np.array([0, 1, 2])
    max_supplies = np.array([15, 10, 8])
    supply_unit_costs = np.array([1, 5, 3])

    # Super source node and its arcs to the supply nodes.
    super_source = num_nodes
    source_arcs = smcf.add_arcs_with_capacity_and_unit_cost(
        np.full(len(supply_nodes), super_source),
        supply_nodes,
        max_supplies,
        supply_unit_costs,
    )
    network_arcs = smcf.add_arcs_with_capacity_and_unit_cost(
        start_nodes, end_nodes, capacities, unit_costs
    )

    # Only the super source and the demand node have non-zero supply.
    smcf.set_node_supply(super_source, demand)
    smcf.set_node_supply(demand_node, -demand)

    status = smcf.solve()

    if status != smcf.OPTIMAL:
        # INFEASIBLE: demand can't be met with the given supply/arc capacities.
        print("There was an issue with the min cost flow input.")
        print(f"Status: {status}")
        exit(1)

    source_flows = smcf.flows(source_arcs)
    network_flows = smcf.flows(network_arcs)
    supply_cost = int(np.sum(source_flows * supply_unit_costs))
    transport_cost = int(np.sum(network_flows * unit_costs))

    print(f"Minimum total cost: {smcf.optimal_cost()}")
    print(f"  Supply cost:      {supply_cost}")
    print(f"  Transport cost:   {transport_cost}")
    print("")
    print("Node  Supplied / Max  Unit cost  Cost")
    for node, flow, cap, cost in zip(
        supply_nodes, source_flows, max_supplies, supply_unit_costs
    ):
        print(f"{node:4}  {flow:8} / {cap:3}  {cost:9}  {flow * cost:4}")
    print("")
    print(" Arc    Flow / Capacity Cost")
    for arc, flow, cost in zip(network_arcs, network_flows, network_flows * unit_costs):
        print(
            f"{smcf.tail(arc):1} -> "
            f"{smcf.head(arc)}  {flow:3}  / {smcf.capacity(arc):3}       {cost}"
        )


if __name__ == "__main__":
    main()
