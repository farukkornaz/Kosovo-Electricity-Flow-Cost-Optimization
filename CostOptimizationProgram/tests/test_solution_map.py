from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import pytest  # noqa: E402

from costopt.data_loader import load_model  # noqa: E402
from costopt.min_cost_route_solver import MinCostRouteSolver  # noqa: E402
from costopt.model import Arc, DemandNode, NetworkModel, SupplyNode  # noqa: E402
from costopt.price_curve import LinearPriceCurve  # noqa: E402
from costopt.solution import SolveStatus, error_solution  # noqa: E402
from costopt.solution_map import draw_path_costs, draw_paths, draw_solution  # noqa: E402

SAMPLE = Path(__file__).parent.parent / "data" / "sample_network.json"


def test_draw_sample_solution(tmp_path):
    model = load_model(SAMPLE)
    result = MinCostRouteSolver().solve(model)
    draw_solution(model, result).figure.savefig(tmp_path / "solution.png")
    paths = draw_paths(model, result)
    paths.savefig(tmp_path / "paths.png")
    draw_path_costs(model, result).savefig(tmp_path / "costs.png")
    assert sum(a.axison for a in paths.axes) == len(result.paths)
    for name in ("solution.png", "paths.png", "costs.png"):
        assert (tmp_path / name).stat().st_size > 0


def test_draw_infeasible_solution():
    model = NetworkModel()
    model.add_node(SupplyNode("A", "A", 0, 0, max_supply=500, unit_price=50))
    model.add_node(DemandNode("D", "D", 1, 0, demand=300))
    model.add_arc(Arc("A", "D", LinearPriceCurve(10, 0, 120)))
    result = MinCostRouteSolver().solve(model)
    assert result.status is SolveStatus.INFEASIBLE
    ax = draw_solution(model, result)
    assert "120 / 300" in ax.get_title()


def test_error_result_is_rejected():
    model = load_model(SAMPLE)
    with pytest.raises(ValueError, match="Nothing to draw"):
        draw_solution(model, error_solution(model, "boom", 10))
