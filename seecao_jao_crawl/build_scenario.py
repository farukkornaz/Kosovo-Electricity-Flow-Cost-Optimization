"""Build a single-hour CostOptimizationProgram scenario (Kosovo demand) from auctions.db.

    python build_scenario.py --date 2026-09-01 --timetable 14:00-15:00 [--demand 400] [--seed 42]

Every auctioned border direction between COUNTRIES becomes an arc whose linear price
curve is fitted to that hour's bids. Borders without an explicit daily auction are
kept as closed arcs (capacity 0). Supply prices are that hour's spot prices; zones
the price API doesn't cover get a random placeholder.
"""

import argparse
import json
import random
import sqlite3
from datetime import date
from pathlib import Path

HERE = Path(__file__).parent

# id: (name, lat, lon, max_supply MW); coordinates and supplies as in
# CostOptimizationProgram/data/scenario_xk_demand.json.
COUNTRIES = {
    "XK": ("Kosovo", 42.6, 20.9, None),
    "AL": ("Albania", 41.1, 20.0, 300),
    "MK": ("North Macedonia", 41.6, 21.7, 200),
    "ME": ("Montenegro", 42.7, 19.3, 200),
    "RS": ("Serbia", 44.0, 21.6, 700),
    "BA": ("Bosnia", 44.2, 17.8, 500),
    "BG": ("Bulgaria", 42.7, 25.3, 800),
    "GR": ("Greece", 39.1, 21.8, 600),
    "RO": ("Romania", 45.9, 25.0, 900),
    "HU": ("Hungary", 47.2, 19.4, 800),
    "HR": ("Croatia", 45.6, 16.2, 600),
    "TR": ("Türkiye", 40.9, 29.0, 800),
}
DEMAND_NODE = "XK"
# No explicit daily auction on JAO/SEECAO (AL-XK: implicit; RO: market coupled).
CLOSED_BORDERS = [("AL", "XK"), ("RO", "RS"), ("RO", "HU"), ("RO", "BG")]
PLACEHOLDER_PRICE_RANGE = (200.0, 300.0)  # for zones without spot prices (BA, TR)


def fit_linear_curve(bids: list, capacity: int, clearing_price: float) -> dict:
    """Linear P(q) for buying q MW with a bid priced to win.

    Our q MW is accepted first, so the other bidders share capacity - q, and the
    pay-as-clear price is the bid at which their cumulative demand reaches that.
    base_price is the published clearing price (q = 0); slope is the least-squares
    fit of the resulting step curve over q = 0..capacity, clipped at 0.
    """
    bids = sorted(bids, key=lambda bid: -bid[1])

    def price_left_for_others(residual: int) -> float:
        cumulative = 0.0
        for quantity, price in bids:
            cumulative += quantity
            if cumulative >= residual:
                return price
        return 0.0  # undersubscribed

    quantities = range(capacity + 1)
    num = sum(q * (price_left_for_others(capacity - q) - clearing_price) for q in quantities)
    den = sum(q * q for q in quantities)
    slope = max(num / den, 0.0) if den else 0.0
    return {"type": "linear", "base_price": round(clearing_price, 2), "slope": round(slope, 6), "capacity": capacity}


def load_spot_prices(conn: sqlite3.Connection, day: date, timetable: str) -> dict[str, float]:
    return dict(conn.execute(
        "SELECT zone, price_eur_mwh FROM spot_prices WHERE delivery_date = ? AND timetable = ?",
        (day.isoformat(), timetable),
    ).fetchall())


def build_scenario(conn: sqlite3.Connection, day: date, timetable: str, demand: int, seed: int) -> dict:
    rng = random.Random(seed)
    spot = load_spot_prices(conn, day, timetable)
    nodes = []
    for node_id, (name, lat, lon, max_supply) in COUNTRIES.items():
        node = {"id": node_id, "name": name, "lat": lat, "lon": lon}
        if node_id == DEMAND_NODE:
            node |= {"type": "demand", "demand": demand}
        else:
            price = spot[node_id] if node_id in spot else rng.uniform(*PLACEHOLDER_PRICE_RANGE)
            node |= {"type": "supply", "max_supply": max_supply, "unit_price": round(price, 2)}
        nodes.append(node)

    curves = {}
    results = conn.execute(
        """SELECT source, auction_id, hour, out_area, in_area, offered_capacity_mw, clearing_price_eur_mwh
           FROM results WHERE delivery_date = ? AND timetable = ?""",
        (day.isoformat(), timetable),
    ).fetchall()
    for source, auction_id, hour, out_area, in_area, capacity, price in results:
        if out_area not in COUNTRIES or in_area not in COUNTRIES:
            continue
        if (out_area, in_area) in curves:
            raise ValueError(f"{out_area}->{in_area} auctioned by more than one platform")
        bids = conn.execute(
            "SELECT quantity_mw, price_eur_mwh FROM bids WHERE source = ? AND auction_id = ? AND hour = ?",
            (source, auction_id, hour),
        ).fetchall()
        curves[(out_area, in_area)] = fit_linear_curve(bids, int(capacity), price)
    for a, b in CLOSED_BORDERS:
        for pair in ((a, b), (b, a)):
            curves[pair] = {"type": "linear", "base_price": 0.0, "slope": 0.0, "capacity": 0}

    # List both directions of a border next to each other.
    order = sorted(curves, key=lambda pair: (sorted(pair), pair))
    arcs = [{"from": a, "to": b, "curve": curves[(a, b)]} for a, b in order]
    name = f"scenario-xk-demand-{day:%Y%m%d}-{timetable[:5].replace(':', '')}"
    return {"name": name, "nodes": nodes, "arcs": arcs}


def dumps(scenario: dict) -> str:
    """JSON with one node/arc per line, matching the hand-written scenario files."""
    nodes = ",\n".join(f"    {json.dumps(n, ensure_ascii=False)}" for n in scenario["nodes"])
    arcs = ",\n".join(f"    {json.dumps(a, ensure_ascii=False)}" for a in scenario["arcs"])
    return f'{{\n  "name": {json.dumps(scenario["name"])},\n  "nodes": [\n{nodes}\n  ],\n  "arcs": [\n{arcs}\n  ]\n}}\n'


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--date", required=True, type=date.fromisoformat, help="delivery day (CET), YYYY-MM-DD")
    parser.add_argument("--timetable", required=True, help="product hour (CET), e.g. 14:00-15:00")
    parser.add_argument("--demand", type=int, default=400, help="Kosovo demand in MW (default: 400)")
    parser.add_argument("--seed", type=int, default=42, help="seed for placeholder prices of zones without spot prices")
    parser.add_argument("--db", type=Path, default=HERE / "auctions.db")
    parser.add_argument("-o", "--output", type=Path, help="default: data/scenario_xk_demand_<date>_<hhmm>.json")
    args = parser.parse_args()

    with sqlite3.connect(args.db) as conn:
        scenario = build_scenario(conn, args.date, args.timetable, args.demand, args.seed)
        missing = [c for c in COUNTRIES if c != DEMAND_NODE and c not in load_spot_prices(conn, args.date, args.timetable)]
    output = args.output or HERE / "data" / f"scenario_xk_demand_{args.date:%Y%m%d}_{args.timetable[:5].replace(':', '')}.json"
    output.parent.mkdir(exist_ok=True)
    output.write_text(dumps(scenario), encoding="utf-8")
    print(f"Saved {output}: {len(scenario['nodes'])} nodes, {len(scenario['arcs'])} arcs")
    if missing:
        print(f"No spot price for {', '.join(missing)}: random placeholder used")


if __name__ == "__main__":
    main()
