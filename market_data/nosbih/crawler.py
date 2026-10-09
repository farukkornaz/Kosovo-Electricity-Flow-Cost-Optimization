"""NOSBiH daily explicit auctions on the BA-RS border, which neither JAO nor SEECAO runs.

NOSBiH publishes results only, no bids. Its results page asks admin-ajax.php for a
delivery day's HTML table, whose download link points to an AuctionSummary XML that
covers both directions under one auction code. Rows are read from the XML: the HTML
table mislabels and drops hours on clock-change days (2025-10-26, 2026-03-29).
"""

import json
import re
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import date

from common import USER_AGENT, auction_row, delivery_day, fetch, hours_by_clock_end, parse_utc

SOURCE = "NOSBIH"
RESULTS_PAGE = "https://www.nosbih.ba/en/kapaciteti/rezultati-aukcija/"
AJAX_URL = "https://www.nosbih.ba/en/wp-admin/admin-ajax.php"
HEADERS = {"Referer": RESULTS_PAGE, "User-Agent": USER_AGENT}

# EIC codes used in the summary XML.
AREAS = {"10YBA-JPCC-----D": "BA", "10YCS-SERBIATSOV": "RS"}


def list_daily_auctions(day: date) -> list[str]:
    """URLs of the AuctionSummary XML files delivering on `day`; empty when nothing is published."""
    form = urllib.parse.urlencode({"action": "auction", "auction": f"date={day:%d.%m.%Y.}"}).encode()
    payload = json.loads(fetch(AJAX_URL, HEADERS, form))
    if not payload.get("success"):
        raise RuntimeError(f"NOSBiH results query for {day} failed: {payload.get('data')!r}")
    links = re.findall(r'href="([^"]+\.xml)"', payload["data"])
    return [urllib.parse.urljoin(RESULTS_PAGE, link) for link in links]


def fetch_auction(url: str) -> ET.Element:
    return ET.fromstring(fetch(url, HEADERS))


def to_rows(summary: ET.Element) -> list[tuple[dict, list, list]]:
    """Map an AuctionSummary to (auction, results, bids) rows, one auction per direction.

    Both directions share the auction code ('BA-RS-D-20261007'), so the stored id
    appends the direction ('BA-RS-D-20261007/RS-BA'). Bids are always empty.
    """
    code = summary.findtext("AuctionCode")
    by_corridor = {}
    for product in summary.iter("ProductInstanceSummary"):
        corridor, label, _ = product.findtext("ProductInstanceCode").split("_")  # 'RS-BA', '03BH', '26'
        by_corridor.setdefault(corridor, []).append((label, product))

    auctions = []
    for corridor, products in by_corridor.items():
        first = products[0][1]
        out_area, in_area = AREAS[first.findtext("OutAreaEicCode")], AREAS[first.findtext("InAreaEicCode")]
        start = parse_utc(first.findtext("DeliveryFrom"))
        hours = _hours_by_label(date.fromisoformat(delivery_day(start)))
        results = []
        for label, product in products:
            if label not in hours:
                raise ValueError(f"{code}: product {label} is not an hour of {delivery_day(start)}")
            results.append({
                **hours[label],
                "offered_capacity_mw": _number(product, "TotalOfferedQty"),
                "requested_capacity_mw": _number(product, "TotalBidQty"),
                "allocated_capacity_mw": _number(product, "TotalAllocatedQty"),
                "clearing_price_eur_mwh": _number(product, "MarginalPricePerMegawatt"),
                # Only the traders awarded capacity are counted, not every bidder.
                "participants": None,
                "awarded_participants": int(product.findtext("CapacityTradersWithAllocationsCount")),
                "comment": None,
                "cancelled": False,
            })
        results.sort(key=lambda row: row["hour"])
        auction = auction_row(SOURCE, f"{code}/{out_area}-{in_area}", corridor, out_area, in_area, start)
        auctions.append((auction, results, []))
    return auctions


def _hours_by_label(day: date) -> dict[str, dict]:
    """Product label -> hour_columns: '01H' is 00:00-01:00; the 25-hour day repeats
    02:00-03:00 as '03H' then '03BH', the 23-hour day has no '03H'."""
    return {
        f"{end:02d}{'BH' if repeated else 'H'}": columns
        for (end, repeated), columns in hours_by_clock_end(day).items()
    }


def _number(product: ET.Element, tag: str) -> float | None:
    text = product.findtext(tag)
    return float(text) if text not in (None, "") else None
