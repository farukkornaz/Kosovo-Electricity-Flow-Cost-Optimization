from pathlib import Path

import matplotlib

matplotlib.use("Agg")

from costopt.data_loader import load_model  # noqa: E402
from costopt.map import LABEL_CLEARANCE, _label_angle, draw_arc_curves, draw_model  # noqa: E402
from costopt.model import Arc, DemandNode, NetworkModel, SupplyNode  # noqa: E402
from costopt.price_curve import LinearPriceCurve  # noqa: E402

SAMPLE = Path(__file__).parent.parent / "data" / "sample_network.json"


def test_draw_sample_to_png(tmp_path):
    model = load_model(SAMPLE)
    ax = draw_model(model)
    ax.figure.savefig(tmp_path / "map.png")
    fig = draw_arc_curves(model, num_segments=5)
    fig.savefig(tmp_path / "curves.png")
    assert (tmp_path / "map.png").stat().st_size > 0
    assert (tmp_path / "curves.png").stat().st_size > 0
    # one subplot per arc, the rest switched off
    assert sum(a.axison for a in fig.axes) == len(model.arcs)


def test_label_avoids_arcs():
    model = NetworkModel()
    model.add_node(SupplyNode("N", "N", lat=1, lon=0, max_supply=10, unit_price=1))
    model.add_node(DemandNode("S", "S", lat=0, lon=0, demand=5))
    model.add_arc(Arc("N", "S", LinearPriceCurve(1, 0, 10)))
    # The only arc points straight down from N, so N's label must not go below it.
    angle = _label_angle(model, "N", x_scale=1.0)
    assert min(abs(angle - 270), 360 - abs(angle - 270)) >= LABEL_CLEARANCE
