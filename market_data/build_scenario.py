"""Build a single-hour CostOptimizationProgram scenario (Kosovo demand) from the market database.

    python build_scenario.py --date 2026-09-01 --timetable 14:00-15:00 [--demand 400] [--seed 42]

Every border in network.BORDERS becomes two arcs, one per direction. A direction is
open when the database holds a result for that hour: its linear price curve is fitted
to that hour's bids, or is flat at the clearing price when there are none. Otherwise
its capacity is 0. When both a platform and a MANUAL import cover a direction, the
platform wins. Supply prices are that hour's spot prices (ENTSOE before MANUAL);
zones without one get a random placeholder. A report lists what was used.
"""

import argparse
import json
import random
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import psycopg

import db
import network

HERE = Path(__file__).parent
PLACEHOLDER_PRICE_RANGE = (200.0, 300.0)  # for zones without spot prices (BA, TR)


@dataclass
class Report:
    """What build_scenario used, so missing data never goes unnoticed."""

    open: list[str] = field(default_factory=list)            # 'MK->XK SEECAO'
    flat: list[str] = field(default_factory=list)            # open, but no bids to fit a slope
    closed: list[str] = field(default_factory=list)          # border without a known daily auction
    missing: list[str] = field(default_factory=list)         # expected data not in the database
    overridden: list[str] = field(default_factory=list)      # MANUAL rows a platform replaced
    placeholder_prices: list[str] = field(default_factory=list)

    def lines(self) -> list[str]:
        sections = [
            ("Open", self.open),
            ("Open with flat curve (no bids)", self.flat),
            ("Closed, no daily auction known", self.closed),
            ("WARNING closed, expected data missing", self.missing),
            ("MANUAL ignored, platform data used", self.overridden),
            ("WARNING random placeholder spot price", self.placeholder_prices),
        ]
        return [f"{title}: {', '.join(items)}" for title, items in sections if items]


def fit_linear_curve(bids: list, capacity: int, clearing_price: float) -> dict:
    """Linear P(q) for buying q MW with a bid priced to win.

    Our q MW is accepted first, so the other bidders share capacity - q, and the
    pay-as-clear price is the bid at which their cumulative demand reaches that.
    base_price is the published clearing price (q = 0); slope is the least-squares
    fit of the resulting step curve over q = 0..capacity, clipped at 0. Without
    bids the slope is 0.
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


CLOSED_CURVE = {"type": "linear", "base_price": 0.0, "slope": 0.0, "capacity": 0}


def load_results(conn: psycopg.Connection, day: date, timetable: str) -> dict[tuple[str, str], list[tuple]]:
    """That hour's results between modeled countries, per direction: (source, auction_ref, hour, capacity, price, cancelled)."""
    rows = conn.execute(
        """SELECT a.out_area, a.in_area, a.source, r.auction_ref, r.hour,
                  r.offered_capacity_mw, r.clearing_price_eur_mwh, r.cancelled
           FROM results r JOIN auctions a ON a.id = r.auction_ref
           WHERE a.delivery_date = %s AND r.timetable = %s""",
        (day, timetable),
    ).fetchall()
    by_direction = {}
    for out_area, in_area, *rest in rows:
        if not network.is_modeled(out_area, in_area):
            continue
        if network.border_of(out_area, in_area) is None:
            raise ValueError(f"{out_area}-{in_area} has data but is not in network.BORDERS: add it there first")
        by_direction.setdefault((out_area, in_area), []).append(tuple(rest))
    hours = {row[2] for rows in by_direction.values() for row in rows}
    if len(hours) > 1:
        raise ValueError(f"{timetable} matches hours {sorted(hours)} on {day} (clock change day)")
    return by_direction


def choose_result(direction: str, rows: list[tuple], report: Report) -> tuple:
    """One result per direction: platform data over MANUAL, a re-run over the auction it replaced."""
    platform = [row for row in rows if row[0] != db.MANUAL]
    live = [row for row in platform if not row[5]]
    if len(live) > 1:
        raise ValueError(f"{direction} has more than one uncancelled platform auction: {sorted(row[0] for row in live)}")
    # A cancelled auction is usually re-run the same day (JAO HR-RS on 2026-08-17).
    platform = live or platform[:1]
    if platform and len(rows) > len(platform):
        report.overridden.append(f"{direction} ({platform[0][0]})")
    return (platform or rows)[0]


def build_arcs(conn: psycopg.Connection, day: date, timetable: str, report: Report) -> list[dict]:
    results = load_results(conn, day, timetable)
    arcs = []
    for (a, b), expected in sorted(network.BORDERS.items()):
        unused = []
        for out_area, in_area in ((a, b), (b, a)):
            direction = f"{out_area}->{in_area}"
            arc = {"from": out_area, "to": in_area, "curve": CLOSED_CURVE}
            arcs.append(arc)
            rows = results.get((out_area, in_area))
            if not rows:
                unused.append(direction)
                continue
            source, auction_ref, hour, capacity, price, cancelled = choose_result(direction, rows, report)
            if cancelled or capacity is None or price is None:
                report.missing.append(f"{direction} ({source}: cancelled or no capacity/price)")
                continue
            bids = conn.execute(
                "SELECT quantity_mw, price_eur_mwh FROM bids WHERE auction_ref = %s AND hour = %s",
                (auction_ref, hour),
            ).fetchall()
            arc["curve"] = fit_linear_curve(bids, int(capacity), price)
            (report.open if bids else report.flat).append(f"{direction} {source}")
        if expected is None:
            report.closed += [f"{a}-{b}"] if len(unused) == 2 else unused
        else:
            report.missing += [f"{direction} ({expected})" for direction in unused]
    return arcs


def load_spot_prices(conn: psycopg.Connection, day: date, timetable: str) -> dict[str, float]:
    """Zone -> that hour's spot price, ENTSOE before MANUAL."""
    rows = conn.execute(
        "SELECT zone, source, price_eur_mwh FROM spot_prices WHERE delivery_date = %s AND timetable = %s",
        (day, timetable),
    ).fetchall()
    prices = {}
    for zone, source, price in sorted(rows, key=lambda row: row[1] == db.MANUAL, reverse=True):
        prices[zone] = price  # MANUAL rows sort first, so platform prices overwrite them
    return prices


def build_scenario(conn: psycopg.Connection, day: date, timetable: str, demand: int, seed: int) -> tuple[dict, Report]:
    rng = random.Random(seed)
    report = Report()
    spot = load_spot_prices(conn, day, timetable)
    nodes = []
    for node_id, (name, lat, lon, max_supply) in network.COUNTRIES.items():
        node = {"id": node_id, "name": name, "lat": lat, "lon": lon}
        if node_id == network.DEMAND_NODE:
            node |= {"type": "demand", "demand": demand}
        else:
            if node_id not in spot:
                report.placeholder_prices.append(node_id)
            price = spot[node_id] if node_id in spot else rng.uniform(*PLACEHOLDER_PRICE_RANGE)
            node |= {"type": "supply", "max_supply": max_supply, "unit_price": round(price, 2)}
        nodes.append(node)

    arcs = build_arcs(conn, day, timetable, report)
    name = f"scenario-xk-demand-{day:%Y%m%d}-{timetable[:5].replace(':', '')}"
    return {"name": name, "nodes": nodes, "arcs": arcs}, report


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
    parser.add_argument("--db", help="PostgreSQL URL (default: DATABASE_URL or the credentials in .env)")
    parser.add_argument("-o", "--output", type=Path, help="default: data/scenario_xk_demand_<date>_<hhmm>.json")
    args = parser.parse_args()

    conn = db.connect(args.db, create=False)
    scenario, report = build_scenario(conn, args.date, args.timetable, args.demand, args.seed)
    conn.close()
    output = args.output or HERE / "data" / f"scenario_xk_demand_{args.date:%Y%m%d}_{args.timetable[:5].replace(':', '')}.json"
    output.parent.mkdir(exist_ok=True)
    output.write_text(dumps(scenario), encoding="utf-8")
    print(f"Saved {output}: {len(scenario['nodes'])} nodes, {len(scenario['arcs'])} arcs")
    print("\n".join(report.lines()))


if __name__ == "__main__":
    main()
