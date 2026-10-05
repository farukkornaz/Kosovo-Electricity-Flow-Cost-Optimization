"""SQLite market database: daily auction results and bids, and hourly spot prices.

Each auction is stored once in `auctions`; `results` (one row per product hour) and
`bids` point to it by `auction_ref`, so a bid row holds only the bid itself. The
`results_v` and `bids_v` views join them back into flat rows for analysis, and
`results_v` adds the congestion income (allocated capacity x clearing price).

`source` says where a row came from: a platform ('JAO', 'SEECAO'), the local price
API ('ENTSOE'), or a hand-collected file ('MANUAL', see import_manual.py).
"""

import sqlite3
from collections import Counter
from datetime import date
from pathlib import Path

# Shared by every data source, so it lives at the project root.
DEFAULT_PATH = Path(__file__).resolve().parent.parent / "market_data.db"
SCHEMA_VERSION = 2
MANUAL = "MANUAL"

SCHEMA = """
CREATE TABLE IF NOT EXISTS auctions (
    id            INTEGER PRIMARY KEY,
    source        TEXT NOT NULL,  -- 'JAO' | 'SEECAO' | 'MANUAL'
    auction_id    TEXT NOT NULL,  -- platform's id
    corridor      TEXT NOT NULL,  -- platform's code, e.g. 'HU-RS', 'IF1-FR-GB', 'MK-XK'
    out_area      TEXT NOT NULL,
    in_area       TEXT NOT NULL,
    border        TEXT GENERATED ALWAYS AS (out_area || '-' || in_area) VIRTUAL,
    delivery_date TEXT NOT NULL,  -- CET/CEST delivery day, YYYY-MM-DD
    UNIQUE (source, auction_id)
);
CREATE INDEX IF NOT EXISTS auctions_day ON auctions (delivery_date);
CREATE TABLE IF NOT EXISTS results (
    auction_ref            INTEGER NOT NULL REFERENCES auctions (id) ON DELETE CASCADE,
    hour                   INTEGER NOT NULL,  -- 1-based product hour within the delivery day
    timetable              TEXT    NOT NULL,  -- CET/CEST, e.g. '00:00-01:00'
    delivery_start_utc     TEXT    NOT NULL,
    offered_capacity_mw    REAL,
    requested_capacity_mw  REAL,
    allocated_capacity_mw  REAL,
    clearing_price_eur_mwh REAL,
    participants           INTEGER,
    awarded_participants   INTEGER,
    comment                TEXT,     -- JAO only
    cancelled              INTEGER NOT NULL,
    PRIMARY KEY (auction_ref, hour)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS bids (
    auction_ref         INTEGER NOT NULL REFERENCES auctions (id) ON DELETE CASCADE,
    hour                INTEGER NOT NULL,
    seq                 INTEGER NOT NULL,  -- 1 = highest price within the hour
    quantity_mw         REAL    NOT NULL,
    price_eur_mwh       REAL    NOT NULL,
    awarded_quantity_mw REAL,              -- JAO only
    PRIMARY KEY (auction_ref, hour, seq)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS spot_prices (
    source             TEXT    NOT NULL,  -- 'ENTSOE' | 'MANUAL'
    zone               TEXT    NOT NULL,  -- bidding zone, e.g. 'HU'
    delivery_date      TEXT    NOT NULL,  -- CET/CEST delivery day, YYYY-MM-DD
    hour               INTEGER NOT NULL,  -- 1-based product hour within the delivery day
    timetable          TEXT    NOT NULL,  -- CET/CEST, e.g. '00:00-01:00'
    delivery_start_utc TEXT    NOT NULL,
    price_eur_mwh      REAL    NOT NULL,  -- day-ahead price, hourly mean of the 15-min prices
    PRIMARY KEY (source, zone, delivery_start_utc)
);
CREATE INDEX IF NOT EXISTS spot_prices_day ON spot_prices (delivery_date);

DROP VIEW IF EXISTS results_v;
CREATE VIEW results_v AS
SELECT a.source, a.auction_id, a.corridor, a.border, a.out_area, a.in_area, a.delivery_date,
       r.hour, r.timetable, r.delivery_start_utc,
       r.offered_capacity_mw, r.requested_capacity_mw, r.allocated_capacity_mw, r.clearing_price_eur_mwh,
       r.allocated_capacity_mw * r.clearing_price_eur_mwh AS congestion_income_eur,
       r.participants, r.awarded_participants, r.comment, r.cancelled
FROM results r JOIN auctions a ON a.id = r.auction_ref;

DROP VIEW IF EXISTS bids_v;
CREATE VIEW bids_v AS
SELECT a.source, a.auction_id, a.border, a.out_area, a.in_area, a.delivery_date,
       b.hour, r.timetable, r.delivery_start_utc,
       b.seq, b.quantity_mw, b.price_eur_mwh, b.awarded_quantity_mw
FROM bids b
JOIN auctions a ON a.id = b.auction_ref
LEFT JOIN results r ON r.auction_ref = b.auction_ref AND r.hour = b.hour;
"""


def connect(path: Path, create: bool = True) -> sqlite3.Connection:
    """Open the database, creating the schema on a new file."""
    if not create and not Path(path).exists():
        raise FileNotFoundError(f"{path} not found: crawl first (main.py)")
    conn = sqlite3.connect(path)
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    has_tables = conn.execute("SELECT count(*) FROM sqlite_master WHERE type = 'table'").fetchone()[0]
    if has_tables and version != SCHEMA_VERSION:
        conn.close()
        raise RuntimeError(f"{path} has schema version {version}, expected {SCHEMA_VERSION}: move it away and re-crawl")
    conn.executescript(SCHEMA)
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def save_auction(conn: sqlite3.Connection, auction: dict, results: list, bids: list) -> None:
    """Store one auction with its hourly results and bids, replacing whatever was stored for it.

    `auction` is an `auctions` row (common.auction_row). Result and bid rows carry
    `hour` instead of the auction's columns; bids are numbered per hour from the
    highest price down.
    """
    with conn:
        ref = conn.execute(
            """INSERT INTO auctions (source, auction_id, corridor, out_area, in_area, delivery_date)
               VALUES (:source, :auction_id, :corridor, :out_area, :in_area, :delivery_date)
               ON CONFLICT (source, auction_id) DO UPDATE SET
                   corridor = excluded.corridor, out_area = excluded.out_area,
                   in_area = excluded.in_area, delivery_date = excluded.delivery_date
               RETURNING id""",
            auction,
        ).fetchone()[0]
        for table in ("results", "bids"):
            conn.execute(f"DELETE FROM {table} WHERE auction_ref = ?", (ref,))
        _insert(conn, "results", [{"auction_ref": ref, **row} for row in results])

        seq = Counter()
        numbered = []
        for bid in sorted(bids, key=lambda b: (b["hour"], -b["price_eur_mwh"])):
            seq[bid["hour"]] += 1
            numbered.append({"auction_ref": ref, "seq": seq[bid["hour"]], **bid})
        _insert(conn, "bids", numbered)


def has_auction(conn: sqlite3.Connection, source: str, auction_id: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM auctions WHERE source = ? AND auction_id = ?", (source, auction_id)
    ).fetchone() is not None


def save_spot_prices(conn: sqlite3.Connection, rows: list) -> None:
    """Upsert hourly spot prices; a re-fetched hour replaces the stored one from the same source."""
    with conn:
        _insert(conn, "spot_prices", rows, or_replace=True)


def spot_price_days(conn: sqlite3.Connection, source: str, start: date, end: date) -> set[date]:
    """Delivery days between `start` and `end` (inclusive) with spot prices from `source`."""
    rows = conn.execute(
        "SELECT DISTINCT delivery_date FROM spot_prices WHERE source = ? AND delivery_date BETWEEN ? AND ?",
        (source, start.isoformat(), end.isoformat()),
    ).fetchall()
    return {date.fromisoformat(day) for (day,) in rows}


def _insert(conn: sqlite3.Connection, table: str, rows: list, or_replace: bool = False) -> None:
    if not rows:
        return
    columns = list(rows[0])
    verb = "INSERT OR REPLACE" if or_replace else "INSERT"
    conn.executemany(
        f"{verb} INTO {table} ({', '.join(columns)}) VALUES ({', '.join('?' * len(columns))})",
        [tuple(row[c] for c in columns) for row in rows],
    )
