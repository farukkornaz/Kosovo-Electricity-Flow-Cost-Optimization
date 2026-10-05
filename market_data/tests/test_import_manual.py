import pytest

import db
from build_scenario import build_scenario
from helpers import DAY
from import_manual import read_csv, to_auctions, to_spot_prices


def write(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_results_bids_and_spot_round_trip(tmp_path):
    _, results = read_csv(write(tmp_path, "r.csv",
        "border,delivery_date,timetable,offered_capacity_mw,clearing_price_eur_mwh\n"
        "BA-RS,2026-09-01,*,300,4.5\n"))
    _, bids = read_csv(write(tmp_path, "b.csv",
        "border,delivery_date,timetable,quantity_mw,price_eur_mwh\n"
        "BA-RS,2026-09-01,14:00-15:00,250,9\n"
        "BA-RS,2026-09-01,14:00-15:00,100,4.5\n"))
    kind, spot = read_csv(write(tmp_path, "s.csv",
        "zone,delivery_date,timetable,price_eur_mwh\n"
        "BA,2026-09-01,*,95\n"))
    assert kind == "spot"

    auctions = to_auctions(results, bids)
    assert len(auctions) == 1
    auction, result_rows, bid_rows = auctions[0]
    assert auction["auction_id"] == "MANUAL-BA-RS-2026-09-01"
    assert len(result_rows) == 24 and len(bid_rows) == 2

    conn = db.connect(tmp_path / "market.db")
    db.save_auction(conn, *auctions[0])
    db.save_spot_prices(conn, to_spot_prices(spot))
    scenario, report = build_scenario(conn, DAY, "14:00-15:00", demand=400, seed=1)
    conn.close()

    ba_rs = next(a["curve"] for a in scenario["arcs"] if (a["from"], a["to"]) == ("BA", "RS"))
    assert ba_rs["capacity"] == 300 and ba_rs["slope"] > 0
    assert "BA->RS MANUAL" in report.open
    assert next(n for n in scenario["nodes"] if n["id"] == "BA")["unit_price"] == 95.0


def test_unknown_border_is_rejected(tmp_path):
    _, rows = read_csv(write(tmp_path, "r.csv",
        "border,delivery_date,timetable,offered_capacity_mw,clearing_price_eur_mwh\n"
        "AL-BG,2026-09-01,*,300,4.5\n"))
    with pytest.raises(ValueError, match="r.csv:2: border 'AL-BG' is not in network.BORDERS"):
        to_auctions(rows, [])


def test_bids_need_a_result(tmp_path):
    _, bids = read_csv(write(tmp_path, "b.csv",
        "border,delivery_date,timetable,quantity_mw,price_eur_mwh\n"
        "BA-RS,2026-09-01,14:00-15:00,250,9\n"))
    with pytest.raises(ValueError, match="have no results row"):
        to_auctions([], bids)


def test_header_decides_the_kind(tmp_path):
    with pytest.raises(ValueError, match="not a results, bids or spot file"):
        read_csv(write(tmp_path, "x.csv", "border,price\nBA-RS,1\n"))
