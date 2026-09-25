"""End-to-end run: load model → draw model → solve → draw solution → save JSON.

    python main.py [model.json] [-o OUT_DIR] [--segments 10] [--show]

Outputs go to OUT_DIR (default: output/<model name>/), so scenarios don't overwrite each other.
"""
import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt

from costopt.data_loader import load_model
from costopt.map import draw_arc_curves, draw_model
from costopt.min_cost_route_solver import MinCostRouteSolver
from costopt.solution import SolutionResult, SolveStatus
from costopt.solution_map import draw_path_costs, draw_paths, draw_solution

DEFAULT_MODEL = Path(__file__).parent / "data" / "sample_network.json"


def run(model_path: str | Path, out_dir: str | Path | None = None, num_segments: int = 10,
        keep_figures: bool = False) -> SolutionResult:
    model = load_model(model_path)
    out_dir = Path(out_dir) if out_dir else Path(__file__).parent / "output" / model.name
    out_dir.mkdir(parents=True, exist_ok=True)
    print(model.summary(), end="\n\n")

    figures = {
        "model_map.png": draw_model(model).figure,
        "arc_curves.png": draw_arc_curves(model, num_segments),
    }
    result = MinCostRouteSolver(num_segments=num_segments).solve(model)
    print(result.summary(), end="\n\n")

    if result.status is not SolveStatus.ERROR:
        figures |= {
            "solution_map.png": draw_solution(model, result).figure,
            "solution_paths.png": draw_paths(model, result),
            "path_costs.png": draw_path_costs(model, result),
        }
        with open(out_dir / "solution.json", "w", encoding="utf-8") as f:
            json.dump(result.to_dict(), f, indent=2, ensure_ascii=False)
        print(f"Saved {out_dir / 'solution.json'}")

    for name, fig in figures.items():
        fig.savefig(out_dir / name, dpi=150, bbox_inches="tight")
        print(f"Saved {out_dir / name}")
        if not keep_figures:
            plt.close(fig)
    return result


def main():
    parser = argparse.ArgumentParser(description="Cross-border electricity min cost route: full run.")
    parser.add_argument("model", nargs="?", default=DEFAULT_MODEL, help="model JSON file")
    parser.add_argument("-o", "--out-dir", help="output folder (default: output/<model name>/)")
    parser.add_argument("--segments", type=int, default=10, help="price curve segments per arc")
    parser.add_argument("--show", action="store_true", help="also open the figures in windows")
    args = parser.parse_args()

    result = run(args.model, args.out_dir, args.segments, keep_figures=args.show)
    if args.show:
        plt.show()
    if result.status is SolveStatus.ERROR:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
