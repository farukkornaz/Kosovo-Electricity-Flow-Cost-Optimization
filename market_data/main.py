"""Crawl daily capacity auctions (JAO, SEECAO) and hourly spot prices into the market database.

    python main.py --from 2026-09-01 [--to 2026-09-30] [--refresh] [--db PATH] [--price-api URL]

Only auctions between network.COUNTRIES are stored. What is already in the database
is skipped unless --refresh is given, so an interrupted backfill resumes where it
stopped. When the price API is down, spot prices are skipped with a warning and the
auctions are still crawled.
"""

import argparse
import urllib.error
from datetime import date, timedelta
from pathlib import Path

import db
import network
import spot_prices
from jao import crawler as jao
from seecao import crawler as seecao


def crawl_auctions(conn, day: date, refresh: bool) -> str:
    """Store one delivery day's modeled auctions; returns a one-line summary."""
    parts = []
    for source, statuses in (("JAO", _jao_day(conn, day, refresh)), ("SEECAO", _seecao_day(conn, day, refresh))):
        statuses = list(statuses)
        skipped = statuses.count("skipped")
        parts.append(f"{source} {statuses.count('saved')}" + (f" (+{skipped} already stored)" if skipped else ""))
    return ", ".join(parts)


def _jao_day(conn, day: date, refresh: bool):
    for auction in jao.list_daily_auctions(day):
        if not network.is_modeled(*jao.areas(auction)):
            continue
        auction_id = auction["identification"]
        if not refresh and db.has_auction(conn, jao.SOURCE, auction_id):
            yield "skipped"
            continue
        db.save_auction(conn, *jao.to_rows(auction, jao.fetch_bids(auction_id)))
        yield "saved"


def _seecao_day(conn, day: date, refresh: bool):
    for auction_id in seecao.list_daily_auctions(day):
        if not refresh and db.has_auction(conn, seecao.SOURCE, auction_id):
            yield "skipped"
            continue
        rows = seecao.to_rows(seecao.fetch_auction(auction_id))
        if rows is None or not network.is_modeled(rows[0]["out_area"], rows[0]["in_area"]):
            continue
        db.save_auction(conn, *rows)
        yield "saved"


def crawl_spot_prices(conn, start: date, end: date, refresh: bool, api_url: str) -> None:
    stored = set() if refresh else db.spot_price_days(conn, spot_prices.SOURCE, start, end)
    missing = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    missing = [day for day in missing if day not in stored]
    if not missing:
        print(f"Spot prices: all {len(stored)} days already stored")
        return
    if not spot_prices.is_up(api_url):
        print(f"WARNING: price API at {api_url} is down, spot prices skipped. "
              "Start it in ~/lab/south-europe-energy-prices with `.venv/bin/python api.py` and re-run.")
        return
    try:
        rows = spot_prices.fetch_hourly(missing[0], missing[-1], api_url=api_url)
    except urllib.error.URLError as exc:
        print(f"WARNING: price API failed ({exc}), spot prices skipped")
        return
    db.save_spot_prices(conn, rows)
    found = {row["zone"] for row in rows}
    no_data = sorted(set(spot_prices.ZONES) - found)
    print(f"Spot prices: {len(rows)} hourly prices for {len(missing)} days"
          + (f", no data for {', '.join(no_data)}" if no_data else ""))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--from", "--date", dest="start", required=True, type=date.fromisoformat,
                        help="first delivery day (CET), YYYY-MM-DD")
    parser.add_argument("--to", dest="end", type=date.fromisoformat, help="last delivery day, inclusive (default: --from)")
    parser.add_argument("--refresh", action="store_true", help="re-download what is already stored")
    parser.add_argument("--db", type=Path, default=db.DEFAULT_PATH, help=f"SQLite file (default: {db.DEFAULT_PATH})")
    parser.add_argument("--price-api", default=spot_prices.API_URL, help=f"price API (default: {spot_prices.API_URL})")
    args = parser.parse_args()
    end = args.end or args.start
    if end < args.start:
        parser.error("--to is before --from")

    conn = db.connect(args.db)
    crawl_spot_prices(conn, args.start, end, args.refresh, args.price_api)
    day = args.start
    while day <= end:
        print(f"{day}: {crawl_auctions(conn, day, args.refresh)}", flush=True)
        day += timedelta(days=1)
    conn.close()
    print(f"Saved {args.db}")


if __name__ == "__main__":
    main()
