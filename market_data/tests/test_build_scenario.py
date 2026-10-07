import pytest

import db
import network
from build_scenario import build_scenario, fit_linear_curve
from helpers import DAY, auction, result, store

HOUR = "14:00-15:00"


def arcs_by_id(scenario):
    return {f"{a['from']}->{a['to']}": a["curve"] for a in scenario["arcs"]}


def test_fit_linear_curve():
    # Without bids the curve is flat at the clearing price.
    flat = fit_linear_curve([], capacity=100, clearing_price=10.0)
    assert flat == {"type": "linear", "base_price": 10.0, "slope": 0.0, "capacity": 100}
    # What we take leaves less for the others, so the price climbs to their 30 €/MWh bid.
    rising = fit_linear_curve([(50, 30.0), (50, 10.0)], capacity=100, clearing_price=10.0)
    assert rising["slope"] > 0


def test_every_border_becomes_two_arcs(conn):
    scenario, report = build_scenario(conn, DAY, HOUR, demand=400, seed=1)
    assert len(scenario["arcs"]) == 2 * len(network.BORDERS)
    assert all(curve["capacity"] == 0 for curve in arcs_by_id(scenario).values())
    assert "RS-XK" in report.closed
    assert "MK->XK (SEECAO)" in report.missing


def test_data_opens_a_direction(conn):
    store(conn, "SEECAO", "MK", "XK", capacity=200, price=5.0, bids=[(150, 20.0), (100, 5.0)])
    store(conn, db.MANUAL, "BA", "RS", capacity=300, price=4.0)
    scenario, report = build_scenario(conn, DAY, HOUR, demand=400, seed=1)

    arcs = arcs_by_id(scenario)
    assert arcs["MK->XK"]["capacity"] == 200 and arcs["MK->XK"]["slope"] > 0
    assert arcs["BA->RS"] == {"type": "linear", "base_price": 4.0, "slope": 0.0, "capacity": 300}
    assert arcs["XK->MK"]["capacity"] == 0
    assert "MK->XK SEECAO" in report.open
    assert "BA->RS MANUAL" in report.flat
    assert "RS->BA" in report.closed


def test_platform_wins_over_manual(conn):
    store(conn, "SEECAO", "MK", "XK", capacity=200, price=5.0)
    store(conn, db.MANUAL, "MK", "XK", capacity=999, price=1.0)
    scenario, report = build_scenario(conn, DAY, HOUR, demand=400, seed=1)

    assert arcs_by_id(scenario)["MK->XK"]["capacity"] == 200
    assert report.overridden == ["MK->XK (SEECAO)"]


def test_rerun_replaces_the_cancelled_auction(conn):
    cancelled = auction("JAO", "HR", "RS") | {"auction_id": "HR-RS-D-01"}
    rerun = auction("JAO", "HR", "RS") | {"auction_id": "HR-RS-D-02"}
    db.save_auction(conn, cancelled, [result(15, 100, 1.0, cancelled=True)], [])
    db.save_auction(conn, rerun, [result(15, 200, 2.0)], [])
    scenario, report = build_scenario(conn, DAY, HOUR, demand=400, seed=1)

    assert arcs_by_id(scenario)["HR->RS"]["capacity"] == 200
    assert "HR->RS JAO" in report.flat


def test_unlisted_border_is_an_error(conn):
    store(conn, db.MANUAL, "AL", "BG")
    with pytest.raises(ValueError, match="not in network.BORDERS"):
        build_scenario(conn, DAY, HOUR, demand=400, seed=1)


def test_spot_prices_entsoe_before_manual_then_placeholder(conn):
    hour = {"delivery_date": DAY.isoformat(), "hour": 15, "timetable": HOUR, "delivery_start_utc": "2026-09-01T12:00:00Z"}
    db.save_spot_prices(conn, [
        {"source": "ENTSOE", "zone": "RS", **hour, "price_eur_mwh": 90.0},
        {"source": db.MANUAL, "zone": "RS", **hour, "price_eur_mwh": 1.0},
        {"source": db.MANUAL, "zone": "BA", **hour, "price_eur_mwh": 80.0},
    ])
    scenario, report = build_scenario(conn, DAY, HOUR, demand=400, seed=1)

    prices = {n["id"]: n.get("unit_price") for n in scenario["nodes"]}
    assert prices["RS"] == 90.0 and prices["BA"] == 80.0
    assert "BA" not in report.placeholder_prices and "TR" in report.placeholder_prices
