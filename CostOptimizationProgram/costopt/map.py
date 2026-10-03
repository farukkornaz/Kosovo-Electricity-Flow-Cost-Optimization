"""Visual check of a NetworkModel before solving.

- draw_model:      nodes at their lat/lon, arcs with capacity and price range.
- draw_arc_curves: per-arc clearing price, marginal cost and the segments the solver will get.

The lower-level helpers (draw_nodes, draw_arcs, finish_map) are shared with solution_map.

CLI:
    python -m costopt.map data/sample_network.json [-o output] [--segments 10] [--show]
"""
import argparse
import math
from dataclasses import dataclass
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
PAIRED_ARC_RAD = 0.3
SINGLE_ARC_STYLE = "arc3,rad=0"
PAIRED_ARC_STYLE = f"arc3,rad={PAIRED_ARC_RAD}"

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


MAP_PADDING = 0.15  # fraction of the network's extent added around the nodes


def _map_extent(model: NetworkModel) -> tuple[float, float, float, float]:
    """(lon_min, lon_max, lat_min, lat_max) of the nodes, padded."""
    lons, lats = [n.lon for n in model.nodes], [n.lat for n in model.nodes]
    pad_lon = MAP_PADDING * (max(lons) - min(lons)) or 1.0
    pad_lat = MAP_PADDING * (max(lats) - min(lats)) or 1.0
    return min(lons) - pad_lon, max(lons) + pad_lon, min(lats) - pad_lat, max(lats) + pad_lat


def map_figsize(model: NetworkModel, max_width: float = 16, max_height: float = 14) -> tuple[float, float]:
    """Figure size following the network's shape, so the map fills the figure."""
    lon_min, lon_max, lat_min, lat_max = _map_extent(model)
    ratio = (lat_max - lat_min) / ((lon_max - lon_min) * _x_scale(model))
    if max_width * ratio <= max_height:
        return max_width, max(9.0, max_width * ratio)
    return max(10.0, max_height / ratio), max_height


# Other arcs passing closer than this (fraction of the map extent) also steer a node's label away.
NEARBY_ARC_RADIUS = 0.1
# Candidate spots for an arc label, as a fraction along the arc from its tail (preferred first).
ARC_LABEL_SPOTS = [0.5, 0.4, 0.6, 0.3, 0.7, 0.2, 0.8]
LABEL_GAP_PX = 3  # breathing room kept around labels when checking overlaps


@dataclass(frozen=True)
class ArcLabel:
    """An arc label to be placed by finish_map, once node texts exist and can be avoided."""

    tail: str
    head: str
    text: str
    rad: float = 0.0  # curvature of the drawn arc (matplotlib arc3 connection style)


def _projected(model: NetworkModel, x_scale: float) -> dict[str, np.ndarray]:
    return {n.id: np.array([n.lon * x_scale, n.lat]) for n in model.nodes}


def _extent(points: dict[str, np.ndarray]) -> float:
    xy = np.array(list(points.values()))
    return float(max(np.ptp(xy[:, 0]), np.ptp(xy[:, 1]))) or 1.0


def _closest_on_segment(p: np.ndarray, a: np.ndarray, b: np.ndarray) -> np.ndarray:
    ab = b - a
    t = np.clip(np.dot(p - a, ab) / (np.dot(ab, ab) or 1.0), 0, 1)
    return a + t * ab


def _label_angle(model: NetworkModel, node_id: str, x_scale: float) -> int:
    """Direction for a node's info label that keeps it away from its own arcs and arcs passing nearby."""
    pts = _projected(model, x_scale)
    here = pts[node_id]
    radius = NEARBY_ARC_RADIUS * _extent(pts)
    directions = []
    for arc in model.arcs:
        if node_id in (arc.from_node, arc.to_node):
            other = arc.to_node if arc.from_node == node_id else arc.from_node
            directions.append(pts[other] - here)
        else:
            nearest = _closest_on_segment(here, pts[arc.from_node], pts[arc.to_node])
            if np.linalg.norm(nearest - here) < radius:
                directions.append(nearest - here)
    arc_angles = [math.degrees(math.atan2(d[1], d[0])) % 360 for d in directions]

    def clearance(angle):
        gaps = [min(abs(angle - a), 360 - abs(angle - a)) for a in arc_angles]
        return min(min(gaps, default=180), LABEL_CLEARANCE)

    return max(LABEL_ANGLES, key=clearance)  # max() keeps the first (preferred) on ties


def _annotate_node(ax, xy, angle: int, text: str, color: str = INK):
    dx, dy = math.cos(math.radians(angle)), math.sin(math.radians(angle))
    ha = "left" if dx > 0.3 else "right" if dx < -0.3 else "center"
    va = "bottom" if dy > 0.3 else "top" if dy < -0.3 else "center"
    return ax.annotate(
        text, xy=xy, xytext=(20 * dx, 20 * dy), textcoords="offset points",
        ha=ha, va=va, fontsize=8, color=color,
        bbox=dict(boxstyle="round,pad=0.2", fc="white", ec="none", alpha=0.8),
    )


def _renderer(fig):
    try:
        return fig.canvas.get_renderer()
    except AttributeError:
        return fig._get_renderer()


def _box_overlap(a, b) -> float:
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    return w * h if w > 0 and h > 0 else 0.0


def _place_arc_labels(ax, model: NetworkModel, requests: list[ArcLabel], obstacles: list, node_size: int):
    """Put each arc label where it overlaps the least with nodes, node texts and earlier labels.

    Candidates are spots along the arc (on the line first, then just beside it); among equally
    good spots the preferred one wins. Works in display pixels, so real text sizes are used.
    """
    renderer = _renderer(ax.figure)
    to_display, to_data = ax.transData.transform, ax.transData.inverted().transform
    radius = math.sqrt(node_size) / 2 * ax.figure.dpi / 72
    boxes = list(obstacles) + [
        (x - radius, y - radius, x + radius, y + radius)
        for x, y in (to_display(p) for p in _positions(model).values())
    ]
    pos = _positions(model)
    for request in requests:
        p0, p2 = to_display(pos[request.tail]), to_display(pos[request.head])
        d = p2 - p0
        control = (p0 + p2) / 2 + request.rad * np.array([d[1], -d[0]])  # same formula as arc3
        text = ax.text(
            0, 0, request.text, ha="center", va="center", fontsize=7, color=INK, zorder=4,
            bbox=dict(boxstyle="round,pad=0.2", fc="white", ec=BASELINE, alpha=0.9),
        )
        extent = text.get_window_extent(renderer)
        half = np.array([extent.width, extent.height]) / 2 + LABEL_GAP_PX

        candidates = []
        for side in (0, 1, -1):
            for t in ARC_LABEL_SPOTS:
                point = (1 - t) ** 2 * p0 + 2 * (1 - t) * t * control + t ** 2 * p2
                tangent = 2 * (1 - t) * (control - p0) + 2 * t * (p2 - control)
                normal = np.array([-tangent[1], tangent[0]]) / (np.linalg.norm(tangent) or 1.0)
                shift = abs(normal[0]) * half[0] + abs(normal[1]) * half[1]  # just clear of the line
                candidates.append(point + side * shift * normal)

        def cost(center):
            box = (*(center - half), *(center + half))
            return sum(_box_overlap(box, b) for b in boxes)

        best = min(candidates, key=cost)  # min() keeps the first (preferred) of equal costs
        text.set_position(to_data(best))
        boxes.append((*(best - half), *(best + half)))


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
    straight: set[str] = frozenset(),
):
    """Draw `arcs` (a subset of the model's arcs); two-way lines bend apart consistently.

    Arc ids in `straight` are drawn straight even if the reverse direction exists
    (e.g. a line used in one direction only, with the reverse not drawn).
    Returns the labels to place; pass them to finish_map.
    """
    if not arcs:
        return []
    graph, pos = _graph(model), _positions(model)
    width_of = dict(zip((a.id for a in arcs), widths))
    model_edges = {(a.from_node, a.to_node) for a in model.arcs}
    curved = [a for a in arcs if (a.to_node, a.from_node) in model_edges and a.id not in straight]
    single = [a for a in arcs if a not in curved]
    paired = curved

    requests = []
    for group, connection, rad in ((single, SINGLE_ARC_STYLE, 0.0), (paired, PAIRED_ARC_STYLE, PAIRED_ARC_RAD)):
        if not group:
            continue
        nx.draw_networkx_edges(
            graph, pos, ax=ax, edgelist=[(a.from_node, a.to_node) for a in group],
            node_size=node_size, width=[width_of[a.id] for a in group], style=style,
            arrowsize=arrowsize, edge_color=color, connectionstyle=connection,
        )
        requests += [ArcLabel(a.from_node, a.to_node, labels[a.id], rad)
                     for a in group if labels and a.id in labels]
    return requests


def split_pairs(arcs: list[Arc], same=lambda a, b: True) -> tuple[list[tuple[Arc, Arc]], list[Arc]]:
    """Pair up arcs whose reverse is also in `arcs` and passes `same(a, reverse)`; return (pairs, rest)."""
    by_id = {a.id: a for a in arcs}
    pairs, rest, seen = [], [], set()
    for arc in arcs:
        if arc.id in seen:
            continue
        reverse = by_id.get(f"{arc.to_node}->{arc.from_node}")
        if reverse and same(arc, reverse):
            pairs.append((arc, reverse))
            seen |= {arc.id, reverse.id}
        else:
            rest.append(arc)
            seen.add(arc.id)
    return pairs, rest


def draw_lines(
    ax,
    model: NetworkModel,
    pairs: list[tuple[Arc, Arc]],
    widths: list[float],
    color: str = ARC_COLOR,
    labels: dict[str, str] | None = None,
    style: str = "solid",
    two_way_arrows: bool = True,
    node_size: int = NODE_SIZE,
    arrowsize: int = 14,
):
    """One straight line per two-way pair, instead of two curved arcs. `labels` are keyed by the first arc's id.

    Returns the labels to place; pass them to finish_map.
    """
    if not pairs:
        return []
    graph, pos = _graph(model), _positions(model)
    nx.draw_networkx_edges(
        graph, pos, ax=ax, edgelist=[(a.from_node, a.to_node) for a, _ in pairs],
        node_size=node_size, width=widths, style=style, edge_color=color,
        arrowstyle="<|-|>" if two_way_arrows else "-", arrowsize=arrowsize,
        connectionstyle=SINGLE_ARC_STYLE,
    )
    return [ArcLabel(a.from_node, a.to_node, labels[a.id]) for a, _ in pairs if labels and a.id in labels]


def finish_map(ax, model: NetworkModel, node_texts: dict[str, str] | None = None,
               faded: set[str] = frozenset(), axis_labels: bool = True,
               arc_labels: list[ArcLabel] = (), node_size: int = NODE_SIZE):
    """Projection, margins, node info texts, arc labels (placed around the node texts) and recessive axes."""
    x_scale = _x_scale(model)
    lon_min, lon_max, lat_min, lat_max = _map_extent(model)
    ax.set_xlim(lon_min, lon_max)
    ax.set_ylim(lat_min, lat_max)
    # adjustable="datalim" widens the limits to the figure's shape instead of shrinking the map
    ax.set_aspect(1 / x_scale, adjustable="datalim")
    ax.apply_aspect()  # fix the final limits now, so label placement sees the real layout
    pos = _positions(model)
    node_labels = []
    for node_id, text in (node_texts or {}).items():
        color = INK_SECONDARY if node_id in faded else INK
        node_labels.append(_annotate_node(ax, pos[node_id], _label_angle(model, node_id, x_scale), text, color))
    if arc_labels:
        renderer = _renderer(ax.figure)
        obstacles = []
        for label in node_labels:
            e = label.get_window_extent(renderer)
            obstacles.append((e.x0 - LABEL_GAP_PX, e.y0 - LABEL_GAP_PX, e.x1 + LABEL_GAP_PX, e.y1 + LABEL_GAP_PX))
        _place_arc_labels(ax, model, list(arc_labels), obstacles, node_size)
    for spine in ax.spines.values():
        spine.set_color(BASELINE)
    if axis_labels:
        ax.set_xlabel("longitude", color=MUTED)
        ax.set_ylabel("latitude", color=MUTED)
        ax.tick_params(left=True, bottom=True, labelleft=True, labelbottom=True, colors=MUTED)
    else:
        ax.tick_params(left=False, bottom=False, labelleft=False, labelbottom=False)


def closed_legend_handle() -> Line2D:
    return Line2D([], [], color=BASELINE, lw=1.5, ls=":", label="closed (ATC 0)")


def draw_closed_arcs(ax, model: NetworkModel, node_size: int = NODE_SIZE, arrowsize: int = 8):
    """Closed lines: dotted; a line closed in both directions is a single plain dotted line."""
    pairs, rest = split_pairs([a for a in model.arcs if a.is_closed])
    draw_lines(ax, model, pairs, widths=[1.5] * len(pairs), color=BASELINE, style="dotted",
               two_way_arrows=False, node_size=node_size)
    draw_arcs(ax, model, rest, widths=[1.5] * len(rest), color=BASELINE, style="dotted",
              node_size=node_size, arrowsize=arrowsize)


def _price_range(arc: Arc) -> str:
    return f"{arc.curve.clearing_price(0):.1f}–{arc.curve.clearing_price(arc.capacity):.1f} €"


def node_legend_handles() -> list[Line2D]:
    return [
        Line2D([], [], marker="o", ls="", ms=10, mfc=color, mec=INK, label=kind)
        for kind, color in NODE_COLORS.items()
    ]


def draw_model(model: NetworkModel, ax=None, title: str | None = None):
    if ax is None:
        _, ax = plt.subplots(figsize=map_figsize(model))

    open_arcs = [a for a in model.arcs if not a.is_closed]
    max_capacity = max((a.capacity for a in open_arcs), default=1)
    # Same ATC both ways -> one two-way line. Its price range is shown only if both directions share the curve.
    pairs, one_way = split_pairs(open_arcs, same=lambda a, b: a.capacity == b.capacity)
    draw_closed_arcs(ax, model)
    labels = draw_lines(
        ax, model, pairs,
        widths=[1 + 4 * a.capacity / max_capacity for a, _ in pairs],
        labels={
            a.id: f"{a.capacity} MW ↔" + (f"\n{_price_range(a)}" if a.curve == b.curve else "")
            for a, b in pairs
        },
    )
    labels += draw_arcs(
        ax, model, one_way,
        widths=[1 + 4 * a.capacity / max_capacity for a in one_way],
        labels={a.id: f"{a.capacity} MW\n{_price_range(a)}" for a in one_way},
    )
    draw_nodes(ax, model)
    finish_map(ax, model, {n.id: f"{n.name}\n{_node_info(n)}" for n in model.nodes}, arc_labels=labels)

    ax.legend(
        handles=node_legend_handles()
        + [Line2D([], [], color=ARC_COLOR, lw=3, label="arc: ATC · P(0)–P(cap)")]
        + ([Line2D([], [], color=ARC_COLOR, lw=3, marker="$↔$", ms=14,
                   label="two-way, same ATC each direction")] if pairs else [])
        + ([closed_legend_handle()] if len(open_arcs) < len(model.arcs) else []),
        loc="upper right", fontsize=8,
    )
    ax.set_title(title or f"{model.name}: {len(model.nodes)} nodes, {len(model.arcs)} arcs")
    return ax


def draw_arc_curves(model: NetworkModel, num_segments: int = 10, cols: int | None = None):
    arcs = [a for a in model.arcs if not a.is_closed]  # a closed line has no curve to show
    cols = cols or (3 if len(arcs) <= 12 else 6)
    rows = max(1, math.ceil(len(arcs) / cols))
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
