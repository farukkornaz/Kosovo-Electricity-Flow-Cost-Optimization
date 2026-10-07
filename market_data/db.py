"""PostgreSQL market database: daily auction results and bids, and hourly spot prices.

Each auction is stored once in `auctions`; `results` (one row per product hour) and
`bids` point to it by `auction_ref`, so a bid row holds only the bid itself. The
`results_v` and `bids_v` views join them back into flat rows for analysis, and
`results_v` adds the congestion income (allocated capacity x clearing price).

`source` says where a row came from: a platform ('JAO', 'SEECAO'), the local price
API ('ENTSOE'), or a hand-collected file ('MANUAL', see import_manual.py).

The server runs in Docker (`docker compose up -d db`). Credentials come from the
project's .env file (see .env.example), which docker compose reads too.
"""

import os
from collections import Counter
from datetime import date
from pathlib import Path

import psycopg
from psycopg.conninfo import make_conninfo

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
# 1 and 2 were SQLite files (market_data.db); 3 is the first PostgreSQL schema.
SCHEMA_VERSION = 3
MANUAL = "MANUAL"

SCHEMA = """
CREATE TABLE schema_version (version INTEGER NOT NULL);
CREATE TABLE auctions (
    id            INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source        TEXT NOT NULL,  -- 'JAO' | 'SEECAO' | 'MANUAL'
    auction_id    TEXT NOT NULL,  -- platform's id
    corridor      TEXT NOT NULL,  -- platform's code, e.g. 'HU-RS', 'IF1-FR-GB', 'MK-XK'
    out_area      TEXT NOT NULL,
    in_area       TEXT NOT NULL,
    border        TEXT GENERATED ALWAYS AS (out_area || '-' || in_area) STORED,
    delivery_date DATE NOT NULL,  -- CET/CEST delivery day
    UNIQUE (source, auction_id)
);
CREATE INDEX auctions_day ON auctions (delivery_date);
CREATE INDEX auctions_border_day ON auctions (border, delivery_date);
CREATE TABLE results (
    auction_ref            INTEGER  NOT NULL REFERENCES auctions (id) ON DELETE CASCADE,
    hour                   SMALLINT NOT NULL,  -- 1-based product hour within the delivery day
    timetable              TEXT     NOT NULL,  -- CET/CEST, e.g. '00:00-01:00'
    delivery_start_utc     TIMESTAMPTZ NOT NULL,
    offered_capacity_mw    DOUBLE PRECISION,
    requested_capacity_mw  DOUBLE PRECISION,
    allocated_capacity_mw  DOUBLE PRECISION,
    clearing_price_eur_mwh DOUBLE PRECISION,
    participants           INTEGER,
    awarded_participants   INTEGER,
    comment                TEXT,     -- JAO only
    cancelled              BOOLEAN  NOT NULL,
    PRIMARY KEY (auction_ref, hour)
);
CREATE TABLE bids (
    auction_ref         INTEGER  NOT NULL REFERENCES auctions (id) ON DELETE CASCADE,
    hour                SMALLINT NOT NULL,
    seq                 INTEGER  NOT NULL,          -- 1 = highest price within the hour
    quantity_mw         DOUBLE PRECISION NOT NULL,
    price_eur_mwh       DOUBLE PRECISION NOT NULL,
    awarded_quantity_mw DOUBLE PRECISION,           -- JAO only
    PRIMARY KEY (auction_ref, hour, seq)
);
CREATE TABLE spot_prices (
    source             TEXT     NOT NULL,  -- 'ENTSOE' | 'MANUAL'
    zone               TEXT     NOT NULL,  -- bidding zone, e.g. 'HU'
    delivery_date      DATE     NOT NULL,  -- CET/CEST delivery day
    hour               SMALLINT NOT NULL,  -- 1-based product hour within the delivery day
    timetable          TEXT     NOT NULL,  -- CET/CEST, e.g. '00:00-01:00'
    delivery_start_utc TIMESTAMPTZ NOT NULL,
    price_eur_mwh      DOUBLE PRECISION NOT NULL,  -- day-ahead price, hourly mean of the 15-min prices
    PRIMARY KEY (source, zone, delivery_start_utc)
);
CREATE INDEX spot_prices_day ON spot_prices (delivery_date);

CREATE VIEW results_v AS
SELECT a.source, a.auction_id, a.corridor, a.border, a.out_area, a.in_area, a.delivery_date,
       r.hour, r.timetable, r.delivery_start_utc,
       r.offered_capacity_mw, r.requested_capacity_mw, r.allocated_capacity_mw, r.clearing_price_eur_mwh,
       r.allocated_capacity_mw * r.clearing_price_eur_mwh AS congestion_income_eur,
       r.participants, r.awarded_participants, r.comment, r.cancelled
FROM results r JOIN auctions a ON a.id = r.auction_ref;

CREATE VIEW bids_v AS
SELECT a.source, a.auction_id, a.border, a.out_area, a.in_area, a.delivery_date,
       b.hour, r.timetable, r.delivery_start_utc,
       b.seq, b.quantity_mw, b.price_eur_mwh, b.awarded_quantity_mw
FROM bids b
JOIN auctions a ON a.id = b.auction_ref
LEFT JOIN results r ON r.auction_ref = b.auction_ref AND r.hour = b.hour;
"""


def database_url(dbname: str | None = None) -> str:
    """DATABASE_URL, or a URL built from POSTGRES_USER / _PASSWORD / _DB (and _HOST, _PORT).

    Environment variables win over the .env file. `dbname` swaps the database (tests).
    """
    settings = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            key, sep, value = line.partition("=")
            if sep and not key.lstrip().startswith("#"):
                settings[key.strip()] = value.strip()
    settings |= os.environ
    url = settings.get("DATABASE_URL")
    if not url:
        try:
            user, password, name = (settings[k] for k in ("POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB"))
        except KeyError as exc:
            raise RuntimeError(f"{exc.args[0]} not set: copy .env.example to .env (or set DATABASE_URL)") from None
        host, port = settings.get("POSTGRES_HOST", "localhost"), settings.get("POSTGRES_PORT", "5432")
        url = f"postgresql://{user}:{password}@{host}:{port}/{name}"
    return make_conninfo(url, dbname=dbname) if dbname else url


def connect(url: str | None = None, create: bool = True) -> psycopg.Connection:
    """Open the database (default: database_url()) in autocommit mode, creating the schema in an empty one.

    Writes that must be atomic run in `with conn.transaction():`.
    """
    conn = psycopg.connect(url or database_url(), autocommit=True)
    version = schema_version(conn)
    where = describe(conn)
    if version is None:
        if not create:
            conn.close()
            raise LookupError(f"{where} has no market schema: crawl first (main.py)")
        with conn.transaction():
            conn.execute(SCHEMA)
            conn.execute("INSERT INTO schema_version VALUES (%s)", (SCHEMA_VERSION,))
    elif version != SCHEMA_VERSION:
        conn.close()
        raise RuntimeError(f"{where} has schema version {version}, expected {SCHEMA_VERSION}")
    return conn


def schema_version(conn: psycopg.Connection) -> int | None:
    """The stored schema version; None in an empty database, 0 for tables of unknown origin."""
    if conn.execute("SELECT to_regclass('schema_version')").fetchone()[0] is None:
        return 0 if conn.execute("SELECT to_regclass('auctions')").fetchone()[0] else None
    return conn.execute("SELECT max(version) FROM schema_version").fetchone()[0]


def describe(conn: psycopg.Connection) -> str:
    """host:port/dbname, without the password, for messages."""
    return f"{conn.info.host}:{conn.info.port}/{conn.info.dbname}"


def save_auction(conn: psycopg.Connection, auction: dict, results: list, bids: list) -> None:
    """Store one auction with its hourly results and bids, replacing whatever was stored for it.

    `auction` is an `auctions` row (common.auction_row). Result and bid rows carry
    `hour` instead of the auction's columns; bids are numbered per hour from the
    highest price down.
    """
    with conn.transaction():
        ref = conn.execute(
            """INSERT INTO auctions (source, auction_id, corridor, out_area, in_area, delivery_date)
               VALUES (%(source)s, %(auction_id)s, %(corridor)s, %(out_area)s, %(in_area)s, %(delivery_date)s)
               ON CONFLICT (source, auction_id) DO UPDATE SET
                   corridor = excluded.corridor, out_area = excluded.out_area,
                   in_area = excluded.in_area, delivery_date = excluded.delivery_date
               RETURNING id""",
            auction,
        ).fetchone()[0]
        for table in ("results", "bids"):
            conn.execute(f"DELETE FROM {table} WHERE auction_ref = %s", (ref,))
        _insert(conn, "results", [{"auction_ref": ref, **row} for row in results])

        seq = Counter()
        numbered = []
        for bid in sorted(bids, key=lambda b: (b["hour"], -b["price_eur_mwh"])):
            seq[bid["hour"]] += 1
            numbered.append({"auction_ref": ref, "seq": seq[bid["hour"]], **bid})
        _insert(conn, "bids", numbered)


def has_auction(conn: psycopg.Connection, source: str, auction_id: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM auctions WHERE source = %s AND auction_id = %s", (source, auction_id)
    ).fetchone() is not None


def save_spot_prices(conn: psycopg.Connection, rows: list) -> None:
    """Upsert hourly spot prices; a re-fetched hour replaces the stored one from the same source."""
    with conn.transaction():
        _insert(conn, "spot_prices", rows, upsert_on=("source", "zone", "delivery_start_utc"))


def spot_price_days(conn: psycopg.Connection, source: str, start: date, end: date) -> set[date]:
    """Delivery days between `start` and `end` (inclusive) with spot prices from `source`."""
    rows = conn.execute(
        "SELECT DISTINCT delivery_date FROM spot_prices WHERE source = %s AND delivery_date BETWEEN %s AND %s",
        (source, start, end),
    ).fetchall()
    return {day for (day,) in rows}


def _insert(conn: psycopg.Connection, table: str, rows: list, upsert_on: tuple = ()) -> None:
    if not rows:
        return
    columns = list(rows[0])
    sql = f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({', '.join(['%s'] * len(columns))})"
    if upsert_on:
        updates = ", ".join(f"{c} = excluded.{c}" for c in columns if c not in upsert_on)
        sql += f" ON CONFLICT ({', '.join(upsert_on)}) DO UPDATE SET {updates}"
    with conn.cursor() as cur:
        cur.executemany(sql, [tuple(row[c] for c in columns) for row in rows])
