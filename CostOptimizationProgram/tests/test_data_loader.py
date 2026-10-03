from pathlib import Path

import pytest

from costopt.data_loader import load_model, model_from_dict, model_to_dict, save_model
from costopt.model import SupplyNode

SAMPLE = Path(__file__).parent.parent / "data" / "sample_network.json"


def test_load_sample():
    model = load_model(SAMPLE)
    assert model.demand_node.id == "TR"
    assert len(model.supply_nodes) == 6
    assert len(model.arcs) == 8
    assert isinstance(model.node("BG"), SupplyNode)


def test_xk_scenario_closed_borders():
    model = load_model(SAMPLE.parent / "scenario_xk_demand.json")
    assert model.demand_node.id == "XK"
    closed = sorted(a.id for a in model.arcs if a.is_closed)
    assert closed == ["AL->MK", "MK->AL", "RS->XK", "XK->RS"]


def test_roundtrip(tmp_path):
    model = load_model(SAMPLE)
    out = tmp_path / "out.json"
    save_model(model, out)
    assert model_to_dict(load_model(out)) == model_to_dict(model)


def test_unknown_field_is_reported():
    data = {
        "nodes": [{"id": "A", "name": "A", "lat": 0, "lon": 0, "type": "supply",
                   "max_supply": 10, "unit_price": 1, "colour": "red"}],
        "arcs": [],
    }
    with pytest.raises(ValueError, match="colour"):
        model_from_dict(data)


def test_unknown_curve_type():
    data = {
        "nodes": [
            {"id": "A", "name": "A", "lat": 0, "lon": 0, "type": "supply", "max_supply": 10, "unit_price": 1},
            {"id": "B", "name": "B", "lat": 0, "lon": 1, "type": "demand", "demand": 5},
        ],
        "arcs": [{"from": "A", "to": "B", "curve": {"type": "step", "capacity": 10}}],
    }
    with pytest.raises(ValueError, match="unknown curve type"):
        model_from_dict(data)
