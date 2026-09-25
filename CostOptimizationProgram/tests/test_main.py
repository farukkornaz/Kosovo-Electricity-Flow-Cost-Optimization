from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import pytest  # noqa: E402

from main import run  # noqa: E402
from costopt.solution import SolveStatus  # noqa: E402

DATA = Path(__file__).parent.parent / "data"
OUTPUTS = ["model_map.png", "arc_curves.png", "solution_map.png", "solution_paths.png",
           "path_costs.png", "solution.json"]


@pytest.mark.parametrize("model_file", ["sample_network.json", "scenario_gr_demand.json"])
def test_run_writes_all_outputs(tmp_path, model_file):
    result = run(DATA / model_file, tmp_path)
    assert result.status is SolveStatus.OPTIMAL
    assert result.delivered == result.demand
    for name in OUTPUTS:
        assert (tmp_path / name).stat().st_size > 0, name
