"""Data layer for the oil godown inventory app.

Works against a cloud PostgreSQL database (e.g. Neon) when a connection URL is
provided via Streamlit secrets or the DATABASE_URL environment variable. Falls
back to a local SQLite file when no URL is set, so the app can still be run
locally for testing. The SQL is written with SQLAlchemy so the same code works
on both databases.
"""

import os
from pathlib import Path

import pandas as pd
from sqlalchemy import (
    Column,
    Float,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    create_engine,
    text,
)

LOCAL_SQLITE_PATH = Path(__file__).parent / "oil_inventory.db"

metadata = MetaData()

oil_types = Table(
    "oil_types", metadata,
    Column("id", Integer, primary_key=True),
    Column("name", String(120), unique=True, nullable=False),
)

tanks = Table(
    "tanks", metadata,
    Column("id", Integer, primary_key=True),
    Column("name", String(120), unique=True, nullable=False),
    Column("oil_type_id", Integer, ForeignKey("oil_types.id"), nullable=False),
    Column("capacity", Float, nullable=False),
    Column("current_volume", Float, nullable=False, default=0),
)

incoming_transactions = Table(
    "incoming_transactions", metadata,
    Column("id", Integer, primary_key=True),
    Column("date", String(20), nullable=False),
    Column("oil_type_id", Integer, ForeignKey("oil_types.id"), nullable=False),
    Column("tank_id", Integer, ForeignKey("tanks.id"), nullable=False),
    Column("quantity", Float, nullable=False),
    Column("rate", Float, nullable=False),
    Column("supplier", String(255)),
)

outgoing_transactions = Table(
    "outgoing_transactions", metadata,
    Column("id", Integer, primary_key=True),
    Column("date", String(20), nullable=False),
    Column("oil_type_id", Integer, ForeignKey("oil_types.id"), nullable=False),
    Column("tank_id", Integer, ForeignKey("tanks.id"), nullable=False),
    Column("quantity", Float, nullable=False),
    Column("buyer", String(255)),
    Column("notes", String(1000)),
)

# Small key/value table used to remember one-off facts, e.g. whether the
# sample data has already been seeded (so clearing data never re-seeds it).
app_meta = Table(
    "app_meta", metadata,
    Column("key", String(50), primary_key=True),
    Column("value", String(255)),
)


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

_engine = None


def _resolve_db_url() -> str:
    """Find the database URL from Streamlit secrets, env var, or local SQLite."""
    url = None
    try:
        import streamlit as st

        url = st.secrets.get("db_url")
    except Exception:
        url = None

    if not url:
        url = os.environ.get("DATABASE_URL")

    if not url:
        return "sqlite:///" + str(LOCAL_SQLITE_PATH)

    # SQLAlchemy needs the "postgresql://" scheme (some providers give "postgres://").
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return url


def get_engine():
    global _engine
    if _engine is None:
        url = _resolve_db_url()
        connect_args = {}
        engine_kwargs = {"pool_pre_ping": True, "future": True}
        if url.startswith("sqlite"):
            connect_args["check_same_thread"] = False
        _engine = create_engine(url, connect_args=connect_args, **engine_kwargs)
    return _engine


def init_db():
    """Create tables if missing. Seed sample data only on the very first
    initialisation (tracked in app_meta) so that clearing the data later never
    causes the sample data to come back."""
    engine = get_engine()
    metadata.create_all(engine)
    need_seed = False
    with engine.begin() as conn:
        seeded = conn.execute(text("SELECT value FROM app_meta WHERE key = 'seeded'")).scalar()
        if seeded is None:
            oil_count = conn.execute(text("SELECT COUNT(*) FROM oil_types")).scalar()
            need_seed = oil_count == 0
            conn.execute(app_meta.insert().values(key="seeded", value="yes"))
    if need_seed:
        _seed_sample_data()


def _seed_sample_data():
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(insert_names(oil_types, ["Furnace Oil", "LSFO", "Rubber Oil"]))
        oil_type_ids = {
            r.name: r.id
            for r in conn.execute(text("SELECT id, name FROM oil_types")).fetchall()
        }

        tank_rows = [
            ("Tank 1", "Furnace Oil", 50000),
            ("Tank 2", "LSFO", 40000),
            ("Tank 3", "Rubber Oil", 30000),
            ("Tank 4", "Furnace Oil", 25000),
        ]
        for name, oil, cap in tank_rows:
            conn.execute(
                tanks.insert().values(
                    name=name, oil_type_id=oil_type_ids[oil], capacity=cap, current_volume=0
                )
            )
        tank_ids = {
            r.name: r.id for r in conn.execute(text("SELECT id, name FROM tanks")).fetchall()
        }

        incoming = [
            ("2026-05-01", "Furnace Oil", "Tank 1", 20000, 45.0, "Supplier A - Batch FA101"),
            ("2026-06-01", "Furnace Oil", "Tank 1", 10000, 47.0, "Supplier B - Batch FB204"),
            ("2026-06-15", "Furnace Oil", "Tank 4", 8000, 46.0, "Supplier C - Batch FC310"),
            ("2026-05-10", "LSFO", "Tank 2", 15000, 38.0, "Supplier D - Batch LD055"),
            ("2026-06-20", "LSFO", "Tank 2", 10000, 40.0, "Supplier E - Batch LE087"),
            ("2026-05-15", "Rubber Oil", "Tank 3", 12000, 55.0, "Supplier F - Batch RF012"),
            ("2026-07-01", "Rubber Oil", "Tank 3", 5000, 58.0, "Supplier G - Batch RG045"),
        ]
        for date, oil, tank, qty, rate, supplier in incoming:
            conn.execute(
                incoming_transactions.insert().values(
                    date=date, oil_type_id=oil_type_ids[oil], tank_id=tank_ids[tank],
                    quantity=qty, rate=rate, supplier=supplier,
                )
            )
            conn.execute(
                text("UPDATE tanks SET current_volume = current_volume + :q WHERE id = :id"),
                {"q": qty, "id": tank_ids[tank]},
            )

        outgoing = [
            ("2026-06-10", "Furnace Oil", "Tank 1", 8000, "MH-12-AB-1234", "Regular delivery"),
            ("2026-06-25", "LSFO", "Tank 2", 6000, "MH-14-CD-5678", "Regular delivery"),
            ("2026-07-10", "Rubber Oil", "Tank 3", 4000, "MH-12-EF-9999", "Regular delivery"),
        ]
        for date, oil, tank, qty, buyer, notes in outgoing:
            conn.execute(
                outgoing_transactions.insert().values(
                    date=date, oil_type_id=oil_type_ids[oil], tank_id=tank_ids[tank],
                    quantity=qty, buyer=buyer, notes=notes,
                )
            )
            conn.execute(
                text("UPDATE tanks SET current_volume = current_volume - :q WHERE id = :id"),
                {"q": qty, "id": tank_ids[tank]},
            )


def insert_names(table, names):
    """Helper: build a multi-row insert for a table with just a `name` column."""
    return table.insert().values([{"name": n} for n in names])


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

def get_oil_types() -> pd.DataFrame:
    return pd.read_sql(text("SELECT id, name FROM oil_types ORDER BY name"), get_engine())


def get_tanks(oil_type_id: int | None = None) -> pd.DataFrame:
    query = """
        SELECT t.id, t.name, t.oil_type_id, o.name AS oil_type, t.capacity, t.current_volume
        FROM tanks t
        JOIN oil_types o ON o.id = t.oil_type_id
    """
    params = {}
    if oil_type_id is not None:
        query += " WHERE t.oil_type_id = :oil_type_id"
        params["oil_type_id"] = oil_type_id
    query += " ORDER BY t.name"
    return pd.read_sql(text(query), get_engine(), params=params)


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------

def add_incoming(date, oil_type_id, tank_id, quantity, rate, supplier):
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(
            incoming_transactions.insert().values(
                date=date, oil_type_id=oil_type_id, tank_id=tank_id,
                quantity=quantity, rate=rate, supplier=supplier,
            )
        )
        conn.execute(
            text("UPDATE tanks SET current_volume = current_volume + :q WHERE id = :id"),
            {"q": quantity, "id": tank_id},
        )


def add_outgoing(date, oil_type_id, tank_id, quantity, buyer, notes):
    engine = get_engine()
    with engine.begin() as conn:
        current_volume = conn.execute(
            text("SELECT current_volume FROM tanks WHERE id = :id"), {"id": tank_id}
        ).scalar()
        if quantity > current_volume:
            raise ValueError(
                f"Cannot dispatch {quantity:g} — only {current_volume:g} available in this tank."
            )
        conn.execute(
            outgoing_transactions.insert().values(
                date=date, oil_type_id=oil_type_id, tank_id=tank_id,
                quantity=quantity, buyer=buyer, notes=notes,
            )
        )
        conn.execute(
            text("UPDATE tanks SET current_volume = current_volume - :q WHERE id = :id"),
            {"q": quantity, "id": tank_id},
        )


# ---------------------------------------------------------------------------
# Dashboard aggregates
# ---------------------------------------------------------------------------

def get_weighted_avg_rates() -> pd.DataFrame:
    """Weighted average purchase rate per oil type, from ALL historical inflows."""
    query = """
        SELECT o.id AS oil_type_id, o.name AS oil_type,
               SUM(i.quantity * i.rate) AS total_cost,
               SUM(i.quantity) AS total_quantity
        FROM incoming_transactions i
        JOIN oil_types o ON o.id = i.oil_type_id
        GROUP BY o.id, o.name
    """
    df = pd.read_sql(text(query), get_engine())
    if df.empty:
        return pd.DataFrame(columns=["oil_type_id", "oil_type", "total_cost",
                                     "total_quantity", "weighted_avg_rate"])
    df["weighted_avg_rate"] = df["total_cost"] / df["total_quantity"]
    return df


def get_stock_by_oil_type() -> pd.DataFrame:
    """Current stock, weighted average rate, and valuation per oil type."""
    stock = pd.read_sql(
        text(
            """
            SELECT o.id AS oil_type_id, o.name AS oil_type,
                   COALESCE(SUM(t.current_volume), 0) AS current_stock
            FROM oil_types o
            LEFT JOIN tanks t ON t.oil_type_id = o.id
            GROUP BY o.id, o.name
            ORDER BY o.name
            """
        ),
        get_engine(),
    )
    rates = get_weighted_avg_rates()[["oil_type_id", "weighted_avg_rate"]]
    merged = stock.merge(rates, on="oil_type_id", how="left")
    merged["weighted_avg_rate"] = merged["weighted_avg_rate"].fillna(0)
    merged["total_value"] = merged["current_stock"] * merged["weighted_avg_rate"]
    return merged


def get_stock_by_tank() -> pd.DataFrame:
    df = get_tanks()
    df["fill_pct"] = (df["current_volume"] / df["capacity"] * 100).round(1)
    return df


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------

def get_transactions(
    start_date=None,
    end_date=None,
    oil_type_id=None,
    tank_id=None,
    txn_type="All",
) -> pd.DataFrame:
    engine = get_engine()
    frames = []

    if txn_type in ("All", "In"):
        q = """
            SELECT i.date, 'In' AS type, o.name AS oil_type, t.name AS tank,
                   i.quantity, i.rate, i.supplier AS party, NULL AS notes
            FROM incoming_transactions i
            JOIN oil_types o ON o.id = i.oil_type_id
            JOIN tanks t ON t.id = i.tank_id
            WHERE 1=1
        """
        params = {}
        if start_date:
            q += " AND i.date >= :start"
            params["start"] = start_date
        if end_date:
            q += " AND i.date <= :end"
            params["end"] = end_date
        if oil_type_id:
            q += " AND i.oil_type_id = :oil"
            params["oil"] = oil_type_id
        if tank_id:
            q += " AND i.tank_id = :tank"
            params["tank"] = tank_id
        frames.append(pd.read_sql(text(q), engine, params=params))

    if txn_type in ("All", "Out"):
        q = """
            SELECT o2.date, 'Out' AS type, o.name AS oil_type, t.name AS tank,
                   o2.quantity, NULL AS rate, o2.buyer AS party, o2.notes AS notes
            FROM outgoing_transactions o2
            JOIN oil_types o ON o.id = o2.oil_type_id
            JOIN tanks t ON t.id = o2.tank_id
            WHERE 1=1
        """
        params = {}
        if start_date:
            q += " AND o2.date >= :start"
            params["start"] = start_date
        if end_date:
            q += " AND o2.date <= :end"
            params["end"] = end_date
        if oil_type_id:
            q += " AND o2.oil_type_id = :oil"
            params["oil"] = oil_type_id
        if tank_id:
            q += " AND o2.tank_id = :tank"
            params["tank"] = tank_id
        frames.append(pd.read_sql(text(q), engine, params=params))

    columns = ["date", "type", "oil_type", "tank", "quantity", "rate", "party", "notes"]
    frames = [f for f in frames if not f.empty]
    if not frames:
        return pd.DataFrame(columns=columns)

    for f in frames:
        f["rate"] = f["rate"].astype("float64")
        f["notes"] = f["notes"].astype("object")

    result = pd.concat(frames, ignore_index=True)
    return result[columns].sort_values("date", ascending=False).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Setup / management (oil types, tanks) and one-time reset
# ---------------------------------------------------------------------------

def add_oil_type(name):
    with get_engine().begin() as conn:
        conn.execute(oil_types.insert().values(name=name))


def delete_oil_type(oil_type_id):
    with get_engine().begin() as conn:
        used = conn.execute(
            text("SELECT COUNT(*) FROM tanks WHERE oil_type_id = :id"), {"id": oil_type_id}
        ).scalar()
        if used:
            raise ValueError("Cannot remove: some tanks still use this oil type. Remove those tanks first.")
        conn.execute(text("DELETE FROM oil_types WHERE id = :id"), {"id": oil_type_id})


def add_tank(name, oil_type_id, capacity):
    with get_engine().begin() as conn:
        conn.execute(
            tanks.insert().values(
                name=name, oil_type_id=oil_type_id, capacity=capacity, current_volume=0
            )
        )


def update_tank_capacity(tank_id, capacity):
    with get_engine().begin() as conn:
        conn.execute(text("UPDATE tanks SET capacity = :c WHERE id = :id"), {"c": capacity, "id": tank_id})


def delete_tank(tank_id):
    with get_engine().begin() as conn:
        vol = conn.execute(
            text("SELECT current_volume FROM tanks WHERE id = :id"), {"id": tank_id}
        ).scalar()
        if vol and vol > 0:
            raise ValueError("Cannot remove a tank that still holds stock. Dispatch/empty it first.")
        has_history = conn.execute(
            text(
                "SELECT (SELECT COUNT(*) FROM incoming_transactions WHERE tank_id = :id) + "
                "(SELECT COUNT(*) FROM outgoing_transactions WHERE tank_id = :id)"
            ),
            {"id": tank_id},
        ).scalar()
        if has_history:
            raise ValueError("Cannot remove a tank that has transaction history (this protects your records).")
        conn.execute(text("DELETE FROM tanks WHERE id = :id"), {"id": tank_id})
