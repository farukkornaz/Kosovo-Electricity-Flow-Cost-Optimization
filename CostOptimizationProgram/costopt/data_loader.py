"""Read/write NetworkModel as JSON.

Format:
{
  "name": "...",
  "nodes": [
    {"id": "TR", "name": "Türkiye", "lat": 39.0, "lon": 35.0, "type": "demand", "demand": 1000},
    {"id": "BG", "name": "Bulgaria", "lat": 42.7, "lon": 25.3, "type": "supply",
     "max_supply": 700, "unit_price": 95.0},
    {"id": "XX", "name": "...", "lat": 0, "lon": 0, "type": "transit"}
  ],
  "arcs": [
    {"from": "BG", "to": "TR",
     "curve": {"type": "linear", "base_price": 8.0, "slope": 0.03, "capacity": 600}}
  ]
}
"""
import json
from dataclasses import asdict, fields
from pathlib import Path

from costopt.model import Arc, DemandNode, NetworkModel, Node, SupplyNode
from costopt.price_curve import LinearPriceCurve, PriceCurve

NODE_TYPES: dict[str, type[Node]] = {
    "transit": Node,
    "supply": SupplyNode,
    "demand": DemandNode,
}

CURVE_TYPES: dict[str, type[PriceCurve]] = {
    "linear": LinearPriceCurve,
}


def _type_name(obj, registry: dict[str, type]) -> str:
    for name, cls in registry.items():
        if type(obj) is cls:
            return name
    raise TypeError(f"Unregistered type: {type(obj).__name__}")


def _build(cls: type, data: dict, context: str):
    expected = {f.name for f in fields(cls)}
    missing = expected - data.keys()
    unknown = data.keys() - expected
    if missing or unknown:
        raise ValueError(f"{context}: missing {sorted(missing)}, unknown {sorted(unknown)}")
    return cls(**data)


def model_from_dict(data: dict) -> NetworkModel:
    model = NetworkModel(data.get("name", "network"))
    for raw in data["nodes"]:
        raw = dict(raw)
        node_type = raw.pop("type", "transit")
        if node_type not in NODE_TYPES:
            raise ValueError(f"Node {raw.get('id')}: unknown type '{node_type}'")
        model.add_node(_build(NODE_TYPES[node_type], raw, f"Node {raw.get('id')}"))
    for raw in data["arcs"]:
        context = f"Arc {raw['from']}->{raw['to']}"
        curve_data = dict(raw["curve"])
        curve_type = curve_data.pop("type")
        if curve_type not in CURVE_TYPES:
            raise ValueError(f"{context}: unknown curve type '{curve_type}'")
        curve = _build(CURVE_TYPES[curve_type], curve_data, context)
        model.add_arc(Arc(raw["from"], raw["to"], curve))
    model.validate()
    return model


def model_to_dict(model: NetworkModel) -> dict:
    return {
        "name": model.name,
        "nodes": [{**asdict(n), "type": _type_name(n, NODE_TYPES)} for n in model.nodes],
        "arcs": [
            {
                "from": a.from_node,
                "to": a.to_node,
                "curve": {"type": _type_name(a.curve, CURVE_TYPES), **asdict(a.curve)},
            }
            for a in model.arcs
        ],
    }


def load_model(path: str | Path) -> NetworkModel:
    with open(path, encoding="utf-8") as f:
        return model_from_dict(json.load(f))


def save_model(model: NetworkModel, path: str | Path) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(model_to_dict(model), f, indent=2, ensure_ascii=False)
