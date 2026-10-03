"""Crawl one delivery day's daily capacity auctions from JAO and SEECAO into SQLite.

    python main.py --date 2026-09-01 [--db auctions.db]
"""

import argparse
from datetime import date
from pathlib import Path

import db
from jao import crawler as jao
from seecao import crawler as seecao

DEFAULT_DB = Path(__file__).parent / "auctions.db"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--date", required=True, type=date.fromisoformat, help="delivery day (CET), YYYY-MM-DD")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help=f"SQLite file (default: {DEFAULT_DB.name})")
    args = parser.parse_args()

    conn = db.connect(args.db)

    jao_auctions = jao.list_daily_auctions(args.date)
    print(f"JAO: {len(jao_auctions)} daily auctions")
    for auction in jao_auctions:
        auction_id = auction["identification"]
        results, bids = jao.to_rows(auction, jao.fetch_bids(auction_id))
        db.replace_auction(conn, jao.SOURCE, auction_id, results, bids)
        print(f"  {auction_id}: {len(results)} results, {len(bids)} bids")

    seecao_ids = seecao.list_daily_auctions(args.date)
    print(f"SEECAO: {len(seecao_ids)} daily auctions")
    for auction_id in seecao_ids:
        results, bids = seecao.to_rows(seecao.fetch_auction(auction_id))
        db.replace_auction(conn, seecao.SOURCE, auction_id, results, bids)
        print(f"  {auction_id}: {len(results)} results, {len(bids)} bids")

    conn.close()
    print(f"Saved {args.db}")


if __name__ == "__main__":
    main()
