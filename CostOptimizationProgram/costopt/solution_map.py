"""Visual inspection of a solved problem on the network map.

- draw_solution:   flows on the map. Width follows flow; labels show flow/capacity, utilization
                   and clearing price. Unused arcs are dashed, unused suppliers are outlines.
- draw_paths:      one small map per path, with that path highlighted.
- draw_path_costs: €/MWh per path, split into supply and transport.

CLI:
    python -m costopt.solution_map data/sample_network.json [-o output] [--segments 10] [--show]
"""
import argparse
import math
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.lines import Line2D

from costopt.data_loader import load_model
from costopt.map import (
    AQUA, ARC_COLOR, BASELINE, BLUE, GRID, INK, INK_SECONDARY, MUTED, SURFACE,
    closed_legend_handle, map_figsize, draw_arcs, draw_closed_arcs, draw_lines, draw_nodes, finish_map,
    node_legend_handles, split_pairs,
)
from costopt.min_cost_route_solver import MinCostRouteSolver
from costopt.model import DemandNode, NetworkModel, SupplyNode
from costopt.solution import RoutePath, SolutionResult, SolveStatus

SMALL_NODE_SIZE = 250
PANEL_WIDTH = 5.5  # inches, per small-multiple map


def _check_drawable(result: SolutionResult):
    if result.status is SolveStatus.ERROR:
        raise ValueError(f"Nothing to draw, solver failed: {result.message}")


def _reverse_id(arc) -> str:
    return f"{arc.to_node}->{arc.from_node}"


def _path_arc_ids(path: RoutePath) -> set[str]:
    return {f"{a}->{b}" for a, b in zip(path.nodes[:-1], path.nodes[1:])}


def _title(model: NetworkModel, result: SolutionResult) -> str:
    return (
        f"{model.name}: {result.status.value} · {result.delivered} / {result.demand} MW to {result.demand_node} · "
        f"{result.total_cost:,.0f} € ({result.unit_cost:.2f} €/MWh)"
    )


def draw_solution(model: NetworkModel, result: SolutionResult, ax=None, title: str | None = None):
    _check_drawable(result)
    if ax is None:
        _, ax = plt.subplots(figsize=map_figsize(model))

    used = [a for a in model.arcs if result.arc(a.id).flow > 0]
    used_ids = {a.id for a in used}
    # A line used in one direction is drawn straight; its unused reverse direction is left out.
    one_way_used = {a.id for a in used if _reverse_id(a) not in used_ids}
    unused = [a for a in model.arcs
              if result.arc(a.id).flow == 0 and not a.is_closed and _reverse_id(a) not in used_ids]
    max_flow = max((result.arc(a.id).flow for a in used), default=1)

    draw_closed_arcs(ax, model)
    unused_pairs, unused_rest = split_pairs(unused)  # unused both ways -> one plain dashed line
    draw_lines(ax, model, unused_pairs, widths=[1] * len(unused_pairs), color=BASELINE, style="dashed",
               two_way_arrows=False)
    draw_arcs(ax, model, unused_rest, widths=[1] * len(unused_rest), color=BASELINE, style="dashed", arrowsize=10)
    labels = draw_arcs(
        ax, model, used, straight=one_way_used,
        widths=[1.5 + 5 * result.arc(a.id).flow / max_flow for a in used],
        labels={
            a.id: (
                f"{r.flow}/{r.capacity} MW ({r.utilization:.0%})\n{r.clearing_price:.2f} €"
            )
            for a in used
            for r in [result.arc(a.id)]
        },
    )

    unused_suppliers = {s.node_id for s in result.supplies if s.quantity == 0}
    draw_nodes(ax, model, faded=unused_suppliers)

    texts = {}
    for node in model.nodes:
        if isinstance(node, SupplyNode):
            s = result.supply(node.id)
            texts[node.id] = f"{node.name}\n{s.quantity} / {s.max_supply} MW @ {s.unit_price:g} €"
        elif isinstance(node, DemandNode):
            texts[node.id] = f"{node.name}\n{result.delivered} / {result.demand} MW delivered"
        else:
            texts[node.id] = node.name
    finish_map(ax, model, texts, faded=unused_suppliers, arc_labels=labels)

    ax.legend(
        handles=node_legend_handles() + [
            Line2D([], [], marker="o", ls="", ms=10, mfc="white", mec=BLUE, mew=1.5, label="supply, not used"),
            Line2D([], [], color=ARC_COLOR, lw=3, label="flow/cap (use) · clearing price"),
            Line2D([], [], color=BASELINE, lw=1, ls="--", label="arc, not used"),
        ] + ([closed_legend_handle()] if any(a.is_closed for a in model.arcs) else []),
        loc="upper right", fontsize=8,
    )
    ax.set_title(title or _title(model, result))
    return ax


def draw_paths(model: NetworkModel, result: SolutionResult, cols: int = 3):
    """Small multiples: every path on its own mini map."""
    _check_drawable(result)
    paths = result.paths
    rows = max(1, math.ceil(len(paths) / cols))
    width, height = map_figsize(model)
    panel_height = min(6.0, max(3.4, PANEL_WIDTH * height / width))  # panels follow the map's shape
    fig, axes = plt.subplots(rows, cols, figsize=(PANEL_WIDTH * cols, panel_height * rows), squeeze=False)

    for ax, path in zip(axes.flat, paths):
        on_path = _path_arc_ids(path)
        off = [a for a in model.arcs
               if a.id not in on_path and _reverse_id(a) not in on_path and not a.is_closed]
        on = [a for a in model.arcs if a.id in on_path]
        off_pairs, off_rest = split_pairs(off)
        draw_lines(ax, model, off_pairs, widths=[0.8] * len(off_pairs), color=BASELINE,
                   two_way_arrows=False, node_size=SMALL_NODE_SIZE)
        draw_arcs(ax, model, off_rest, widths=[0.8] * len(off_rest), color=BASELINE,
                  node_size=SMALL_NODE_SIZE, arrowsize=6)
        draw_arcs(ax, model, on, widths=[3] * len(on), color=BLUE,
                  node_size=SMALL_NODE_SIZE, arrowsize=12, straight={a.id for a in on})
        draw_nodes(ax, model, faded={n.id for n in model.nodes} - set(path.nodes), node_size=SMALL_NODE_SIZE)
        finish_map(ax, model, axis_labels=False)
        ax.set_title(
            f"{path.label}\n{path.flow} MW · {path.total_cost:,.0f} € · {path.unit_cost:.2f} €/MWh",
            fontsize=9, color=INK,
        )

    for ax in axes.flat[len(paths):]:
        ax.axis("off")
    fig.suptitle(_title(model, result), fontsize=11)
    fig.tight_layout()
    return fig


def draw_path_costs(model: NetworkModel, result: SolutionResult):
    """Horizontal stacked bars: supply + transport €/MWh per path, cheapest first."""
    _check_drawable(result)
    paths = sorted(result.paths, key=lambda p: p.unit_cost)
    supply_unit = np.array([p.supply_cost / p.flow for p in paths])
    transport_unit = np.array([p.transport_cost / p.flow for p in paths])
    y = np.arange(len(paths))

    fig, ax = plt.subplots(figsize=(11, 0.55 * len(paths) + 1.8))
    bar = dict(height=0.6, edgecolor=SURFACE, linewidth=2)
    ax.barh(y, supply_unit, color=BLUE, label="supply €/MWh", **bar)
    ax.barh(y, transport_unit, left=supply_unit, color=AQUA, label="transport €/MWh", **bar)
    for i, p in enumerate(paths):
        ax.text(p.unit_cost + 1, i, f"{p.unit_cost:.2f} €/MWh · {p.flow} MW",
                va="center", fontsize=8, color=INK, zorder=3,
                bbox=dict(boxstyle="round,pad=0.15", fc=SURFACE, ec="none"))
    ax.axvline(result.unit_cost, color=MUTED, lw=1, ls=":",
               label=f"average {result.unit_cost:.2f} €/MWh")

    ax.set_yticks(y, [p.label for p in paths], fontsize=9, color=INK)
    ax.invert_yaxis()
    ax.set_xlim(0, max(p.unit_cost for p in paths) * 1.25)
    ax.set_xlabel("€/MWh delivered", color=MUTED)
    ax.tick_params(axis="x", colors=MUTED)
    ax.tick_params(axis="y", length=0)
    ax.grid(axis="x", color=GRID, lw=0.8)
    ax.set_axisbelow(True)
    for side, spine in ax.spines.items():
        spine.set_visible(side == "bottom")
        spine.set_color(BASELINE)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.15), ncol=3, frameon=False, fontsize=8)
    ax.set_title(f"{model.name}: cost per path", color=INK)
    fig.tight_layout()
    return fig


def main():
    parser = argparse.ArgumentParser(description="Solve a network model and draw the solution.")
    parser.add_argument("model", help="model JSON file")
    parser.add_argument("-o", "--out-dir", default="output")
    parser.add_argument("--segments", type=int, default=10)
    parser.add_argument("--show", action="store_true", help="also open the figures in a window")
    args = parser.parse_args()

    model = load_model(args.model)
    result = MinCostRouteSolver(num_segments=args.segments).solve(model)
    print(result.summary())
    if result.status is SolveStatus.ERROR:
        raise SystemExit(1)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    figures = {
        "solution_map.png": draw_solution(model, result).figure,
        "solution_paths.png": draw_paths(model, result),
        "path_costs.png": draw_path_costs(model, result),
    }
    print()
    for name, fig in figures.items():
        fig.savefig(out_dir / name, dpi=150, bbox_inches="tight")
        print(f"Saved {out_dir / name}")

    if args.show:
        plt.show()


if __name__ == "__main__":
    main()
