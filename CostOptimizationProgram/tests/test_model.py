import pytest

from costopt.model import Arc, DemandNode, ModelValidationError, NetworkModel, Node, SupplyNode
from costopt.price_curve import LinearPriceCurve


def curve(capacity=100):
    return LinearPriceCurve(base_price=10, slope=0.1, capacity=capacity)


def small_model():
    model = NetworkModel("small")
    model.add_node(SupplyNode("A", "A", 0, 0, max_supply=100, unit_price=50))
    model.add_node(Node("B", "B", 0, 1))
    model.add_node(DemandNode("C", "C", 0, 2, demand=80))
    model.add_arc(Arc("A", "B", curve()))
    model.add_arc(Arc("B", "C", curve(90)))
    return model


def test_queries():
    model = small_model()
    model.validate()
    assert model.demand_node.id == "C"
    assert [n.id for n in model.supply_nodes] == ["A"]
    assert model.arc("B->C").capacity == 90
    assert [a.id for a in model.arcs_from("B")] == ["B->C"]
    assert [a.id for a in model.arcs_to("B")] == ["A->B"]
    assert "small" in model.summary()


def test_add_rejects_bad_input():
    model = small_model()
    with pytest.raises(ValueError, match="Duplicate node"):
        model.add_node(Node("A", "A", 0, 0))
    with pytest.raises(ValueError, match="unknown node"):
        model.add_arc(Arc("A", "Z", curve()))
    with pytest.raises(ValueError, match="self-loop"):
        model.add_arc(Arc("A", "A", curve()))
    with pytest.raises(ValueError, match="Duplicate arc"):
        model.add_arc(Arc("A", "B", curve()))


def test_node_value_checks():
    with pytest.raises(ValueError):
        SupplyNode("A", "A", 0, 0, max_supply=0, unit_price=10)
    with pytest.raises(ValueError):
        DemandNode("A", "A", 0, 0, demand=-5)


def test_validate_collects_all_errors():
    model = NetworkModel()
    model.add_node(SupplyNode("A", "A", 0, 0, max_supply=100, unit_price=50))
    model.add_node(DemandNode("C", "C", 0, 2, demand=80))
    model.add_node(DemandNode("D", "D", 0, 3, demand=10))
    with pytest.raises(ModelValidationError) as exc:
        model.validate()
    errors = exc.value.errors
    assert any("Exactly one demand" in e for e in errors)
    assert any("no outgoing arc" in e for e in errors)
    assert any("no incoming arc" in e for e in errors)
