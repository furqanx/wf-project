# src/transform/_helpers.py
"""
Fungsi-fungsi shared yang digunakan oleh semua modul transform.
"""

from sqlalchemy import text
from src.db_config import logger
from src.transform._maps import (
    SHOPEE_CHANNEL_MAP, TIKTOK_CHANNEL_MAP, LAZADA_CHANNEL_MAP,
    SHOPEE_SHIPPING_MAP, TIKTOK_SHIPPING_MAP, LAZADA_SHIPPING_MAP,
)

MP_NAME = {
    'shopee':           'Shopee',
    'tiktok_tokopedia': 'TikTok-Tokopedia',
    'lazada':           'Lazada',
}


def create_temp_tables(conn):
    conn.execute(text("""
        CREATE TEMP TABLE IF NOT EXISTS _tmp_channel_map (
            nama_toko        TEXT,
            purchase_channel TEXT,
            sales_channel_id INT
        )
    """))
    conn.execute(text("""
        CREATE TEMP TABLE IF NOT EXISTS _tmp_warehouse_map (
            raw_name     TEXT,
            warehouse_id INT
        )
    """))
    conn.execute(text("""
        CREATE TEMP TABLE IF NOT EXISTS _tmp_shipping_map (
            provider         TEXT,
            delivery_option  TEXT,
            service_id       INT
        )
    """))


def load_channel_map(conn, marketplace):
    conn.execute(text("DELETE FROM _tmp_channel_map"))

    res = conn.execute(text("""
        SELECT sc.channel_name, sc.sales_channel_id
        FROM public.dim_sales_channel sc
        JOIN public.dim_marketplace mp ON mp.marketplace_id = sc.marketplace_id
        WHERE mp.nama_marketplace = :mp
    """), {'mp': MP_NAME[marketplace]})
    db_map = {r[0].lower(): r[1] for r in res.fetchall()}

    channel_maps = {
        'shopee':           SHOPEE_CHANNEL_MAP,
        'tiktok_tokopedia': TIKTOK_CHANNEL_MAP,
        'lazada':           LAZADA_CHANNEL_MAP,
    }
    rows = [
        {'nama_toko': nama_toko, 'purchase_channel': None, 'sales_channel_id': db_map.get(channel_name.lower())}
        for nama_toko, channel_name in channel_maps[marketplace].items()
        if db_map.get(channel_name.lower())
    ]
    if rows:
        conn.execute(text("INSERT INTO _tmp_channel_map VALUES (:nama_toko, :purchase_channel, :sales_channel_id)"), rows)


def load_warehouse_map(conn):
    conn.execute(text("DELETE FROM _tmp_warehouse_map"))
    res = conn.execute(text("SELECT warehouse_name, warehouse_id FROM public.dim_warehouse"))
    rows = [{'raw_name': r[0].lower(), 'warehouse_id': r[1]} for r in res.fetchall()]
    if rows:
        conn.execute(text("INSERT INTO _tmp_warehouse_map VALUES (:raw_name, :warehouse_id)"), rows)


def load_shipping_map(conn, marketplace):
    conn.execute(text("DELETE FROM _tmp_shipping_map"))

    if marketplace == 'shopee':
        rows = [{'provider': k, 'delivery_option': '_', 'service_id': v}
                for k, v in SHOPEE_SHIPPING_MAP.items()]
    elif marketplace == 'tiktok_tokopedia':
        rows = [{'provider': provider, 'delivery_option': option, 'service_id': sid}
                for (provider, option), sid in TIKTOK_SHIPPING_MAP.items()]
    elif marketplace == 'lazada':
        rows = [{'provider': k, 'delivery_option': '_', 'service_id': v}
                for k, v in LAZADA_SHIPPING_MAP.items()]
    else:
        rows = []

    if rows:
        conn.execute(text("INSERT INTO _tmp_shipping_map VALUES (:provider, :delivery_option, :service_id)"), rows)


def setup_maps(conn, marketplace):
    """Shortcut: buat temp tables + load semua map sekaligus."""
    create_temp_tables(conn)
    load_channel_map(conn, marketplace)
    load_warehouse_map(conn)
    load_shipping_map(conn, marketplace)
