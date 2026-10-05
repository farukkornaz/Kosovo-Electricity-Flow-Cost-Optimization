from jao import crawler as jao
from seecao import crawler as seecao


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


def test_seecao_without_results():
    assert seecao.to_rows({"table": [], "bids": []}) is None
