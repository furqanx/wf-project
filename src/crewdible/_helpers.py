# src/crewdible/_helpers.py

from sqlalchemy import text
from src.transform._maps import (
    CREWDIBLE_WAREHOUSE_MAP,
    CREWDIBLE_MARKETPLACE_MAP,
    CREWDIBLE_STORE_MAP,
)


def create_temp_tables(conn):
    conn.execute(text("""
        CREATE TEMP TABLE IF NOT EXISTS _tmp_crewdible_warehouse_map (
            raw_name     TEXT,
            warehouse_id INT
        )
    """))
    conn.execute(text("""
        CREATE TEMP TABLE IF NOT EXISTS _tmp_crewdible_marketplace_map (
            raw_name       TEXT,
            marketplace_id INT
        )
    """))
    conn.execute(text("""
        CREATE TEMP TABLE IF NOT EXISTS _tmp_crewdible_store_map (
            raw_name TEXT,
            store_id INT
        )
    """))


def load_maps(conn):
    # Warehouse
    conn.execute(text("DELETE FROM _tmp_crewdible_warehouse_map"))
    res = conn.execute(text("SELECT warehouse_name, warehouse_id FROM public.dim_warehouse"))
    wh_db = {r[0]: r[1] for r in res.fetchall()}
    wh_rows = [{'raw_name': k, 'warehouse_id': wh_db[v]}
               for k, v in CREWDIBLE_WAREHOUSE_MAP.items() if v in wh_db]
    if wh_rows:
        conn.execute(text("INSERT INTO _tmp_crewdible_warehouse_map VALUES (:raw_name, :warehouse_id)"), wh_rows)

    # Marketplace
    conn.execute(text("DELETE FROM _tmp_crewdible_marketplace_map"))
    mp_rows = [{'raw_name': k, 'marketplace_id': v} for k, v in CREWDIBLE_MARKETPLACE_MAP.items()]
    if mp_rows:
        conn.execute(text("INSERT INTO _tmp_crewdible_marketplace_map VALUES (:raw_name, :marketplace_id)"), mp_rows)

    # Store
    conn.execute(text("DELETE FROM _tmp_crewdible_store_map"))
    res = conn.execute(text("SELECT nama_toko, store_id FROM public.dim_store"))
    st_db = {r[0]: r[1] for r in res.fetchall()}
    st_rows = [{'raw_name': k, 'store_id': st_db[v]}
               for k, v in CREWDIBLE_STORE_MAP.items() if v in st_db]
    if st_rows:
        conn.execute(text("INSERT INTO _tmp_crewdible_store_map VALUES (:raw_name, :store_id)"), st_rows)


def setup_maps(conn):
    create_temp_tables(conn)
    load_maps(conn)
