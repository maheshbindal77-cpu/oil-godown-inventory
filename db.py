"""Data layer for the oil godown inventory app.

Stock is tracked purely by OIL TYPE (no tanks): current stock of an oil type =
all inflows of that oil minus all outflows. Works against a cloud PostgreSQL
database (e.g. Neon) when a connection URL is provided via Streamlit secrets or
the DATABASE_URL environment variable, and falls back to a local SQLite file
otherwise so the app can be run locally for testing.
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

incoming_transactions = Table(
    "incoming_transactions", metadata,
    Column("id", Integer, primary_key=True),
    Column("date", String(20), nullable=False),
    Column("oil_type_id", Integer, ForeignKey("oil_types.id"), nullable=False),
    Column("quantity", Float, nullable=False),
    Column("rate", Float, nullable=False),
    Column("supplier", String(255)),
)

outgoing_transactions = Table(
    "outgoing_transactions", metadata,
    Column("id", Integer, primary_key=True),
    Column("date", String(20), nullable=False),
    Column("oil_type_id", Integer, ForeignKey("oil_types.id"), nullable=False),
    Column("quantity", Float, nullable=False),
    Column("buyer", String(255)),
    Column("notes", String(1000)),
)

# Small key/value table for one-off facts (e.g. whether sample data was seeded).
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


def _migrate_drop_tanks(conn):
    """Upgrade older databases that still have the tank concept: drop the
    tank_id columns and the tanks table. Existing oil types and transactions
    are preserved (they just lose the tank association). Safe to run every
    startup — it does nothing once the columns/table are gone."""
    dialect = conn.engine.dialect.name
    for tbl in ("incoming_transactions", "outgoing_transactions"):
        try:
            if dialect == "postgresql":
                conn.execute(text(f"ALTER TABLE {tbl} DROP COLUMN IF EXISTS tank_id"))
            else:  # sqlite
                cols = [r[1] for r in conn.execute(text(f"PRAGMA table_info({tbl})")).fetchall()]
                if "tank_id" in cols:
                    conn.execute(text(f"ALTER TABLE {tbl} DROP COLUMN tank_id"))
        except Exception:
            pass
    try:
        conn.execute(text("DROP TABLE IF EXISTS tanks"))
    except Exception:
        pass


def init_db():
    """Create tables if missing, upgrade older tank-based databases, and seed
    sample data only on the very first initialisation."""
    engine = get_engine()
    metadata.create_all(engine)
    need_seed = False
    with engine.begin() as conn:
        _migrate_drop_tanks(conn)
        seeded = conn.execute(text("SELECT value FROM app_meta WHERE key = 'seeded'")).scalar()
        if seeded is None:
            oil_count = conn.execute(text("SELECT COUNT(*) FROM oil_types")).scalar()
            need_seed = oil_count == 0
            conn.execute(app_meta.insert().values(key="seeded", value="yes"))
    if need_seed:
        _seed_sample_data()


def _seed_sample_data():
    with get_engine().begin() as conn:
        conn.execute(oil_types.insert().values(
            [{"name": "Furnace Oil"}, {"name": "LSFO"}, {"name": "Rubber Oil"}]
        ))
        ids = {r.name: r.id for r in conn.execute(text("SELECT id, name FROM oil_types")).fetchall()}

        incoming = [
            ("2026-05-01", "Furnace Oil", 20000, 45.0, "Supplier A - Batch FA101"),
            ("2026-06-01", "Furnace Oil", 10000, 47.0, "Supplier B - Batch FB204"),
            ("2026-05-10", "LSFO", 15000, 38.0, "Supplier D - Batch LD055"),
            ("2026-06-20", "LSFO", 10000, 40.0, "Supplier E - Batch LE087"),
            ("2026-05-15", "Rubber Oil", 12000, 55.0, "Supplier F - Batch RF012"),
            ("2026-07-01", "Rubber Oil", 5000, 58.0, "Supplier G - Batch RG045"),
        ]
        for date, oil, qty, rate, supplier in incoming:
            conn.execute(incoming_transactions.insert().values(
                date=date, oil_type_id=ids[oil], quantity=qty, rate=rate, supplier=supplier))

        outgoing = [
            ("2026-06-10", "Furnace Oil", 8000, "MH-12-AB-1234", "Regular delivery"),
            ("2026-06-25", "LSFO", 6000, "MH-14-CD-5678", "Regular delivery"),
            ("2026-07-10", "Rubber Oil", 4000, "MH-12-EF-9999", "Regular delivery"),
        ]
        for date, oil, qty, buyer, notes in outgoing:
            conn.execute(outgoing_transactions.insert().values(
                date=date, oil_type_id=ids[oil], quantity=qty, buyer=buyer, notes=notes))


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

def get_oil_types() -> pd.DataFrame:
    return pd.read_sql(text("SELECT id, name FROM oil_types ORDER BY name"), get_engine())


# ---------------------------------------------------------------------------
# Stock helpers
# ---------------------------------------------------------------------------

def _oil_type_stock(conn, oil_type_id) -> float:
    """Current stock of one oil type = all inflows − all outflows."""
    return conn.execute(
        text(
            "SELECT "
            "COALESCE((SELECT SUM(quantity) FROM incoming_transactions WHERE oil_type_id = :id), 0) - "
            "COALESCE((SELECT SUM(quantity) FROM outgoing_transactions WHERE oil_type_id = :id), 0)"
        ),
        {"id": oil_type_id},
    ).scalar()


def _validate_oil_stock(conn, oil_type_id):
    """Raise if an oil type's stock would go negative (more out than in)."""
    if oil_type_id is None:
        return
    stock = _oil_type_stock(conn, oil_type_id)
    if stock < -1e-6:
        name = conn.execute(
            text("SELECT name FROM oil_types WHERE id = :id"), {"id": oil_type_id}
        ).scalar()
        raise ValueError(
            f"This change would make {name} stock negative ({stock:g} L) — more would go out "
            "than exists. Fix the other entries for this oil type first."
        )


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------

def add_incoming(date, oil_type_id, quantity, rate, supplier):
    with get_engine().begin() as conn:
        conn.execute(incoming_transactions.insert().values(
            date=date, oil_type_id=oil_type_id, quantity=quantity, rate=rate, supplier=supplier))


def add_outgoing(date, oil_type_id, quantity, buyer, notes):
    with get_engine().begin() as conn:
        stock = _oil_type_stock(conn, oil_type_id)
        if quantity > stock:
            raise ValueError(
                f"Cannot dispatch {quantity:g} — only {stock:g} of this oil is currently in the godown."
            )
        conn.execute(outgoing_transactions.insert().values(
            date=date, oil_type_id=oil_type_id, quantity=quantity, buyer=buyer, notes=notes))


# ---------------------------------------------------------------------------
# Edit / delete individual entries
# ---------------------------------------------------------------------------

def get_editable_transactions(limit: int = 300) -> pd.DataFrame:
    engine = get_engine()
    inc = pd.read_sql(text(
        "SELECT i.id, 'In' AS type, i.date, i.oil_type_id, o.name AS oil_type, "
        "i.quantity, i.rate, i.supplier AS party "
        "FROM incoming_transactions i JOIN oil_types o ON o.id = i.oil_type_id"
    ), engine)
    out = pd.read_sql(text(
        "SELECT o2.id, 'Out' AS type, o2.date, o2.oil_type_id, o.name AS oil_type, "
        "o2.quantity, o2.buyer AS party, o2.notes "
        "FROM outgoing_transactions o2 JOIN oil_types o ON o.id = o2.oil_type_id"
    ), engine)
    if "notes" not in inc.columns:
        inc["notes"] = None
    if "rate" not in out.columns:
        out["rate"] = None
    cols = ["id", "type", "date", "oil_type_id", "oil_type", "quantity", "rate", "party", "notes"]
    frames = [d for d in (inc, out) if not d.empty]
    if not frames:
        return pd.DataFrame(columns=cols)
    for f in frames:
        f["rate"] = f["rate"].astype("float64")
        f["notes"] = f["notes"].astype("object")
    result = pd.concat([f[cols] for f in frames], ignore_index=True)
    return result.sort_values("date", ascending=False).head(limit).reset_index(drop=True)


def update_incoming(txn_id, date, oil_type_id, quantity, rate, supplier):
    with get_engine().begin() as conn:
        old_oil = conn.execute(
            text("SELECT oil_type_id FROM incoming_transactions WHERE id = :id"), {"id": txn_id}
        ).scalar()
        conn.execute(
            text("UPDATE incoming_transactions SET date = :d, oil_type_id = :o, "
                 "quantity = :q, rate = :r, supplier = :s WHERE id = :id"),
            {"d": date, "o": oil_type_id, "q": quantity, "r": rate, "s": supplier, "id": txn_id},
        )
        for oid in {old_oil, oil_type_id}:
            _validate_oil_stock(conn, oid)


def update_outgoing(txn_id, date, oil_type_id, quantity, buyer, notes):
    with get_engine().begin() as conn:
        old_oil = conn.execute(
            text("SELECT oil_type_id FROM outgoing_transactions WHERE id = :id"), {"id": txn_id}
        ).scalar()
        conn.execute(
            text("UPDATE outgoing_transactions SET date = :d, oil_type_id = :o, "
                 "quantity = :q, buyer = :b, notes = :n WHERE id = :id"),
            {"d": date, "o": oil_type_id, "q": quantity, "b": buyer, "n": notes, "id": txn_id},
        )
        for oid in {old_oil, oil_type_id}:
            _validate_oil_stock(conn, oid)


def delete_incoming(txn_id):
    with get_engine().begin() as conn:
        oil_id = conn.execute(
            text("SELECT oil_type_id FROM incoming_transactions WHERE id = :id"), {"id": txn_id}
        ).scalar()
        conn.execute(text("DELETE FROM incoming_transactions WHERE id = :id"), {"id": txn_id})
        _validate_oil_stock(conn, oil_id)


def delete_outgoing(txn_id):
    with get_engine().begin() as conn:
        oil_id = conn.execute(
            text("SELECT oil_type_id FROM outgoing_transactions WHERE id = :id"), {"id": txn_id}
        ).scalar()
        conn.execute(text("DELETE FROM outgoing_transactions WHERE id = :id"), {"id": txn_id})
        _validate_oil_stock(conn, oil_id)


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
    stock = pd.read_sql(text(
        "SELECT o.id AS oil_type_id, o.name AS oil_type, "
        "COALESCE((SELECT SUM(quantity) FROM incoming_transactions i WHERE i.oil_type_id = o.id), 0) - "
        "COALESCE((SELECT SUM(quantity) FROM outgoing_transactions x WHERE x.oil_type_id = o.id), 0) "
        "AS current_stock "
        "FROM oil_types o ORDER BY o.name"
    ), get_engine())
    rates = get_weighted_avg_rates()[["oil_type_id", "weighted_avg_rate"]]
    merged = stock.merge(rates, on="oil_type_id", how="left")
    merged["weighted_avg_rate"] = merged["weighted_avg_rate"].fillna(0)
    merged["total_value"] = merged["current_stock"] * merged["weighted_avg_rate"]
    return merged


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------

def get_transactions(start_date=None, end_date=None, oil_type_id=None, txn_type="All") -> pd.DataFrame:
    engine = get_engine()
    frames = []

    if txn_type in ("All", "In"):
        q = ("SELECT i.date, 'In' AS type, o.name AS oil_type, i.quantity, i.rate, "
             "i.supplier AS party, NULL AS notes "
             "FROM incoming_transactions i JOIN oil_types o ON o.id = i.oil_type_id WHERE 1=1")
        params = {}
        if start_date:
            q += " AND i.date >= :start"; params["start"] = start_date
        if end_date:
            q += " AND i.date <= :end"; params["end"] = end_date
        if oil_type_id:
            q += " AND i.oil_type_id = :oil"; params["oil"] = oil_type_id
        frames.append(pd.read_sql(text(q), engine, params=params))

    if txn_type in ("All", "Out"):
        q = ("SELECT o2.date, 'Out' AS type, o.name AS oil_type, o2.quantity, NULL AS rate, "
             "o2.buyer AS party, o2.notes AS notes "
             "FROM outgoing_transactions o2 JOIN oil_types o ON o.id = o2.oil_type_id WHERE 1=1")
        params = {}
        if start_date:
            q += " AND o2.date >= :start"; params["start"] = start_date
        if end_date:
            q += " AND o2.date <= :end"; params["end"] = end_date
        if oil_type_id:
            q += " AND o2.oil_type_id = :oil"; params["oil"] = oil_type_id
        frames.append(pd.read_sql(text(q), engine, params=params))

    columns = ["date", "type", "oil_type", "quantity", "rate", "party", "notes"]
    frames = [f for f in frames if not f.empty]
    if not frames:
        return pd.DataFrame(columns=columns)
    for f in frames:
        f["rate"] = f["rate"].astype("float64")
        f["notes"] = f["notes"].astype("object")
    result = pd.concat(frames, ignore_index=True)
    return result[columns].sort_values("date", ascending=False).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Setup / management (oil types)
# ---------------------------------------------------------------------------

def add_oil_type(name):
    with get_engine().begin() as conn:
        conn.execute(oil_types.insert().values(name=name))


def delete_oil_type(oil_type_id):
    with get_engine().begin() as conn:
        used = conn.execute(
            text("SELECT "
                 "(SELECT COUNT(*) FROM incoming_transactions WHERE oil_type_id = :id) + "
                 "(SELECT COUNT(*) FROM outgoing_transactions WHERE oil_type_id = :id)"),
            {"id": oil_type_id},
        ).scalar()
        if used:
            raise ValueError("Cannot remove: this oil type has transactions (this protects your records).")
        conn.execute(text("DELETE FROM oil_types WHERE id = :id"), {"id": oil_type_id})
