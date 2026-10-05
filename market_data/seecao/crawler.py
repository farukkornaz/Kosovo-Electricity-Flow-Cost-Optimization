"""SEECAO daily explicit auctions: discover a delivery day's auctions and map them to DB rows."""

import functools
import urllib.parse
from datetime import date

from common import USER_AGENT, auction_row, fetch_json, hour_columns, parse_utc

SOURCE = "SEECAO"
API_URL = "https://api.seecao.com/api"

HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Authorization": "Bearer false",
    "Origin": "https://seecao.com",
    "Referer": "https://seecao.com/auctions/",
    "User-Agent": USER_AGENT,
}


def list_daily_auctions(day: date) -> list[str]:
    """IDs of daily auctions delivering on `day`, across every border direction SEECAO serves.

    The filter endpoint only answers per direction, keyed by the areas' EIC codes.
    """
    auction_ids = []
    for direction in _directions():
        query = {"type": "daily", "outArea": direction["valueOut"], "inArea": direction["valueIn"], "day": day.isoformat()}
        auction_ids += fetch_json(f"{API_URL}/data/filter?{urllib.parse.urlencode(query)}", HEADERS)["auctions"]
    return auction_ids


@functools.cache
def _directions() -> tuple:
    """Border directions SEECAO serves; fetched once per run."""
    return tuple(fetch_json(f"{API_URL}/config", HEADERS)["dropdown"])


def fetch_auction(auction_id: str) -> dict:
    query = urllib.parse.urlencode({"auctionIdentification": auction_id})
    return fetch_json(f"{API_URL}/data?{query}", HEADERS)["auctionData"]


def to_rows(auction: dict) -> tuple[dict, list, list] | None:
    """Map an `auctionData` payload to (auction, results, bids) rows; None if it has no results."""
    if not auction["table"]:
        return None
    out_area, in_area = (part.strip() for part in auction["table"][0]["border"].split("-"))
    start = parse_utc(auction["deliveryPeriodStart"])
    auction_cols = auction_row(SOURCE, auction["auctionIdentification"], f"{out_area}-{in_area}", out_area, in_area, start)

    result_rows = [
        {
            **hour_columns(start, result["pos"], result["timetable"]),
            "offered_capacity_mw": _number(result["offered"]),
            "requested_capacity_mw": _number(result["requested"]),
            "allocated_capacity_mw": _number(result["allocated"]),
            "clearing_price_eur_mwh": _number(result["price"]),
            "participants": result["numberOfParticipants"],
            "awarded_participants": result["numberOfSuccessfullParticipants"],
            "comment": None,
            "cancelled": int(result["cancelled"]),
        }
        for result in auction["table"]
    ]

    # Each hour's bids come as a cumulative demand curve: prices descending, `capacity`
    # the running total. Differencing consecutive points recovers the individual bids
    # (the result's numberOfAuctionBids matches their count).
    bid_rows = []
    for product in auction["bids"]:
        hour = product["position"] + 1
        cumulative = 0
        for point in product["line"]:
            quantity = point["capacity"] - cumulative
            cumulative = point["capacity"]
            if quantity == 0:
                continue
            bid_rows.append({
                "hour": hour,
                "quantity_mw": quantity,
                "price_eur_mwh": float(point["price"]),
                "awarded_quantity_mw": None,
            })
    return auction_cols, result_rows, bid_rows


def _number(value) -> float | None:
    """SEECAO sends numbers as strings ('295.00') and uses '--' for not applicable."""
    if value in (None, "", "--"):
        return None
    return float(value)
