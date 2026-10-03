"""SEECAO daily explicit auctions: discover a delivery day's auctions and map them to DB rows."""

import urllib.parse
from datetime import date

from common import USER_AGENT, auction_columns, fetch_json, hour_columns, parse_utc

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
    config = fetch_json(f"{API_URL}/config", HEADERS)
    auction_ids = []
    for direction in config["dropdown"]:
        query = {"type": "daily", "outArea": direction["valueOut"], "inArea": direction["valueIn"], "day": day.isoformat()}
        auction_ids += fetch_json(f"{API_URL}/data/filter?{urllib.parse.urlencode(query)}", HEADERS)["auctions"]
    return auction_ids


def fetch_auction(auction_id: str) -> dict:
    query = urllib.parse.urlencode({"auctionIdentification": auction_id})
    return fetch_json(f"{API_URL}/data?{query}", HEADERS)["auctionData"]


def to_rows(auction: dict) -> tuple[list, list]:
    """Map an `auctionData` payload to (results, bids) rows."""
    if not auction["table"]:
        return [], []
    out_area, in_area = (part.strip() for part in auction["table"][0]["border"].split("-"))
    start = parse_utc(auction["deliveryPeriodStart"])
    base = auction_columns(SOURCE, auction["auctionIdentification"], f"{out_area}-{in_area}", out_area, in_area, start)

    result_rows = [
        {
            **base,
            **hour_columns(start, result["pos"], result["timetable"]),
            "offered_capacity_mw": _number(result["offered"]),
            "requested_capacity_mw": _number(result["requested"]),
            "allocated_capacity_mw": _number(result["allocated"]),
            "clearing_price_eur_mwh": _number(result["price"]),
            "congestion_income_eur": None if result["income"] is None else round(result["income"], 2),
            "participants": result["numberOfParticipants"],
            "awarded_participants": result["numberOfSuccessfullParticipants"],
            "bid_count": result["numberOfAuctionBids"],
            "comment": None,
            "cancelled": int(result["cancelled"]),
        }
        for result in auction["table"]
    ]

    # Each hour's bids come as a cumulative demand curve: prices descending, `capacity`
    # the running total. Differencing consecutive points recovers the individual bids.
    bid_rows = []
    for product in auction["bids"]:
        hour_cols = hour_columns(start, product["position"] + 1, product["title"])
        cumulative = 0
        for point in product["line"]:
            quantity = point["capacity"] - cumulative
            cumulative = point["capacity"]
            if quantity == 0:
                continue
            bid_rows.append({
                **base,
                **hour_cols,
                "quantity_mw": quantity,
                "price_eur_mwh": float(point["price"]),
                "awarded_quantity_mw": None,
            })
    return result_rows, bid_rows


def _number(value) -> float | None:
    """SEECAO sends numbers as strings ('295.00') and uses '--' for not applicable."""
    if value in (None, "", "--"):
        return None
    return float(value)
