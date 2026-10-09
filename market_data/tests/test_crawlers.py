import io
import json
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date

import pytest

import common
from jao import crawler as jao
from nosbih import crawler as nosbih
from seecao import crawler as seecao


def test_fetch_json_retries_a_reset_connection(monkeypatch):
    calls = []

    def urlopen(request, timeout):
        calls.append(request.full_url)
        if len(calls) == 1:
            raise ConnectionResetError(104, "Connection reset by peer")
        return io.BytesIO(b'{"ok": true}')

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(common.time, "sleep", lambda seconds: None)
    assert common.fetch_json("https://example.test", {}) == {"ok": True}
    assert len(calls) == 2


def test_jao_to_rows():
    auction = {
        "identification": "IF1-FR-GB-D-1",
        "corridorCode": "IF1-FR-GB",
        "marketPeriodStart": "2026-08-31T22:00:00Z",
        "cancelled": False,
        "products": [{"productIdentification": "B01-------", "bidderPartyCount": 3, "winnerPartyCount": 1}],
        "results": [{
            "productIdentification": "B01-------", "productHour": "00:00 - 01:00",
            "offeredCapacity": 100, "requestedCapacity": 30, "allocatedCapacity": 30, "auctionPrice": 1.5,
            "comment": None, "additionalMessage": "",
        }],
    }
    bids = [
        {"productIdentification": "B01-------", "productHour": "00:00 - 01:00", "quantity": 30,
         "price": 1.5, "awardedQuantity": 30, "currency": "EUR"},
        {"productIdentification": "B02-------", "productHour": "01:00 - 02:00", "quantity": 0,
         "price": 1.0, "awardedQuantity": 0, "currency": "EUR"},
    ]
    auction_row, results, bid_rows = jao.to_rows(auction, bids)

    assert jao.areas(auction) == ("FR", "GB")
    assert auction_row == {"source": "JAO", "auction_id": "IF1-FR-GB-D-1", "corridor": "IF1-FR-GB",
                           "out_area": "FR", "in_area": "GB", "delivery_date": "2026-09-01"}
    assert results[0]["timetable"] == "00:00-01:00"
    assert results[0]["participants"] == 3
    assert bid_rows == [{"hour": 1, "quantity_mw": 30, "price_eur_mwh": 1.5, "awarded_quantity_mw": 30}]


def jao_auction(market_period_start, products):
    """A `getauctions` entry with one result per (productIdentification, productHour)."""
    return {
        "identification": "HU-RS-D-1", "corridorCode": "HU-RS", "marketPeriodStart": market_period_start,
        "cancelled": False,
        "products": [{"productIdentification": pid, "bidderPartyCount": 3, "winnerPartyCount": 1} for pid, _ in products],
        "results": [{
            "productIdentification": pid, "productHour": product_hour,
            "offeredCapacity": 100, "requestedCapacity": 30, "allocatedCapacity": 30, "auctionPrice": 1.5,
            "comment": None, "additionalMessage": "",
        } for pid, product_hour in products],
    }


def test_jao_hours_on_clock_change_days():
    # 25 hours: the repeated 02:00-03:00 is B03DST, and B04 is the day's fifth hour.
    fall = [("B03-------", "02:00-03:00"), ("B03DST----", "02:00-03:00*"), ("B04-------", "03:00-04:00")]
    bids = [{"productIdentification": pid, "productHour": product_hour, "quantity": 30, "price": 1.5,
             "awardedQuantity": 30, "currency": "EUR"} for pid, product_hour in fall]
    _, results, bid_rows = jao.to_rows(jao_auction("2025-10-25T22:00:00.000+00:00", fall), bids)
    assert [(r["hour"], r["timetable"], r["delivery_start_utc"]) for r in results] == [
        (3, "02:00-03:00", "2025-10-26T00:00:00Z"),
        (4, "02:00-03:00", "2025-10-26T01:00:00Z"),
        (5, "03:00-04:00", "2025-10-26T02:00:00Z"),
    ]
    assert [b["hour"] for b in bid_rows] == [3, 4, 5]

    # 23 hours: there is no B03, and B04 is the day's third hour.
    spring = [("B02-------", "01:00-02:00"), ("B04-------", "03:00-04:00")]
    _, results, _ = jao.to_rows(jao_auction("2026-03-28T23:00:00.000+00:00", spring), [])
    assert [(r["hour"], r["timetable"], r["delivery_start_utc"]) for r in results] == [
        (2, "01:00-02:00", "2026-03-29T00:00:00Z"),
        (3, "03:00-04:00", "2026-03-29T01:00:00Z"),
    ]
    with pytest.raises(ValueError, match="B03------- is not an hour of 2026-03-29"):
        jao.to_rows(jao_auction("2026-03-28T23:00:00.000+00:00", [("B03-------", "02:00-03:00")]), [])


def test_seecao_to_rows_differences_the_cumulative_curve():
    auction = {
        "auctionIdentification": "MKXK-DH-20260901-1",
        "deliveryPeriodStart": "2026-08-31T22:00:00Z",
        "table": [{
            "border": "MK - XK", "pos": 1, "timetable": "00:00 - 01:00",
            "offered": "100.00", "requested": "70.00", "allocated": "70.00", "price": "--", "income": None,
            "numberOfParticipants": 2, "numberOfSuccessfullParticipants": 2, "numberOfAuctionBids": 2,
            "cancelled": False,
        }],
        "bids": [{"position": 0, "title": "00:00 - 01:00",
                  "line": [{"capacity": 20, "price": "9.5"}, {"capacity": 20, "price": "8"},
                           {"capacity": 70, "price": "1"}]}],
    }
    auction_row, results, bids = seecao.to_rows(auction)

    assert auction_row["corridor"] == "MK-XK"
    assert results[0]["clearing_price_eur_mwh"] is None
    assert [(b["quantity_mw"], b["price_eur_mwh"]) for b in bids] == [(20, 9.5), (50, 1.0)]


def test_seecao_repeated_hour_on_the_25_hour_day():
    def row(pos, timetable):
        return {
            "border": "MK - XK", "pos": pos, "timetable": timetable,
            "offered": "100.00", "requested": "0.00", "allocated": "0.00", "price": "0.00", "income": None,
            "numberOfParticipants": 0, "numberOfSuccessfullParticipants": 0, "numberOfAuctionBids": 0,
            "cancelled": False,
        }
    auction = {
        "auctionIdentification": "MKXK-DH-20251026-1",
        "deliveryPeriodStart": "2025-10-25T22:00:00Z",
        "table": [row(3, "02:00 - 03:00 (1)"), row(4, "02:00 - 03:00 (2)"), row(5, "03:00 - 04:00")],
        "bids": [],
    }
    _, results, _ = seecao.to_rows(auction)
    assert [(r["hour"], r["timetable"], r["delivery_start_utc"]) for r in results] == [
        (3, "02:00-03:00", "2025-10-26T00:00:00Z"),
        (4, "02:00-03:00", "2025-10-26T01:00:00Z"),
        (5, "03:00-04:00", "2025-10-26T02:00:00Z"),
    ]


def test_seecao_without_results():
    assert seecao.to_rows({"table": [], "bids": []}) is None


def nosbih_product(code, out_eic, in_eic, delivery_from, offered, price, awarded):
    return f"""<ProductInstanceSummary>
      <ProductInstanceCode>{code}</ProductInstanceCode>
      <InAreaEicCode>{in_eic}</InAreaEicCode><OutAreaEicCode>{out_eic}</OutAreaEicCode>
      <DeliveryFrom>{delivery_from}</DeliveryFrom>
      <MarginalPrice>{price}</MarginalPrice><MarginalPricePerMegawatt>{price}</MarginalPricePerMegawatt>
      <TotalOfferedQty>{offered}</TotalOfferedQty><TotalBidQty>700</TotalBidQty>
      <TotalAllocatedQty>{offered}</TotalAllocatedQty><TotalBidsCount>29</TotalBidsCount>
      <CapacityTradersWithAllocationsCount>{awarded}</CapacityTradersWithAllocationsCount>
    </ProductInstanceSummary>"""


def nosbih_summary(code, products):
    return ET.fromstring(f"""\ufeff<?xml version="1.0" encoding="utf-8"?>
    <AuctionSummary><AuctionCode>{code}</AuctionCode>
      <ProductInstanceSummaries>{"".join(products)}</ProductInstanceSummaries></AuctionSummary>""".encode())


BA, RS = "10YBA-JPCC-----D", "10YCS-SERBIATSOV"


def test_nosbih_to_rows_splits_the_directions():
    summary = nosbih_summary("BA-RS-D-20261007", [
        nosbih_product("BA-RS_24H_07", BA, RS, "2026-10-06T22:00:00Z", 441, 3.69, 5),
        nosbih_product("BA-RS_01H_07", BA, RS, "2026-10-06T22:00:00Z", 451, 2.1, 5),
        nosbih_product("RS-BA_01H_07", RS, BA, "2026-10-06T22:00:00Z", 549, 0, 9),
    ])
    (ba_rs, ba_rs_results, bids), (rs_ba, rs_ba_results, _) = nosbih.to_rows(summary)

    assert ba_rs == {"source": "NOSBIH", "auction_id": "BA-RS-D-20261007/BA-RS", "corridor": "BA-RS",
                     "out_area": "BA", "in_area": "RS", "delivery_date": "2026-10-07"}
    assert rs_ba["auction_id"] == "BA-RS-D-20261007/RS-BA" and (rs_ba["out_area"], rs_ba["in_area"]) == ("RS", "BA")
    assert [(r["hour"], r["timetable"], r["delivery_start_utc"]) for r in ba_rs_results] == [
        (1, "00:00-01:00", "2026-10-06T22:00:00Z"), (24, "23:00-24:00", "2026-10-07T21:00:00Z")]
    assert ba_rs_results[0]["clearing_price_eur_mwh"] == 2.1 and ba_rs_results[0]["awarded_participants"] == 5
    assert ba_rs_results[0]["participants"] is None
    assert rs_ba_results[0]["clearing_price_eur_mwh"] == 0
    assert bids == []


def test_nosbih_repeated_hour_on_the_25_hour_day():
    summary = nosbih_summary("BA-RS-D-20251026", [
        nosbih_product(f"BA-RS_{label}_26", BA, RS, "2025-10-25T22:00:00Z", 455, 0, 7)
        for label in ("03BH", "03H", "04H")
    ])
    [(_, results, _)] = nosbih.to_rows(summary)
    assert [(r["hour"], r["timetable"], r["delivery_start_utc"]) for r in results] == [
        (3, "02:00-03:00", "2025-10-26T00:00:00Z"),
        (4, "02:00-03:00", "2025-10-26T01:00:00Z"),
        (5, "03:00-04:00", "2025-10-26T02:00:00Z"),
    ]


def test_nosbih_list_daily_auctions(monkeypatch):
    posted = []

    def fetch(url, headers, data=None):
        posted.append(data)
        html = '<td colspan="7"><a href="../../../files/auction/20261007_AuctionSummary_BA-RS-D-20261007.xml" download>'
        return json.dumps({"success": True, "data": html}).encode()

    monkeypatch.setattr(nosbih, "fetch", fetch)
    assert nosbih.list_daily_auctions(date(2026, 10, 7)) == [
        "https://www.nosbih.ba/files/auction/20261007_AuctionSummary_BA-RS-D-20261007.xml"]
    assert posted == [b"action=auction&auction=date%3D07.10.2026."]
