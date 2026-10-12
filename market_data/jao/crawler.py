"""JAO daily explicit auctions: discover a delivery day's auctions and map them to DB rows."""

import re
import urllib.error
from datetime import date, timedelta

from common import USER_AGENT, auction_row, delivery_day, fetch_json, hours_by_clock_end, parse_utc

SOURCE = "JAO"
API_URL = "https://www.jao.eu/api/v1/auction/calls"

HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json",
    "Origin": "https://www.jao.eu",
    "Referer": "https://www.jao.eu/auctions",
    "User-Agent": USER_AGENT,
}


def list_daily_auctions(day: date) -> list:
    """Daily auctions (all corridors) delivering on `day`, with their results embedded.

    JAO filters on the UTC market period start, which for a CET/CEST day falls on the
    previous UTC date; it answers 400 "No Data found" when nothing matches.
    """
    body = {"fromdate": (day - timedelta(days=1)).isoformat(), "todate": day.isoformat(), "horizon": "Daily"}
    try:
        auctions = fetch_json(f"{API_URL}/getauctions", HEADERS, body)
    except urllib.error.HTTPError as exc:
        if exc.code == 400 and b"No Data found" in exc.read():
            return []
        raise
    return [a for a in auctions if delivery_day(parse_utc(a["marketPeriodStart"])) == day.isoformat()]


def fetch_bids(auction_id: str) -> list:
    return fetch_json(f"{API_URL}/getbids", HEADERS, {"auctionid": auction_id})


def areas(auction: dict) -> tuple[str, str]:
    """(out_area, in_area) of a `getauctions` entry: 'IF1-FR-GB' -> ('FR', 'GB')."""
    *_, out_area, in_area = auction["corridorCode"].split("-")
    return out_area, in_area


def to_rows(auction: dict, bids: list) -> tuple[dict, list, list]:
    """Map a `getauctions` entry and its `getbids` list to (auction, results, bids) rows."""
    start = parse_utc(auction["marketPeriodStart"])
    auction_cols = auction_row(SOURCE, auction["identification"], auction["corridorCode"], *areas(auction), start)
    day = date.fromisoformat(auction_cols["delivery_date"])
    hours = hours_by_clock_end(day)

    def hour_of(product_identification: str) -> dict:
        """Products are named by the clock hour they end at: 'B07-------' is 06:00-07:00.
        The 25-hour day repeats 02:00-03:00 as 'B03' then 'B03DST'; the 23-hour day has no 'B03'."""
        match = re.fullmatch(r"B(\d{2})(DST)?-*", product_identification)
        key = (int(match[1]), match[2] is not None) if match else None
        if key not in hours:
            raise ValueError(f"{auction['identification']}: product {product_identification} is not an hour of {day}")
        return hours[key]

    # Participant counts live on `products`; capacities and price on `results`.
    products = {p["productIdentification"]: p for p in auction["products"]}
    result_rows = []
    for result in auction["results"]:
        product = products[result["productIdentification"]]
        comment = "; ".join(filter(None, (result["comment"], result["additionalMessage"])))
        result_rows.append({
            **hour_of(result["productIdentification"]),
            "offered_capacity_mw": result["offeredCapacity"],
            "requested_capacity_mw": result["requestedCapacity"],
            "allocated_capacity_mw": result["allocatedCapacity"],
            "clearing_price_eur_mwh": result["auctionPrice"],
            "participants": product["bidderPartyCount"],
            "awarded_participants": product["winnerPartyCount"],
            "comment": comment or None,
            "cancelled": bool(auction["cancelled"]),
        })

    bid_rows = []
    for bid in bids:
        # A bid covers every hour of the day; hours it leaves empty come back as 0 MW rows.
        if bid["quantity"] == 0:
            continue
        if bid["currency"] != "EUR":
            raise ValueError(f"{auction['identification']}: unexpected currency {bid['currency']}")
        bid_rows.append({
            "hour": hour_of(bid["productIdentification"])["hour"],
            "quantity_mw": bid["quantity"],
            "price_eur_mwh": bid["price"],
            "awarded_quantity_mw": bid["awardedQuantity"],
        })
    return auction_cols, sorted(result_rows, key=lambda r: r["hour"]), bid_rows
