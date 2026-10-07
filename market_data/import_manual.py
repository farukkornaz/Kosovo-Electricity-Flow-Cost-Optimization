"""Import hand-collected data the crawlers can't fetch: auction results, bids and spot prices.

    python import_manual.py [FILE.csv ...] [--db URL]

Without FILEs every CSV in manual/ is imported. Keep the files there and commit them:
the database is rebuilt by crawling (main.py) and then re-running this script.
The file kind follows from its header (any column order; [...] = optional):

    results: border,delivery_date,timetable,offered_capacity_mw,clearing_price_eur_mwh
             [,requested_capacity_mw,allocated_capacity_mw,participants,awarded_participants]
    bids:    border,delivery_date,timetable,quantity_mw,price_eur_mwh
    spot:    zone,delivery_date,timetable,price_eur_mwh

border is '<out_area>-<in_area>' (e.g. BA-RS) and must be in network.BORDERS; zone must
be in network.COUNTRIES. timetable is CET/CEST like '14:00-15:00', or '*' for every hour
of the day. Rows are stored with source 'MANUAL', as one auction per border direction
and day, so re-importing a border's day replaces it. Bids need a results row for
their hour; without bids the scenario uses a flat price curve.
"""

import argparse
import csv
from datetime import date
from pathlib import Path

import db
import network
from common import day_hours

MANUAL_DIR = Path(__file__).parent / "manual"
REQUIRED = {
    "results": {"border", "delivery_date", "timetable", "offered_capacity_mw", "clearing_price_eur_mwh"},
    "bids": {"border", "delivery_date", "timetable", "quantity_mw", "price_eur_mwh"},
    "spot": {"zone", "delivery_date", "timetable", "price_eur_mwh"},
}
OPTIONAL_RESULT_COLUMNS = ["requested_capacity_mw", "allocated_capacity_mw", "participants", "awarded_participants"]


def read_csv(path: Path) -> tuple[str, list[dict]]:
    """(kind, rows) of one file; each row remembers its file and line for error messages."""
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        columns = {c.strip() for c in reader.fieldnames or ()}
        kinds = [kind for kind, required in REQUIRED.items() if required <= columns]
        if len(kinds) != 1:
            raise ValueError(f"{path}: header {sorted(columns)} is not a results, bids or spot file")
        rows = [
            {"_where": f"{path.name}:{reader.line_num}", **{k.strip(): (v or "").strip() for k, v in row.items()}}
            for row in reader
        ]
    return kinds[0], rows


def _hours(row: dict) -> list[dict]:
    """hour_columns of the row's timetable ('*' = every hour of its day)."""
    hours = day_hours(date.fromisoformat(row["delivery_date"]))
    if row["timetable"] == "*":
        return hours
    matches = [h for h in hours if h["timetable"] == row["timetable"]]
    if len(matches) != 1:
        raise ValueError(f"{row['_where']}: timetable {row['timetable']!r} matches {len(matches)} hours of the day")
    return matches


def _border(row: dict) -> tuple[str, str]:
    out_area, _, in_area = row["border"].partition("-")
    if network.border_of(out_area, in_area) is None:
        raise ValueError(f"{row['_where']}: border {row['border']!r} is not in network.BORDERS")
    return out_area, in_area


def _number(row: dict, column: str, required: bool = True) -> float | None:
    if not row.get(column):
        if required:
            raise ValueError(f"{row['_where']}: {column} is empty")
        return None
    return float(row[column])


def to_auctions(result_rows: list[dict], bid_rows: list[dict]) -> list[tuple[dict, list, list]]:
    """Group results and bids into (auction, results, bids), one auction per border direction and day."""
    auctions = {}

    def auction_for(row):
        out_area, in_area = _border(row)
        key = (out_area, in_area, row["delivery_date"])
        if key not in auctions:
            auction = {
                "source": db.MANUAL,
                "auction_id": f"MANUAL-{out_area}-{in_area}-{row['delivery_date']}",
                "corridor": f"{out_area}-{in_area}",
                "out_area": out_area,
                "in_area": in_area,
                "delivery_date": row["delivery_date"],
            }
            auctions[key] = (auction, {}, [])
        return auctions[key]

    for row in result_rows:
        _, results, _ = auction_for(row)
        for hour in _hours(row):
            if hour["hour"] in results:
                raise ValueError(f"{row['_where']}: {row['border']} {hour['timetable']} given twice")
            results[hour["hour"]] = {
                **hour,
                "offered_capacity_mw": _number(row, "offered_capacity_mw"),
                "clearing_price_eur_mwh": _number(row, "clearing_price_eur_mwh"),
                **{column: _number(row, column, required=False) for column in OPTIONAL_RESULT_COLUMNS},
                "comment": None,
                "cancelled": False,
            }
    for row in bid_rows:
        _, results, bids = auction_for(row)
        for hour in _hours(row):
            if hour["hour"] not in results:
                raise ValueError(f"{row['_where']}: bids for {row['border']} {hour['timetable']} have no results row")
            bids.append({
                "hour": hour["hour"],
                "quantity_mw": _number(row, "quantity_mw"),
                "price_eur_mwh": _number(row, "price_eur_mwh"),
                "awarded_quantity_mw": None,
            })
    return [(auction, sorted(results.values(), key=lambda r: r["hour"]), bids)
            for auction, results, bids in auctions.values()]


def to_spot_prices(rows: list[dict]) -> list[dict]:
    spot = []
    for row in rows:
        if row["zone"] not in network.COUNTRIES:
            raise ValueError(f"{row['_where']}: zone {row['zone']!r} is not in network.COUNTRIES")
        for hour in _hours(row):
            spot.append({
                "source": db.MANUAL,
                "zone": row["zone"],
                "delivery_date": row["delivery_date"],
                **hour,
                "price_eur_mwh": _number(row, "price_eur_mwh"),
            })
    return spot


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("files", nargs="*", type=Path, help=f"CSV files (default: every CSV in {MANUAL_DIR.name}/)")
    parser.add_argument("--db", help="PostgreSQL URL (default: DATABASE_URL or the credentials in .env)")
    args = parser.parse_args()

    files = args.files or sorted(MANUAL_DIR.glob("*.csv"))
    rows = {kind: [] for kind in REQUIRED}
    for path in files:
        kind, file_rows = read_csv(path)
        rows[kind] += file_rows
        print(f"{path}: {len(file_rows)} {kind} rows")
    # Validate everything before writing anything.
    auctions = to_auctions(rows["results"], rows["bids"])
    spot = to_spot_prices(rows["spot"])

    conn = db.connect(args.db)
    for auction, results, bids in auctions:
        db.save_auction(conn, auction, results, bids)
    db.save_spot_prices(conn, spot)
    print(f"Saved to {db.describe(conn)}: {len(auctions)} manual auctions, {len(spot)} manual spot prices")
    conn.close()


if __name__ == "__main__":
    main()
