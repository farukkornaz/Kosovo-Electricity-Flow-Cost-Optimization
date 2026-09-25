"""Visual check of a NetworkModel before solving.

- draw_model:      nodes at their lat/lon, arcs with capacity and price range.
- draw_arc_curves: per-arc clearing price, marginal cost and the segments the solver will get.

The lower-level helpers (draw_nodes, draw_arcs, finish_map) are shared with solution_map.

CLI:
    python -m costopt.map data/sample_network.json [-o output] [--segments 10] [--show]
"""
import argparse
import math
from pathlib import Path

import matplotlib.pyplot as plt
import networkx as nx
import numpy as np
from matplotlib.lines import Line2D

from costopt.data_loader import load_model
from costopt.model import Arc, DemandNode, NetworkModel, SupplyNode

# Colors: first categorical slots of the dataviz reference palette (CVD-safe as a set) + neutral ink.
BLUE = "#2a78d6"
ORANGE = "#eb6834"
AQUA = "#1baf7a"
INK = "#0b0b0b"
INK_SECONDARY = "#52514e"
MUTED = "#898781"
BASELINE = "#c3c2b7"
GRID = "#e1e0d9"
SURFACE = "#fcfcfb"

NODE_COLORS = {"supply": BLUE, "demand": ORANGE, "transit": MUTED}
NODE_SIZE = 900
ARC_COLOR = INK_SECONDARY
# One-way arcs are straight; both directions of a two-way line bend apart so they don't overlap.
SINGLE_ARC_STYLE = "arc3,rad=0"
PAIRED_ARC_STYLE = "arc3,rad=0.3"

# Candidate label directions (degrees), in order of preference when several are clear.
LABEL_ANGLES = [270, 90, 0, 180, 315, 225, 45, 135]
# An arc at least this far (degrees) from a label direction counts as out of the way.
LABEL_CLEARANCE = 60


def node_kind(node) -> str:
    if isinstance(node, SupplyNode):
        return "supply"
    if isinstance(node, DemandNode):
        return "demand"
    return "transit"


def _node_info(node) -> str:
    if isinstance(node, SupplyNode):
        return f"{node.max_supply} MW @ {node.unit_price:g} €"
    if isinstance(node, DemandNode):
        return f"demand {node.demand} MW"
    return ""


def _graph(model: NetworkModel) -> nx.DiGraph:
    graph = nx.DiGraph()
    graph.add_nodes_from(n.id for n in model.nodes)
    graph.add_edges_from((a.from_node, a.to_node) for a in model.arcs)
    return graph


def _positions(model: NetworkModel) -> dict[str, tuple[float, float]]:
    return {n.id: (n.lon, n.lat) for n in model.nodes}


def _x_scale(model: NetworkModel) -> float:
    """Rough equirectangular projection: east-west shrink factor at the network's latitude."""
    return math.cos(math.radians(np.mean([n.lat for n in model.nodes])))


def _label_angle(model: NetworkModel, node_id: str, x_scale: float) -> int:
    """Direction for a node's info label that keeps it away from the node's arcs."""
    here = model.node(node_id)
    arc_angles = []
    for arc in model.arcs_from(node_id) + model.arcs_to(node_id):
        other = model.node(arc.to_node if arc.from_node == node_id else arc.from_node)
        dx, dy = (other.lon - here.lon) * x_scale, other.lat - here.lat
        arc_angles.append(math.degrees(math.atan2(dy, dx)) % 360)

    def clearance(angle):
        gaps = [min(abs(angle - a), 360 - abs(angle - a)) for a in arc_angles]
        return min(min(gaps, default=180), LABEL_CLEARANCE)

    return max(LABEL_ANGLES, key=clearance)  # max() keeps the first (preferred) on ties


def _annotate_node(ax, xy, angle: int, text: str, color: str = INK):
    dx, dy = math.cos(math.radians(angle)), math.sin(math.radians(angle))
    ha = "left" if dx > 0.3 else "right" if dx < -0.3 else "center"
    va = "bottom" if dy > 0.3 else "top" if dy < -0.3 else "center"
    ax.annotate(
        text, xy=xy, xytext=(20 * dx, 20 * dy), textcoords="offset points",
        ha=ha, va=va, fontsize=8, color=color,
        bbox=dict(boxstyle="round,pad=0.2", fc="white", ec="none", alpha=0.8),
    )


def draw_nodes(ax, model: NetworkModel, faded: set[str] = frozenset(), node_size: int = NODE_SIZE):
    """Nodes colored by kind; `faded` nodes are drawn as light outlines (e.g. unused suppliers)."""
    graph, pos = _graph(model), _positions(model)
    active = [n.id for n in model.nodes if n.id not in faded]
    passive = [n.id for n in model.nodes if n.id in faded]
    nx.draw_networkx_nodes(
        graph, pos, ax=ax, nodelist=active, node_size=node_size, edgecolors=INK,
        node_color=[NODE_COLORS[node_kind(model.node(n))] for n in active],
    )
    nx.draw_networkx_labels(
        graph, pos, ax=ax, labels={n: n for n in active},
        font_weight="bold", font_color="white", font_size=10 if node_size >= NODE_SIZE else 7,
    )
    if passive:
        nx.draw_networkx_nodes(
            graph, pos, ax=ax, nodelist=passive, node_size=node_size, node_color="white",
            edgecolors=[NODE_COLORS[node_kind(model.node(n))] for n in passive], linewidths=1.5,
        )
        nx.draw_networkx_labels(
            graph, pos, ax=ax, labels={n: n for n in passive}, font_color=INK_SECONDARY,
            font_size=10 if node_size >= NODE_SIZE else 7,
        )


def draw_arcs(
    ax,
    model: NetworkModel,
    arcs: list[Arc],
    widths: list[float],
    color: str = ARC_COLOR,
    labels: dict[str, str] | None = None,
    style: str = "solid",
    node_size: int = NODE_SIZE,
    arrowsize: int = 18,
):
    """Draw `arcs` (a subset of the model's arcs); two-way lines bend apart consistently."""
    if not arcs:
        return
    graph, pos = _graph(model), _positions(model)
    width_of = dict(zip((a.id for a in arcs), widths))
    model_edges = {(a.from_node, a.to_node) for a in model.arcs}
    paired = [a for a in arcs if (a.to_node, a.from_node) in model_edges]
    single = [a for a in arcs if (a.to_node, a.from_node) not in model_edges]

    for group, connection in ((single, SINGLE_ARC_STYLE), (paired, PAIRED_ARC_STYLE)):
        if not group:
            continue
        nx.draw_networkx_edges(
            graph, pos, ax=ax, edgelist=[(a.from_node, a.to_node) for a in group],
            node_size=node_size, width=[width_of[a.id] for a in group], style=style,
            arrowsize=arrowsize, edge_color=color, connectionstyle=connection,
        )
        group_labels = {(a.from_node, a.to_node): labels[a.id] for a in group if labels and a.id in labels}
        if not group_labels:
            continue
        texts = nx.draw_networkx_edge_labels(
            graph, pos, ax=ax, edge_labels=group_labels, font_size=7, font_color=INK,
            connectionstyle=connection, node_size=node_size, rotate=False,
            bbox=dict(boxstyle="round,pad=0.2", fc="white", ec=BASELINE, alpha=0.9),
        )
        for text in texts.values():
            text.set_zorder(4)  # above nodes, so labels on short arcs stay readable


def finish_map(ax, model: NetworkModel, node_texts: dict[str, str] | None = None,
               faded: set[str] = frozenset(), axis_labels: bool = True):
    """Projection, margins, node info texts and recessive axes."""
    x_scale = _x_scale(model)
    ax.set_aspect(1 / x_scale)
    ax.margins(0.15)
    pos = _positions(model)
    for node_id, text in (node_texts or {}).items():
        color = INK_SECONDARY if node_id in faded else INK
        _annotate_node(ax, pos[node_id], _label_angle(model, node_id, x_scale), text, color)
    for spine in ax.spines.values():
        spine.set_color(BASELINE)
    if axis_labels:
        ax.set_xlabel("longitude", color=MUTED)
        ax.set_ylabel("latitude", color=MUTED)
        ax.tick_params(left=True, bottom=True, labelleft=True, labelbottom=True, colors=MUTED)
    else:
        ax.tick_params(left=False, bottom=False, labelleft=False, labelbottom=False)


def node_legend_handles() -> list[Line2D]:
    return [
        Line2D([], [], marker="o", ls="", ms=10, mfc=color, mec=INK, label=kind)
        for kind, color in NODE_COLORS.items()
    ]


def draw_model(model: NetworkModel, ax=None, title: str | None = None):
    if ax is None:
        _, ax = plt.subplots(figsize=(16, 9))

    max_capacity = max(a.capacity for a in model.arcs)
    draw_arcs(
        ax, model, model.arcs,
        widths=[1 + 4 * a.capacity / max_capacity for a in model.arcs],
        labels={
            a.id: f"{a.capacity} MW\n{a.curve.clearing_price(0):.1f}–{a.curve.clearing_price(a.capacity):.1f} €"
            for a in model.arcs
        },
    )
    draw_nodes(ax, model)
    finish_map(ax, model, {n.id: f"{n.name}\n{_node_info(n)}" for n in model.nodes})

    ax.legend(
        handles=node_legend_handles()
        + [Line2D([], [], color=ARC_COLOR, lw=3, label="arc: capacity · P(0)–P(cap)")],
        loc="upper right", fontsize=8,
    )
    ax.set_title(title or f"{model.name}: {len(model.nodes)} nodes, {len(model.arcs)} arcs")
    return ax


def draw_arc_curves(model: NetworkModel, num_segments: int = 10, cols: int = 3):
    arcs = model.arcs
    rows = math.ceil(len(arcs) / cols)
    fig, axes = plt.subplots(rows, cols, figsize=(4.5 * cols, 3.2 * rows), squeeze=False)

    for ax, arc in zip(axes.flat, arcs):
        curve = arc.curve
        q = np.linspace(0, arc.capacity, 200)
        total_cost = np.array([curve.total_cost(x) for x in q])
        segments = curve.segments(num_segments)
        bounds = np.concatenate([[0], np.cumsum([s.capacity for s in segments])])

        ax.plot(q, [curve.clearing_price(x) for x in q], color=BLUE, lw=2, label="clearing price P(q)")
        ax.plot(q, np.gradient(total_cost, q), color=ORANGE, lw=2, ls="--", label="marginal cost")
        ax.stairs([s.unit_cost for s in segments], bounds, color=AQUA, lw=1.5, label="solver segments")
        ax.set_title(arc.id, fontsize=10)
        ax.set_xlabel("our quantity q (MW)", fontsize=8, color=MUTED)
        ax.set_ylabel("€/MWh", fontsize=8, color=MUTED)
        ax.tick_params(colors=MUTED, labelsize=8)
        ax.grid(color=GRID, lw=0.8)
        for spine in ax.spines.values():
            spine.set_color(BASELINE)

    for ax in axes.flat[len(arcs):]:
        ax.axis("off")
    axes.flat[0].legend(fontsize=7)
    fig.suptitle(f"{model.name}: arc price curves ({num_segments} segments)")
    fig.tight_layout()
    return fig


def main():
    parser = argparse.ArgumentParser(description="Draw a network model for visual checking.")
    parser.add_argument("model", help="model JSON file")
    parser.add_argument("-o", "--out-dir", default="output")
    parser.add_argument("--segments", type=int, default=10)
    parser.add_argument("--show", action="store_true", help="also open the figures in a window")
    args = parser.parse_args()

    model = load_model(args.model)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    model_map = out_dir / "model_map.png"
    draw_model(model).figure.savefig(model_map, dpi=150, bbox_inches="tight")
    arc_curves = out_dir / "arc_curves.png"
    draw_arc_curves(model, args.segments).savefig(arc_curves, dpi=150, bbox_inches="tight")
    print(f"Saved {model_map}\nSaved {arc_curves}")

    if args.show:
        plt.show()


if __name__ == "__main__":
    main()
