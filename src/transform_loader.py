# src/transform_loader.py
"""
ETL Pipeline: Staging Tables → Main (Fact + Dimension) Tables

Dijalankan setelah fase ORDER/INCOME/REPORT selesai mengisi staging tables.
Pendekatan: SQL INSERT...SELECT via temp mapping tables — data tidak keluar ke Python.

Urutan eksekusi (penting — ada dependensi antar tabel):
    1. dim_customer
    2. fact_fulfillment_logistics
    3. fact_balance_transaction
    4. fact_returns_online
    5. fact_sales_online       (Phase 2 — sumber: stg_*_orders)
    6. fact_settlement         (Phase 2 — sumber: stg_*_income)
    7. fact_order_fees         (Phase 2 — sumber: stg_*_income, unpivot wide→narrow)
"""

import os

import pandas as pd
from sqlalchemy import text
from src.db_config import logger


# ============================================================
# MAPPING: nama_toko (staging) → channel_name (dim_sales_channel)
# ============================================================

SHOPEE_CHANNEL_MAP = {
    'official':                 'Shopee',
    'merapi':                   'Shopee-Merapi',
    'merapiorganik':            'Shopee-Merapi',
    'merapi organik':           'Shopee-Merapi',
    'diy':                      'Shopee-DIY-Jateng',
    'diy jateng':               'Shopee-DIY-Jateng',
    'wellfarm diy':             'Shopee-DIY-Jateng',
    'wellfarmdiyjateng':        'Shopee-DIY-Jateng',
    'porice':                   'Shopee-Porice-Official',
    'beras sehat':              'Shopee-Beras-Sehat',
    'berassehat':               'Shopee-Beras-Sehat',
    'bandar organik':           'Shopee-Bandar-Organik',
    'bandarorganik':            'Shopee-Bandar-Organik',
    'bandar organk':            'Shopee-Bandar-Organik',
    'bandar':                   'Shopee-Bandar-Organik',
    'lembah':                   'Shopee-Lembah-Organik',
    'lembah organik':           'Shopee-Lembah-Organik',
    'lembahorganik':            'Shopee-Lembah-Organik',
    'diabetashop':              'Shopee-Diabetashop',
    'diabetasop':               'Shopee-Diabetashop',
    'berasdiabetes':            'Shopee-Diabetashop',
    'truly':                    'Shopee-Truly-Organic',
    'truly organik':            'Shopee-Truly-Organic',
    'trulyorganik':             'Shopee-Truly-Organic',
    'merbabu':                  'Shopee-Merbabu-Organik',
    'merbabu organik':          'Shopee-Merbabu-Organik',
    'merbabuorganik':           'Shopee-Merbabu-Organik',
    'merababu':                 'Shopee-Merbabu-Organik',
    'merbau':                   'Shopee-Merbabu-Organik',
    'bromo':                    'Shopee-Bromo-Organik',
    'bromoorganik':             'Shopee-Bromo-Organik',
    'diet':                     'Shopee-Diet-Healthy-Corner',
    'diet healthy':             'Shopee-Diet-Healthy-Corner',
    'diethealthy':              'Shopee-Diet-Healthy-Corner',
    'diet healthy corner':      'Shopee-Diet-Healthy-Corner',
    'bogor':                    'Shopee-Bogor-Healthy-Store',
    'bogor healthy':            'Shopee-Bogor-Healthy-Store',
    'bogorhealthy':             'Shopee-Bogor-Healthy-Store',
    'bogorhealthystore':        'Shopee-Bogor-Healthy-Store',
    'bogor healhy':             'Shopee-Bogor-Healthy-Store',
    'basecamp':                 'Shopee-Basecamp-Organik',
    'basecamporganik':          'Shopee-Basecamp-Organik',
    'basecamp organik':         'Shopee-Basecamp-Organik',
    'owellnes':                 'Shopee-Owellnes',
    'owellness':                'Shopee-Owellnes',
    'sumber organik':           'Shopee-Sumber-Organik',
    'sumber organik shop':      'Shopee-Sumber-Organik',
    'sumberorganikshop':        'Shopee-Sumber-Organik',
    'solo':                     'Shopee-Solo-Organik',
    'solo organik':             'Shopee-Solo-Organik',
    'soloorganik':              'Shopee-Solo-Organik',
    'pusat beras':              'Shopee-Pusat-Beras-Berkualitas',
    'pusat beras berkualitas':  'Shopee-Pusat-Beras-Berkualitas',
    'pusat beras berkualita':   'Shopee-Pusat-Beras-Berkualitas',
    'pusatberasberkualitas':    'Shopee-Pusat-Beras-Berkualitas',
    'zona':                     'Shopee-Zona-Pangan-Sehat',
    'zona pangan':              'Shopee-Zona-Pangan-Sehat',
    'zonapangan':               'Shopee-Zona-Pangan-Sehat',
    'zonapangansehat':          'Shopee-Zona-Pangan-Sehat',
    'solusi':                   'Shopee-Solusi-Beras-Sehat',
    'solusi beras sehat':       'Shopee-Solusi-Beras-Sehat',
    'solusi beras seat':        'Shopee-Solusi-Beras-Sehat',
    'solusiberassehat':         'Shopee-Solusi-Beras-Sehat',
    'sumber pangan':            'Shopee-Sumber-Pangan-Pokok',
    'sumber pangan pokok':      'Shopee-Sumber-Pangan-Pokok',
    'sumberpanganpokok':        'Shopee-Sumber-Pangan-Pokok',
    'porang sachet':            'Shopee-Porang-Sachet-Store',
    'porang sachet store':      'Shopee-Porang-Sachet-Store',
    'porangsachetstore':        'Shopee-Porang-Sachet-Store',
    'porangsachet':             'Shopee-Porang-Sachet-Store',
    'indoporang':               'Shopee-Indo-Porang-Market',
    'indoporang market':        'Shopee-Indo-Porang-Market',
    'organic':                  'Shopee-Organic-Groceries',
    'organic groceries':        'Shopee-Organic-Groceries',
    'organicgroceries':         'Shopee-Organic-Groceries',
    'mekar':                    'Shopee-Mekar-Organik',
    'mekar organik':            'Shopee-Mekar-Organik',
    'mapan':                    'Shopee-Mapan-Organik',
    'mapan organik':            'Shopee-Mapan-Organik',
    'mapanorganik':             'Shopee-Mapan-Organik',
    'mapan oraganik':           'Shopee-Mapan-Organik',
    'medan':                    'Shopee-Medan-Organik',
    'medan organik':            'Shopee-Medan-Organik',
    'medanorganik':             'Shopee-Medan-Organik',
    # '-', 'unknown_store', 'pako' → NULL (tidak ada di dict)
}

# Key = (nama_toko, purchase_channel lowercase) → channel_name
TIKTOK_CHANNEL_MAP = {
    ('wellfarm id',     'tiktok'):    'Tiktok-WellFarmID',
    ('wellfarm id',     'tokopedia'): 'Tokopedia',
    ('wellfarm store',  'tiktok'):    'Tiktok-WellFarm-Store',
    ('wellfarm shop',   'tiktok'):    'Tiktok-WellFarm-Store',
    ('pundi',           'tiktok'):    'Tiktok-Pundi-Organik',
    ('beras organik id','tiktok'):    'Tiktok-Beras-OrganikID',
    ('organik id',      'tiktok'):    'Tiktok-Beras-OrganikID',
    ('merapi',          'tiktok'):    'Tiktok-Merapi-Organik',
    ('merapi organik',  'tiktok'):    'Tiktok-Merapi-Organik',
    ('merapi',          'tokopedia'): 'Tokopedia-Merapi',
    ('merapi organik',  'tokopedia'): 'Tokopedia-Merapi',
    ('beras sehat',     'tiktok'):    'Tiktok-Beras-Sehat-Shop',
    ('beras sehat',     'tokopedia'): 'Tokopedia-Beras-Sehat',
    ('bromo',           'tiktok'):    'Tiktok-Bromo-Organik',
    ('owellness',       'tiktok'):    'Tiktok-Owellness',
    ('porice',          'tokopedia'): 'Tokopedia-Porice-Official',
    ('diy jateng',      'tiktok'):    'Tokopedia-DIY-Jateng',
    ('diy jateng',      'tokopedia'): 'Tokopedia-DIY-Jateng',
    ('diy',             'tiktok'):    'Tokopedia-DIY-Jateng',
    ('diy',             'tokopedia'): 'Tokopedia-DIY-Jateng',
    # Tidak ada channel untuk: basecamp, bogor/bogor healthy, pundi Tokopedia,
    # beras organik id Tokopedia, porice TikTok → sales_channel_id = NULL
}

LAZADA_CHANNEL_MAP = {
    'official':    'Lazada-Wellfarm',
    'merapi':      'Lazada-Merapi-Organik',
    'beras sehat': 'Lazada-Beras-Sehat-Organik',
}


# ============================================================
# MAPPING: warehouse raw value → warehouse_name (dim_warehouse)
# ============================================================

SHOPEE_WAREHOUSE_MAP = {
    'amerta warehose':   'Amerta',
    'gudang hb riau':    'Harapan Indah Riau',
    'mavisha storage':   'Mavisha',
    'seller space bo':   'Sellerspace',
    'store n go':        'Store n Go',
    'store n go 1':      'Store n Go',
}

TIKTOK_WAREHOUSE_MAP = {
    'aghitsna':                         'Aghitsna',
    'athena':                           'Athena',
    'athena warehouse':                 'Athena',
    'crewdible kalicari':               'Kalicari',
    'gravitywarehouse wellfarm':        'Gravity',
    'gudang amerta':                    'Amerta',
    'hirota new':                       'Hirota',
    'hirota new fullfilmen':            'Hirota',
    'kapuk muara warehouse':            'Kapuk Muara',
    'malang':                           'Malang Warehouse',
    'mavisa':                           'Mavisha',
    'mavisha storage':                  'Mavisha',
    'mavisha storage jaktim':           'Mavisha',
    'seller space x merapi organik':    'Sellerspace',
    'store n go':                       'Store n Go',
    'stor n go':                        'Store n Go',
    # 'shop location' → NULL
}

LAZADA_WAREHOUSE_MAP = {
    'gudang mavisa':   'Mavisha',
    'mavisha storage': 'Mavisha',
}


# ============================================================
# MAPPING: raw shipping value → shipping_service_id (dim_shipping_service)
# ============================================================

# Shopee: parse opsi_pengiriman → ambil bagian setelah '-' pertama
SHOPEE_SHIPPING_MAP = {
    'SPX Hemat':                        16,
    'SPX Standard':                     15,
    'SiCepat REG':                      7,
    'SPX Sameday':                      17,
    'Anteraja Economy':                 12,
    'SPX Instant (Versi Lama)':         18,
    'SPX Instant':                      18,
    'SPX Instant Prioritas':            18,
    'SiCepat Halu':                     9,
    'Anteraja Reguler':                 11,
    'Sicepat Gokil':                    9,
    'ID Express':                       24,
    'JNE Trucking (JTR)':               3,
    'J&T Cargo':                        6,
    'J&T Express':                      4,
    'GrabExpress Sameday':              22,
    'JNE Reguler':                      1,
    'J&T Economy':                      5,
    'GoSend Same Day':                  20,
    'Anteraja Cargo':                   14,
    'Anteraja Sameday':                 13,
    'GrabExpress Instant':              21,
    'GrabExpress Instant (Versi Lama)': 21,
    'GrabExpress Instant Prioritas':    21,
    'Gosend Instant':                   19,
    'GoSend Instant (Versi Lama)':      19,
    'GoSend Instant Prioritas':         19,
    'Ninja Xpress':                     23,
    'JNE YES':                          2,
    'Sicepat BEST':                     8,
    'Sentral Cargo':                    25,
    'Pos Reguler':                      29,
}

# TikTok: key = (shipping_provider_name, delivery_option)
# '_' = wildcard (cocok untuk semua delivery_option dari provider tersebut)
TIKTOK_SHIPPING_MAP = {
    ('Anteraja',              'Kargo'):                14,
    ('Anteraja',              'Same day'):             13,
    ('Anteraja',              'Ekonomi'):              12,
    ('AnterAja-MP',           'AnterAja (Regular)'):   11,
    ('Gojek',                 'Instan'):               19,
    ('Gojek',                 'Same day 8 jam'):       20,
    ('Grab',                  'Instan'):               21,
    ('Grab',                  'Same day 8 jam'):       22,
    ('IDX',                   'Pengiriman standar'):   24,
    ('JNE Cargo',             'Kargo'):                3,
    ('JNE Express Standard ID','_'):                   1,
    ('JNE-MP',                'JNE (Regular)'):        1,
    ('J&T Cargo',             'Kargo'):                6,
    ('J&T Cargo',             'Pengiriman standar'):   6,
    ('J&T Express',           'Pengiriman standar'):   4,
    ('J&T Express',           'Ekonomi'):              5,
    ('J&T-MP',                'J&T (Regular)'):        4,
    ('Lion Parcel-MP',        '_'):                    26,
    ('NinjaVan Indonesia',    '_'):                    23,
    ('NinjaVan-MP',           '_'):                    23,
    ('Paxel',                 'Same day'):             27,
    ('REX',                   'Kargo'):                28,
    ('SiCepat',               'Kargo'):                10,
    ('SiCepat-MP',            'SiCepat (Regular)'):    7,
}

LAZADA_SHIPPING_MAP = {
    'JNE':       1,
    'JNE JTR':   3,
    'J&T':       4,
    'J&T CARGO': 6,
    'LEX ID':    30,
    'NinjaVanID':23,
}


# ============================================================
# MAPPING CREWDIBLE: raw values → dim table lookups
# Key selalu lowercase — JOIN memakai LOWER(TRIM(kolom))
# Tambahkan entri baru sesuai variasi yang muncul di data.
# ============================================================

CREWDIBLE_WAREHOUSE_MAP = {
    # Crewdible gudang → dim_warehouse.warehouse_name
    'crewdible kalicari':           'Kalicari',
    'crewdible gudang solo':        'Gudang Solo',
    'kalicari':                     'Kalicari',
    'gudang solo':                  'Gudang Solo',
    'athena':                       'Athena',
    'athena warehouse':             'Athena',
    'mavisha':                      'Mavisha',
    'mavisha storage':              'Mavisha',
    'mavisha storage jaktim':       'Mavisha',
    'gravity':                      'Gravity',
    'gravitywarehouse wellfarm':    'Gravity',
    'amerta':                       'Amerta',
    'gudang amerta':                'Amerta',
    'store n go':                   'Store n Go',
    'store n go 1':                 'Store n Go',
    'kapuk muara':                  'Kapuk Muara',
    'kapuk muara warehouse':        'Kapuk Muara',
    'aghitsna':                     'Aghitsna',
    'sellerspace':                  'Sellerspace',
    'seller space':                 'Sellerspace',
    'hirota':                       'Hirota',
    'hirota new':                   'Hirota',
    'hd warehouse':                 'HD Warehouse',
    'ar galaxy':                    'AR Galaxy',
    'uju bandung':                  'Uju Bandung',
    'malang':                       'Malang Warehouse',
    'malang warehouse':             'Malang Warehouse',
    'hea':                          'HEA Fullfilment',
    'hea fulfilment':               'HEA Fullfilment',
    'harapan indah':                'Harapan Indah Riau',
    'harapan indah riau':           'Harapan Indah Riau',
    'cd warehouse':                 'CD Warehouse',
    'gudang dc jogja':              'Gudang DC Jogja',
    'basecamp':                     'Gudang DC Jogja',
}

CREWDIBLE_MARKETPLACE_MAP = {
    # nama_marketplace (lowercase) → dim_marketplace.marketplace_id
    'shopee':           1,
    'tiktok shop':      2,
    'tiktok':           2,
    'tokopedia':        3,
    'lazada':           4,
    'tiktok-tokopedia': 5,
}

CREWDIBLE_STORE_MAP = {
    # nama_toko (lowercase) → dim_store.nama_toko
    'wellfarm':                     'Wellfarm Official',
    'wellfarm official':            'Wellfarm Official',
    'wellfarm id':                  'Wellfarm ID',
    'wellfarm store':               'Wellfarm Store',
    'merapi':                       'Merapi Organik',
    'merapi organik':               'Merapi Organik',
    'diy':                          'Wellfarm DIY Jateng',
    'diy jateng':                   'Wellfarm DIY Jateng',
    'wellfarm diy':                 'Wellfarm DIY Jateng',
    'wellfarm diy jateng':          'Wellfarm DIY Jateng',
    'porice':                       'Porice Official',
    'porice official':              'Porice Official',
    'beras sehat':                  'Beras Sehat',
    'bandar organik':               'Bandar Organik',
    'lembah organik':               'Lembah Organik',
    'diabetashop':                  'Diabetashop',
    'truly organik':                'Truly Organik',
    'truly organic':                'Truly Organik',
    'merbabu organik':              'Merbabu Organik',
    'bromo organik':                'Bromo Organik',
    'bromo':                        'Bromo Organik',
    'diet healthy corner':          'Diet Healthy Corner',
    'bogor healthy store':          'Bogor Healthy Store',
    'basecamp organik':             'Basecamp Organik',
    'owellness':                    'Owellness',
    'owellnes':                     'Owellness',
    'sumber organik':               'Sumber Organik',
    'solo organik':                 'Solo Organik',
    'pusat beras berkualitas':      'Pusat Beras Berkualitas',
    'zona pangan sehat':            'Zona Pangan Sehat',
    'solusi beras sehat':           'Solusi Beras Sehat',
    'sumber pangan pokok':          'Sumber Pangan Pokok',
    'porang sachet store':          'Porang Sachet Store',
    'porang sachet':                'Porang Sachet Store',
    'indo porang market':           'Indo Porang Market',
    'organic groceries':            'Organic Groceries',
    'mekar organik':                'Mekar Organik',
    'mapan organik':                'Mapan Organik',
    'medan organik':                'Medan Organik',
    'pundi organik':                'Pundi Organik',
    'pundi':                        'Pundi Organik',
    'beras organik id':             'Beras Organik ID',
}


# ============================================================
# HELPER: Buat temp mapping tables
# ============================================================

def _create_temp_tables(conn):
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
            provider        TEXT,
            delivery_option TEXT,
            service_id      INT
        )
    """))


def _load_channel_map(conn, marketplace):
    conn.execute(text("DELETE FROM _tmp_channel_map"))

    # Ambil ID aktual dari database
    res = conn.execute(text("SELECT channel_name, sales_channel_id FROM dim_sales_channel"))
    db_map = {r[0]: r[1] for r in res.fetchall()}

    rows = []
    if marketplace == 'shopee':
        for nama_toko, channel_name in SHOPEE_CHANNEL_MAP.items():
            cid = db_map.get(channel_name)
            if cid:
                rows.append({'nama_toko': nama_toko, 'purchase_channel': None, 'sales_channel_id': cid})

    elif marketplace == 'tiktok_tokopedia':
        for (nama_toko, pc), channel_name in TIKTOK_CHANNEL_MAP.items():
            cid = db_map.get(channel_name)
            if cid:
                rows.append({'nama_toko': nama_toko, 'purchase_channel': pc, 'sales_channel_id': cid})

    elif marketplace == 'lazada':
        for nama_toko, channel_name in LAZADA_CHANNEL_MAP.items():
            cid = db_map.get(channel_name)
            if cid:
                rows.append({'nama_toko': nama_toko, 'purchase_channel': None, 'sales_channel_id': cid})

    if rows:
        conn.execute(
            text("INSERT INTO _tmp_channel_map VALUES (:nama_toko, :purchase_channel, :sales_channel_id)"),
            rows
        )


def _load_warehouse_map(conn, marketplace):
    conn.execute(text("DELETE FROM _tmp_warehouse_map"))

    res = conn.execute(text("SELECT warehouse_name, warehouse_id FROM dim_warehouse"))
    db_map = {r[0]: r[1] for r in res.fetchall()}

    source = {
        'shopee':         SHOPEE_WAREHOUSE_MAP,
        'tiktok_tokopedia': TIKTOK_WAREHOUSE_MAP,
        'lazada':         LAZADA_WAREHOUSE_MAP,
    }.get(marketplace, {})

    rows = []
    for raw_name, wh_name in source.items():
        wid = db_map.get(wh_name)
        if wid:
            rows.append({'raw_name': raw_name, 'warehouse_id': wid})

    if rows:
        conn.execute(
            text("INSERT INTO _tmp_warehouse_map VALUES (:raw_name, :warehouse_id)"),
            rows
        )


def _load_shipping_map(conn, marketplace):
    conn.execute(text("DELETE FROM _tmp_shipping_map"))

    rows = []
    if marketplace == 'shopee':
        for service_name, service_id in SHOPEE_SHIPPING_MAP.items():
            rows.append({'provider': service_name, 'delivery_option': '_', 'service_id': service_id})

    elif marketplace == 'tiktok_tokopedia':
        for (provider, option), service_id in TIKTOK_SHIPPING_MAP.items():
            rows.append({'provider': provider, 'delivery_option': option, 'service_id': service_id})

    elif marketplace == 'lazada':
        for provider, service_id in LAZADA_SHIPPING_MAP.items():
            rows.append({'provider': provider, 'delivery_option': '_', 'service_id': service_id})

    if rows:
        conn.execute(
            text("INSERT INTO _tmp_shipping_map VALUES (:provider, :delivery_option, :service_id)"),
            rows
        )


# ============================================================
# HELPER: Temp tables & loader khusus CREWDIBLE
# ============================================================

def _create_crewdible_temp_tables(conn):
    conn.execute(text("""
        CREATE TEMP TABLE IF NOT EXISTS _tmp_crewdible_warehouse_map (
            raw_name     TEXT,
            warehouse_id INT
        )
    """))
    conn.execute(text("""
        CREATE TEMP TABLE IF NOT EXISTS _tmp_crewdible_marketplace_map (
            raw_name        TEXT,
            marketplace_id  INT
        )
    """))
    conn.execute(text("""
        CREATE TEMP TABLE IF NOT EXISTS _tmp_crewdible_store_map (
            raw_name  TEXT,
            store_id  INT
        )
    """))


def _load_crewdible_maps(conn):
    # --- Warehouse ---
    conn.execute(text("DELETE FROM _tmp_crewdible_warehouse_map"))
    res = conn.execute(text("SELECT warehouse_name, warehouse_id FROM dim_warehouse"))
    wh_db = {r[0]: r[1] for r in res.fetchall()}
    wh_rows = []
    for raw, wh_name in CREWDIBLE_WAREHOUSE_MAP.items():
        wid = wh_db.get(wh_name)
        if wid:
            wh_rows.append({'raw_name': raw, 'warehouse_id': wid})
    if wh_rows:
        conn.execute(
            text("INSERT INTO _tmp_crewdible_warehouse_map VALUES (:raw_name, :warehouse_id)"),
            wh_rows
        )

    # --- Marketplace ---
    conn.execute(text("DELETE FROM _tmp_crewdible_marketplace_map"))
    mp_rows = [{'raw_name': k, 'marketplace_id': v} for k, v in CREWDIBLE_MARKETPLACE_MAP.items()]
    if mp_rows:
        conn.execute(
            text("INSERT INTO _tmp_crewdible_marketplace_map VALUES (:raw_name, :marketplace_id)"),
            mp_rows
        )

    # --- Store ---
    conn.execute(text("DELETE FROM _tmp_crewdible_store_map"))
    res = conn.execute(text("SELECT nama_toko, store_id FROM dim_store"))
    st_db = {r[0]: r[1] for r in res.fetchall()}
    st_rows = []
    for raw, st_name in CREWDIBLE_STORE_MAP.items():
        sid = st_db.get(st_name)
        if sid:
            st_rows.append({'raw_name': raw, 'store_id': sid})
    if st_rows:
        conn.execute(
            text("INSERT INTO _tmp_crewdible_store_map VALUES (:raw_name, :store_id)"),
            st_rows
        )


# ============================================================
# TRANSFORM 1: dim_customer (AMAN UNTUK DIJALANKAN)
# ============================================================

def transform_dim_customer(engine, marketplace):
    logger.info(f"[TRANSFORM] dim_customer ← {marketplace}")
    try:
        with engine.begin() as conn:
            _create_temp_tables(conn)
            _load_channel_map(conn, marketplace)

            if marketplace == 'shopee':
                sql = text("""
                    INSERT INTO dim_customer (marketplace_id, username, nama_penerima, no_telepon, provinsi, kota_kabupaten)
                        SELECT DISTINCT ON (o.username_pembeli)
                            1,
                            o.username_pembeli,
                            o.nama_penerima,
                            o.no_telepon,
                            o.provinsi,
                            o.kota_kabupaten
                        FROM stg_shopee_orders o
                        WHERE o.username_pembeli IS NOT NULL AND o.username_pembeli NOT IN ('nan', '')
                        ORDER BY o.username_pembeli, o.waktu_pesanan_dibuat DESC NULLS LAST
                    ON CONFLICT (marketplace_id, username) DO UPDATE SET
                        nama_penerima  = EXCLUDED.nama_penerima,
                        no_telepon     = EXCLUDED.no_telepon,
                        provinsi       = EXCLUDED.provinsi,
                        kota_kabupaten = EXCLUDED.kota_kabupaten
                """)

            elif marketplace == 'tiktok_tokopedia':
                sql = text("""
                    INSERT INTO dim_customer (marketplace_id, username, nama_penerima, no_telepon, provinsi, kota_kabupaten, kecamatan)
                        SELECT DISTINCT ON (o.buyer_username)
                            5,
                            o.buyer_username,
                            o.recipient,
                            o.phone_number,
                            o.province,
                            o.regency_and_city,
                            o.districts
                        FROM stg_tiktok_tokopedia_orders o
                        WHERE o.buyer_username IS NOT NULL AND o.buyer_username NOT IN ('nan', '')
                        ORDER BY o.buyer_username, o.created_time DESC NULLS LAST
                    ON CONFLICT (marketplace_id, username) DO UPDATE SET
                        nama_penerima  = EXCLUDED.nama_penerima,
                        no_telepon     = EXCLUDED.no_telepon,
                        provinsi       = EXCLUDED.provinsi,
                        kota_kabupaten = EXCLUDED.kota_kabupaten,
                        kecamatan      = EXCLUDED.kecamatan
                """)

            elif marketplace == 'lazada':
                sql = text("""
                    INSERT INTO dim_customer (marketplace_id, username, nama_penerima, email, no_telepon, provinsi, kota_kabupaten, kode_pos)
                        SELECT DISTINCT ON (o.customer_name)
                            4,
                            o.customer_name,
                            o.shipping_name,
                            NULLIF(o.customer_email, 'nan'),
                            o.shipping_phone,
                            o.shipping_region,
                            o.shipping_city,
                            NULLIF(o.shipping_post_code, 'nan')
                        FROM stg_lazada_orders o
                        WHERE o.customer_name IS NOT NULL AND o.customer_name NOT IN ('nan', '')
                        ORDER BY o.customer_name, o.create_time DESC NULLS LAST
                    ON CONFLICT (marketplace_id, username) DO UPDATE SET
                        nama_penerima  = EXCLUDED.nama_penerima,
                        email          = EXCLUDED.email,
                        no_telepon     = EXCLUDED.no_telepon,
                        provinsi       = EXCLUDED.provinsi,
                        kota_kabupaten = EXCLUDED.kota_kabupaten,
                        kode_pos       = EXCLUDED.kode_pos
                """)
            else:
                logger.warning(f"Marketplace '{marketplace}' tidak dikenal untuk dim_customer.")
                return

            result = conn.execute(sql)
            logger.info(f"✅ dim_customer: {result.rowcount} baris diproses untuk {marketplace}")

    except Exception as e:
        logger.error(f"❌ dim_customer gagal untuk {marketplace}: {e}")


# ============================================================
# TRANSFORM 2: fact_fulfillment_logistics
# ============================================================

def transform_fact_fulfillment_logistics(engine, marketplace):
    logger.info(f"[TRANSFORM] fact_fulfillment_logistics ← {marketplace}")
    try:
        with engine.begin() as conn:
            _create_temp_tables(conn)
            _load_channel_map(conn, marketplace)
            _load_warehouse_map(conn, marketplace)
            _load_shipping_map(conn, marketplace)

            if marketplace == 'shopee':
                sql = text("""
                    INSERT INTO fact_fulfillment_logistics (
                        order_id, 
                        sales_channel_id, 
                        shipping_service_id, 
                        warehouse_id,
                        sla_status_id, 
                        tracking_id, 
                        weight_kg,
                        handover_type, 
                        is_dropship,
                        time_created, 
                        time_paid, 
                        time_rts,
                        time_delivered,
                        created_date_id, 
                        delivered_date_id,
                        source_marketplace, 
                        source_filename
                    )
                        SELECT
                            o.no_pesanan,
                            cm.sales_channel_id,
                            sm.service_id,
                            wm.warehouse_id,
                            5,   -- Shopee tidak punya time_shipped → Data Tidak Tersedia
                            NULLIF(TRIM(o.no_resi), 'nan'),
                            CASE WHEN NULLIF(NULLIF(TRIM(o.total_berat), 'nan'), '') IS NOT NULL
                                    AND NULLIF(REGEXP_REPLACE(TRIM(o.total_berat), '[^0-9.]', '', 'g'), '') IS NOT NULL
                                THEN CASE
                                        WHEN LOWER(TRIM(o.total_berat)) LIKE '%kg%'
                                        THEN REGEXP_REPLACE(TRIM(o.total_berat), '[^0-9.]', '', 'g')::NUMERIC
                                        ELSE REGEXP_REPLACE(TRIM(o.total_berat), '[^0-9.]', '', 'g')::NUMERIC / 1000
                                    END
                                ELSE NULL END,
                            CASE TRIM(o.antar_ke_counter_pickup)
                                WHEN 'Antar ke Counter' THEN 'Antar ke Counter'
                                ELSE 'Pickup'
                            END,
                            FALSE,
                            CASE WHEN NULLIF(NULLIF(NULLIF(TRIM(o.waktu_pesanan_dibuat), 'nan'), ''), '-') IS NOT NULL
                                THEN TO_TIMESTAMP(TRIM(o.waktu_pesanan_dibuat), 'YYYY-MM-DD HH24:MI') END,
                            CASE WHEN NULLIF(NULLIF(NULLIF(TRIM(o.waktu_pembayaran_dilakukan), 'nan'), ''), '-') IS NOT NULL
                                THEN TO_TIMESTAMP(TRIM(o.waktu_pembayaran_dilakukan), 'YYYY-MM-DD HH24:MI') END,
                            CASE WHEN NULLIF(NULLIF(NULLIF(TRIM(o.waktu_pengiriman_diatur), 'nan'), ''), '-') IS NOT NULL
                                THEN TO_TIMESTAMP(TRIM(o.waktu_pengiriman_diatur), 'YYYY-MM-DD HH24:MI') END,
                            CASE WHEN NULLIF(NULLIF(NULLIF(TRIM(o.waktu_pesanan_selesai), 'nan'), ''), '-') IS NOT NULL
                                THEN TO_TIMESTAMP(TRIM(o.waktu_pesanan_selesai), 'YYYY-MM-DD HH24:MI') END,
                            CASE WHEN NULLIF(NULLIF(NULLIF(TRIM(o.waktu_pesanan_dibuat), 'nan'), ''), '-') IS NOT NULL
                                THEN CAST(TO_CHAR(TO_DATE(TRIM(o.waktu_pesanan_dibuat), 'YYYY-MM-DD'), 'YYYYMMDD') AS INT) END,
                            CASE WHEN NULLIF(NULLIF(NULLIF(TRIM(o.waktu_pesanan_selesai), 'nan'), ''), '-') IS NOT NULL
                                THEN CAST(TO_CHAR(TO_DATE(TRIM(o.waktu_pesanan_selesai), 'YYYY-MM-DD'), 'YYYYMMDD') AS INT) END,
                            'shopee',
                            o.source_filename
                        FROM stg_shopee_orders o
                        LEFT JOIN _tmp_channel_map cm  ON cm.nama_toko = o.nama_toko
                        LEFT JOIN _tmp_warehouse_map wm ON wm.raw_name = LOWER(TRIM(o.nama_gudang))
                        LEFT JOIN _tmp_shipping_map sm  ON sm.provider = CASE
                            WHEN o.opsi_pengiriman LIKE '%-%'
                            THEN TRIM(SUBSTRING(o.opsi_pengiriman FROM STRPOS(o.opsi_pengiriman, '-') + 1))
                            ELSE TRIM(o.opsi_pengiriman)
                        END
                        WHERE cm.sales_channel_id IS NOT NULL
                    ON CONFLICT (order_id, sales_channel_id) DO NOTHING
                """)

            elif marketplace == 'tiktok_tokopedia':
                sql = text("""
                    INSERT INTO fact_fulfillment_logistics (
                        order_id, sales_channel_id, shipping_service_id, warehouse_id,
                        sla_status_id, tracking_id, package_id, weight_kg,
                        distance_fee, handover_type, is_dropship,
                        time_created, time_paid, time_rts, time_shipped, time_delivered,
                        created_date_id, shipped_date_id, delivered_date_id,
                        source_marketplace, source_filename
                    )
                    SELECT
                        o.order_id,
                        cm.sales_channel_id,
                        COALESCE(
                            sm_exact.service_id,
                            sm_wild.service_id
                        ),
                        wm.warehouse_id,
                        CASE
                            WHEN NULLIF(NULLIF(TRIM(o.rts_time), 'nan'), '') IS NULL
                              OR NULLIF(NULLIF(TRIM(o.shipped_time), 'nan'), '') IS NULL THEN 5
                            WHEN TO_TIMESTAMP(TRIM(o.shipped_time), 'DD/MM/YYYY HH24:MI:SS')
                               < TO_TIMESTAMP(TRIM(o.rts_time), 'DD/MM/YYYY HH24:MI:SS') THEN 1
                            WHEN DATE(TO_TIMESTAMP(TRIM(o.shipped_time), 'DD/MM/YYYY HH24:MI:SS'))
                               = DATE(TO_TIMESTAMP(TRIM(o.rts_time), 'DD/MM/YYYY HH24:MI:SS')) THEN 2
                            WHEN TO_TIMESTAMP(TRIM(o.shipped_time), 'DD/MM/YYYY HH24:MI:SS')
                               - TO_TIMESTAMP(TRIM(o.rts_time), 'DD/MM/YYYY HH24:MI:SS')
                               <= INTERVAL '1 day' THEN 3
                            ELSE 4
                        END,
                        NULLIF(TRIM(o.tracking_id), 'nan'),
                        NULLIF(TRIM(o.package_id), 'nan'),
                        CASE WHEN NULLIF(TRIM(o.weight_kg), 'nan') IS NOT NULL
                             THEN NULLIF(TRIM(o.weight_kg), '')::NUMERIC ELSE NULL END,
                        (COALESCE(NULLIF(TRIM(o.distance_fee),          '0')::NUMERIC, 0)
                       + COALESCE(NULLIF(TRIM(o.distance_shipping_fee), '0')::NUMERIC, 0)),
                        'Pickup',
                        FALSE,
                        CASE WHEN NULLIF(NULLIF(TRIM(o.created_time), 'nan'), '') IS NOT NULL
                             THEN TO_TIMESTAMP(TRIM(o.created_time), 'DD/MM/YYYY HH24:MI:SS') END,
                        CASE WHEN NULLIF(NULLIF(TRIM(o.paid_time), 'nan'), '') IS NOT NULL
                             THEN TO_TIMESTAMP(TRIM(o.paid_time), 'DD/MM/YYYY HH24:MI:SS') END,
                        CASE WHEN NULLIF(NULLIF(TRIM(o.rts_time), 'nan'), '') IS NOT NULL
                             THEN TO_TIMESTAMP(TRIM(o.rts_time), 'DD/MM/YYYY HH24:MI:SS') END,
                        CASE WHEN NULLIF(NULLIF(TRIM(o.shipped_time), 'nan'), '') IS NOT NULL
                             THEN TO_TIMESTAMP(TRIM(o.shipped_time), 'DD/MM/YYYY HH24:MI:SS') END,
                        CASE WHEN NULLIF(NULLIF(TRIM(o.delivered_time), 'nan'), '') IS NOT NULL
                             THEN TO_TIMESTAMP(TRIM(o.delivered_time), 'DD/MM/YYYY HH24:MI:SS') END,
                        CASE WHEN NULLIF(NULLIF(TRIM(o.created_time), 'nan'), '') IS NOT NULL
                             THEN CAST(TO_CHAR(TO_TIMESTAMP(TRIM(o.created_time), 'DD/MM/YYYY HH24:MI:SS')::DATE, 'YYYYMMDD') AS INT) END,
                        CASE WHEN NULLIF(NULLIF(TRIM(o.shipped_time), 'nan'), '') IS NOT NULL
                             THEN CAST(TO_CHAR(TO_TIMESTAMP(TRIM(o.shipped_time), 'DD/MM/YYYY HH24:MI:SS')::DATE, 'YYYYMMDD') AS INT) END,
                        CASE WHEN NULLIF(NULLIF(TRIM(o.delivered_time), 'nan'), '') IS NOT NULL
                             THEN CAST(TO_CHAR(TO_TIMESTAMP(TRIM(o.delivered_time), 'DD/MM/YYYY HH24:MI:SS')::DATE, 'YYYYMMDD') AS INT) END,
                        'tiktok_tokopedia',
                        o.source_filename
                    FROM stg_tiktok_tokopedia_orders o
                    LEFT JOIN _tmp_channel_map cm ON cm.nama_toko = o.nama_toko
                        AND LOWER(cm.purchase_channel) = LOWER(NULLIF(TRIM(o.purchase_channel), 'nan'))
                    LEFT JOIN _tmp_warehouse_map wm ON wm.raw_name = LOWER(TRIM(o.warehouse_name))
                    -- Coba exact match (provider + delivery_option) dulu
                    LEFT JOIN _tmp_shipping_map sm_exact
                        ON sm_exact.provider = TRIM(o.shipping_provider_name)
                        AND sm_exact.delivery_option = TRIM(o.delivery_option)
                    -- Fallback ke wildcard (provider saja)
                    LEFT JOIN _tmp_shipping_map sm_wild
                        ON sm_wild.provider = TRIM(o.shipping_provider_name)
                        AND sm_wild.delivery_option = '_'
                    WHERE cm.sales_channel_id IS NOT NULL
                    ON CONFLICT (order_id, sales_channel_id) DO NOTHING
                """)

            elif marketplace == 'lazada':
                sql = text("""
                    INSERT INTO fact_fulfillment_logistics (
                        order_id, sales_channel_id, shipping_service_id, warehouse_id,
                        sla_status_id, tracking_id,
                        handover_type, is_dropship,
                        time_created, target_shipped_time, time_delivered,
                        created_date_id, delivered_date_id,
                        source_marketplace, source_filename
                    )
                        SELECT DISTINCT ON (o.order_number, cm.sales_channel_id)
                            o.order_number,
                            cm.sales_channel_id,
                            sm.service_id,
                            wm.warehouse_id,
                            5,   -- Lazada tidak punya time_shipped → Data Tidak Tersedia
                            NULLIF(TRIM(o.tracking_code), 'nan'),
                            'Dropship',
                            TRUE,
                            CASE WHEN NULLIF(NULLIF(TRIM(o.create_time), 'nan'), '') IS NOT NULL
                                THEN TO_TIMESTAMP(TRIM(o.create_time), 'DD Mon YYYY HH24:MI') END,
                            CASE WHEN NULLIF(NULLIF(TRIM(o.rts_sla), 'nan'), '') IS NOT NULL
                                THEN TO_TIMESTAMP(TRIM(o.rts_sla), 'DD Mon YYYY HH24:MI') END,
                            CASE WHEN NULLIF(NULLIF(TRIM(o.delivered_date), 'nan'), '') IS NOT NULL
                                THEN TO_TIMESTAMP(TRIM(o.delivered_date), 'DD Mon YYYY HH24:MI') END,
                            CASE WHEN NULLIF(NULLIF(TRIM(o.create_time), 'nan'), '') IS NOT NULL
                                THEN CAST(TO_CHAR(TO_TIMESTAMP(TRIM(o.create_time), 'DD Mon YYYY HH24:MI')::DATE, 'YYYYMMDD') AS INT) END,
                            CASE WHEN NULLIF(NULLIF(TRIM(o.delivered_date), 'nan'), '') IS NOT NULL
                                THEN CAST(TO_CHAR(TO_TIMESTAMP(TRIM(o.delivered_date), 'DD Mon YYYY HH24:MI')::DATE, 'YYYYMMDD') AS INT) END,
                            'lazada',
                            o.source_filename
                        FROM stg_lazada_orders o
                        LEFT JOIN _tmp_channel_map cm   ON cm.nama_toko = o.nama_toko
                        LEFT JOIN _tmp_warehouse_map wm ON wm.raw_name = LOWER(TRIM(o.warehouse))
                        LEFT JOIN _tmp_shipping_map sm  ON sm.provider = TRIM(o.shipping_provider)
                        WHERE cm.sales_channel_id IS NOT NULL
                        ORDER BY o.order_number, cm.sales_channel_id
                    ON CONFLICT (order_id, sales_channel_id) DO NOTHING
                """)
            else:
                logger.warning(f"Marketplace '{marketplace}' tidak dikenal.")
                return

            result = conn.execute(sql)
            logger.info(f"✅ fact_fulfillment_logistics: {result.rowcount} baris diproses untuk {marketplace}")

    except Exception as e:
        logger.error(f"❌ fact_fulfillment_logistics gagal untuk {marketplace}: {e}")


# ============================================================
# TRANSFORM 3: fact_balance_transaction
# ============================================================

def transform_fact_balance_transaction(engine, marketplace):
    logger.info(f"[TRANSFORM] fact_balance_transaction ← {marketplace}")
    try:
        with engine.begin() as conn:
            _create_temp_tables(conn)
            _load_channel_map(conn, marketplace)

            if marketplace == 'tiktok_tokopedia':
                # Baris Withdrawal (punya payout_batch_id)
                sql_withdrawal = text("""
                    INSERT INTO fact_balance_transaction (
                        sales_channel_id, transaction_date, type, sub_type,
                        direction, amount, payout_batch_id, remarks,
                        source_marketplace, source_filename, transaction_date_id
                    )
                        SELECT
                            cm.sales_channel_id,
                            TRIM(r.success_time)::DATE,
                            TRIM(r.type),
                            NULL,
                            'outflow',
                            ABS(NULLIF(TRIM(r.amount), 'nan')::NUMERIC),
                            TRIM(r.reference_id),
                            NULL,
                            'tiktok_tokopedia',
                            r.source_filename,
                            CAST(TO_CHAR(TRIM(r.success_time)::DATE, 'YYYYMMDD') AS INT)
                        FROM stg_tiktok_tokopedia_report r
                        LEFT JOIN _tmp_channel_map cm ON cm.nama_toko = r.nama_toko AND cm.purchase_channel = 'tiktok'
                        WHERE cm.sales_channel_id IS NOT NULL
                          AND TRIM(r.success_time) ~ '^\\d{4}-\\d{2}-\\d{2}'
                          AND TRIM(r.type) = 'Withdrawal' AND NULLIF(TRIM(r.reference_id), 'nan') IS NOT NULL
                    ON CONFLICT (sales_channel_id, payout_batch_id)
                        WHERE payout_batch_id IS NOT NULL
                    DO NOTHING
                """)
                # Baris non-Withdrawal
                sql_non_withdrawal = text("""
                    INSERT INTO fact_balance_transaction (
                        sales_channel_id, transaction_date, type, sub_type,
                        direction, amount, payout_batch_id, remarks,
                        source_marketplace, source_filename, transaction_date_id
                    )
                    SELECT
                        cm.sales_channel_id,
                        TRIM(r.success_time)::DATE,
                        TRIM(r.type),
                        NULL,
                        CASE TRIM(r.type)
                            WHEN 'Earnings'          THEN 'inflow'
                            WHEN 'GMV Pay Deduction' THEN 'outflow'
                            ELSE 'adjustment'
                        END,
                        ABS(NULLIF(TRIM(r.amount), 'nan')::NUMERIC),
                        NULL,
                        NULL,
                        'tiktok_tokopedia',
                        r.source_filename,
                        CAST(TO_CHAR(TRIM(r.success_time)::DATE, 'YYYYMMDD') AS INT)
                    FROM stg_tiktok_tokopedia_report r
                    LEFT JOIN _tmp_channel_map cm ON cm.nama_toko = r.nama_toko
                        AND cm.purchase_channel = 'tiktok'
                    WHERE cm.sales_channel_id IS NOT NULL
                      AND TRIM(r.success_time) ~ '^\\d{4}-\\d{2}-\\d{2}'
                      AND TRIM(r.type) != 'Withdrawal'
                    ON CONFLICT (sales_channel_id, transaction_date, type, amount, source_filename)
                        WHERE payout_batch_id IS NULL
                    DO NOTHING
                """)
                r1 = conn.execute(sql_withdrawal)
                r2 = conn.execute(sql_non_withdrawal)
                logger.info(f"✅ fact_balance_transaction TikTok: {r1.rowcount + r2.rowcount} baris")

            elif marketplace == 'shopee':
                sql = text("""
                    INSERT INTO fact_balance_transaction (
                        sales_channel_id, transaction_date, type, sub_type,
                        direction, amount, payout_batch_id, remarks,
                        source_marketplace, source_filename, transaction_date_id
                    )
                    SELECT
                        cm.sales_channel_id,
                        TRIM(r.tanggal_transaksi)::DATE,
                        TRIM(r.tipe_transaksi),
                        NULL,
                        CASE TRIM(r.tipe_transaksi)
                            WHEN 'Penghasilan dari Pesanan'        THEN 'inflow'
                            WHEN 'Pembayaran dengan Saldo Penjual' THEN 'outflow'
                            WHEN 'Penarikan Dana'                  THEN 'outflow'
                            WHEN 'Penyesuaian'                     THEN 'adjustment'
                            ELSE 'adjustment'
                        END,
                        ABS(NULLIF(TRIM(r.jumlah), 'nan')::NUMERIC),
                        NULL,
                        NULLIF(TRIM(r.deskripsi), 'nan'),
                        'shopee',
                        r.source_filename,
                        CAST(TO_CHAR(TRIM(r.tanggal_transaksi)::DATE, 'YYYYMMDD') AS INT)
                    FROM stg_shopee_report r
                    LEFT JOIN _tmp_channel_map cm ON cm.nama_toko = r.nama_toko
                    WHERE cm.sales_channel_id IS NOT NULL
                      AND TRIM(r.tanggal_transaksi) ~ '^\\d{4}-\\d{2}-\\d{2}'
                    ON CONFLICT (sales_channel_id, transaction_date, type, amount, source_filename)
                        WHERE payout_batch_id IS NULL
                    DO NOTHING
                """)
                result = conn.execute(sql)
                logger.info(f"✅ fact_balance_transaction Shopee: {result.rowcount} baris")

            elif marketplace == 'lazada':
                # Baris Withdrawal
                sql_withdrawal = text("""
                    INSERT INTO fact_balance_transaction (
                        sales_channel_id, transaction_date, type, sub_type,
                        direction, amount, payout_batch_id, remarks,
                        source_marketplace, source_filename, transaction_date_id
                    )
                    SELECT
                        cm.sales_channel_id,
                        TO_TIMESTAMP(TRIM(r.transaction_time), 'DD Mon YYYY HH24:MI:SS')::DATE,
                        TRIM(r.type),
                        NULLIF(TRIM(r.sub_type), 'nan'),
                        'outflow',
                        ABS(NULLIF(REPLACE(TRIM(r.amount), ',', ''), 'nan')::NUMERIC),
                        TRIM(r.transaction_number),
                        NULLIF(TRIM(r.remarks), 'nan'),
                        'lazada',
                        r.source_filename,
                        CAST(TO_CHAR(
                            TO_TIMESTAMP(TRIM(r.transaction_time), 'DD Mon YYYY HH24:MI:SS')::DATE,
                            'YYYYMMDD') AS INT)
                    FROM stg_lazada_report r
                    LEFT JOIN _tmp_channel_map cm ON cm.nama_toko = r.nama_toko
                    WHERE cm.sales_channel_id IS NOT NULL
                      AND TRIM(r.transaction_time) ~ '^\\d{2} [A-Za-z]{3} \\d{4}'
                      AND TRIM(r.type) = 'Withdrawal'
                    ON CONFLICT (sales_channel_id, payout_batch_id)
                        WHERE payout_batch_id IS NOT NULL
                    DO NOTHING
                """)
                # Baris non-Withdrawal
                sql_non_withdrawal = text("""
                    INSERT INTO fact_balance_transaction (
                        sales_channel_id, transaction_date, type, sub_type,
                        direction, amount, payout_batch_id, remarks,
                        source_marketplace, source_filename, transaction_date_id
                    )
                    SELECT
                        cm.sales_channel_id,
                        TO_TIMESTAMP(TRIM(r.transaction_time), 'DD Mon YYYY HH24:MI:SS')::DATE,
                        TRIM(r.type),
                        NULLIF(TRIM(r.sub_type), 'nan'),
                        CASE
                            WHEN TRIM(r.type) = 'Deposit'  AND TRIM(r.sub_type) = 'Settlement'      THEN 'inflow'
                            WHEN TRIM(r.type) = 'Deposit'  AND TRIM(r.sub_type) = 'Failed Payment'  THEN 'adjustment'
                            WHEN TRIM(r.type) = 'Payment'                                            THEN 'outflow'
                            WHEN TRIM(r.type) = 'Penalty'                                            THEN 'outflow'
                            ELSE 'adjustment'
                        END,
                        ABS(NULLIF(REPLACE(TRIM(r.amount), ',', ''), 'nan')::NUMERIC),
                        NULL,
                        NULLIF(TRIM(r.remarks), 'nan'),
                        'lazada',
                        r.source_filename,
                        CAST(TO_CHAR(
                            TO_TIMESTAMP(TRIM(r.transaction_time), 'DD Mon YYYY HH24:MI:SS')::DATE,
                            'YYYYMMDD') AS INT)
                    FROM stg_lazada_report r
                    LEFT JOIN _tmp_channel_map cm ON cm.nama_toko = r.nama_toko
                    WHERE cm.sales_channel_id IS NOT NULL
                      AND TRIM(r.transaction_time) ~ '^\\d{2} [A-Za-z]{3} \\d{4}'
                      AND TRIM(r.type) != 'Withdrawal'
                    ON CONFLICT (sales_channel_id, transaction_date, type, amount, source_filename)
                        WHERE payout_batch_id IS NULL
                    DO NOTHING
                """)
                r1 = conn.execute(sql_withdrawal)
                r2 = conn.execute(sql_non_withdrawal)
                logger.info(f"✅ fact_balance_transaction Lazada: {r1.rowcount + r2.rowcount} baris")

            else:
                logger.warning(f"Marketplace '{marketplace}' tidak dikenal.")

    except Exception as e:
        logger.error(f"❌ fact_balance_transaction gagal untuk {marketplace}: {e}")


# ============================================================
# TRANSFORM 4: fact_returns_online
# ============================================================

def transform_fact_returns_online(engine, marketplace):
    logger.info(f"[TRANSFORM] fact_returns_online ← {marketplace}")
    try:
        with engine.begin() as conn:
            _create_temp_tables(conn)
            _load_channel_map(conn, marketplace)
            _load_warehouse_map(conn, marketplace)

            if marketplace == 'shopee':
                # Baris dengan product_id diketahui
                sql_known = text("""
                    INSERT INTO fact_returns_online (
                        order_id, product_id, sales_channel_id,
                        cancel_return_reason_id, initiator_id, return_status_id, warehouse_id,
                        qty_returned, source_marketplace, source_filename
                    )
                    SELECT
                        o.no_pesanan,
                        dp.product_id,
                        cm.sales_channel_id,
                        NULL,
                        NULL,
                        CASE TRIM(o.status_pembatalan_pengembalian)
                            WHEN 'Permintaan Disetujui'  THEN 1
                            WHEN 'Permintaan Dibatalkan' THEN 2
                            WHEN 'Pengembalian Diproses' THEN 3
                            ELSE 5
                        END,
                        wm.warehouse_id,
                        CASE WHEN NULLIF(TRIM(o.returned_quantity), 'nan') IS NOT NULL
                             THEN TRIM(o.returned_quantity)::INT ELSE NULL END,
                        'shopee',
                        o.source_filename
                    FROM stg_shopee_orders o
                    LEFT JOIN _tmp_channel_map cm  ON cm.nama_toko = o.nama_toko
                    LEFT JOIN _tmp_warehouse_map wm ON wm.raw_name = LOWER(TRIM(o.nama_gudang))
                    LEFT JOIN dim_product dp
                        ON dp.sku_code = COALESCE(
                            NULLIF(TRIM(o.nomor_referensi_sku), 'nan'),
                            NULLIF(TRIM(o.sku_induk), 'nan')
                        )
                    WHERE cm.sales_channel_id IS NOT NULL
                      AND dp.product_id IS NOT NULL
                      AND (
                          (NULLIF(TRIM(o.returned_quantity), '0') IS NOT NULL
                           AND NULLIF(TRIM(o.returned_quantity), 'nan') IS NOT NULL)
                          OR o.status_pembatalan_pengembalian IS NOT NULL
                      )
                    ON CONFLICT (order_id, product_id, sales_channel_id)
                        WHERE product_id IS NOT NULL
                    DO NOTHING
                """)
                # Baris dengan product_id tidak diketahui
                sql_unknown = text("""
                    INSERT INTO fact_returns_online (
                        order_id, product_id, sales_channel_id,
                        cancel_return_reason_id, initiator_id, return_status_id, warehouse_id,
                        qty_returned, source_marketplace, source_filename
                    )
                    SELECT
                        o.no_pesanan,
                        NULL,
                        cm.sales_channel_id,
                        NULL,
                        NULL,
                        CASE TRIM(o.status_pembatalan_pengembalian)
                            WHEN 'Permintaan Disetujui'  THEN 1
                            WHEN 'Permintaan Dibatalkan' THEN 2
                            WHEN 'Pengembalian Diproses' THEN 3
                            ELSE 5
                        END,
                        wm.warehouse_id,
                        CASE WHEN NULLIF(TRIM(o.returned_quantity), 'nan') IS NOT NULL
                             THEN TRIM(o.returned_quantity)::INT ELSE NULL END,
                        'shopee',
                        o.source_filename
                    FROM stg_shopee_orders o
                    LEFT JOIN _tmp_channel_map cm  ON cm.nama_toko = o.nama_toko
                    LEFT JOIN _tmp_warehouse_map wm ON wm.raw_name = LOWER(TRIM(o.nama_gudang))
                    LEFT JOIN dim_product dp
                        ON dp.sku_code = COALESCE(
                            NULLIF(TRIM(o.nomor_referensi_sku), 'nan'),
                            NULLIF(TRIM(o.sku_induk), 'nan')
                        )
                    WHERE cm.sales_channel_id IS NOT NULL
                      AND dp.product_id IS NULL
                      AND (
                          (NULLIF(TRIM(o.returned_quantity), '0') IS NOT NULL
                           AND NULLIF(TRIM(o.returned_quantity), 'nan') IS NOT NULL)
                          OR o.status_pembatalan_pengembalian IS NOT NULL
                      )
                    ON CONFLICT (order_id, sales_channel_id)
                        WHERE product_id IS NULL
                    DO NOTHING
                """)
                r1 = conn.execute(sql_known)
                r2 = conn.execute(sql_unknown)
                logger.info(f"✅ fact_returns_online Shopee: {r1.rowcount + r2.rowcount} baris")

            elif marketplace == 'tiktok_tokopedia':
                sql_known = text("""
                    INSERT INTO fact_returns_online (
                        order_id, product_id, sales_channel_id,
                        cancel_return_reason_id, initiator_id, return_status_id, warehouse_id,
                        qty_returned, amt_refunded, return_event_date_id,
                        source_marketplace, source_filename
                    )
                    SELECT
                        o.order_id,
                        dp.product_id,
                        cm.sales_channel_id,
                        cr.cancel_return_reason_id,
                        CASE TRIM(o.cancel_by)
                            WHEN 'User'     THEN 1
                            WHEN 'Seller'   THEN 2
                            WHEN 'System'   THEN 3
                            WHEN 'Operator' THEN 4
                        END,
                        CASE
                            WHEN TRIM(o.cancelation_return_type) = 'Return/Refund' THEN 1
                            WHEN TRIM(o.cancelation_return_type) = 'Cancel'
                             AND TRIM(o.order_status) = 'Dibatalkan'               THEN 5
                            WHEN TRIM(o.cancelation_return_type) = 'Cancel'
                             AND TRIM(o.order_status) = 'Selesai'                  THEN 8
                        END,
                        wm.warehouse_id,
                        CASE WHEN NULLIF(TRIM(o.sku_quantity_of_return), 'nan') IS NOT NULL
                             THEN TRIM(o.sku_quantity_of_return)::INT ELSE NULL END,
                        CASE WHEN NULLIF(TRIM(o.order_refund_amount), '0') IS NOT NULL
                              AND NULLIF(TRIM(o.order_refund_amount), 'nan') IS NOT NULL
                             THEN TRIM(o.order_refund_amount)::NUMERIC ELSE NULL END,
                        CASE WHEN NULLIF(NULLIF(TRIM(o.cancelled_time), 'nan'), '') IS NOT NULL
                             THEN CAST(TO_CHAR(TO_TIMESTAMP(TRIM(o.cancelled_time), 'DD/MM/YYYY HH24:MI:SS')::DATE, 'YYYYMMDD') AS INT) END,
                        'tiktok_tokopedia',
                        o.source_filename
                    FROM stg_tiktok_tokopedia_orders o
                    LEFT JOIN _tmp_channel_map cm ON cm.nama_toko = o.nama_toko
                        AND LOWER(cm.purchase_channel) = LOWER(NULLIF(TRIM(o.purchase_channel), 'nan'))
                    LEFT JOIN _tmp_warehouse_map wm ON wm.raw_name = LOWER(TRIM(o.warehouse_name))
                    LEFT JOIN dim_product dp ON dp.sku_code = NULLIF(TRIM(o.seller_sku), 'nan')
                    LEFT JOIN dim_cancel_return_reason cr
                        ON cr.reason_text_original = TRIM(o.cancel_reason)
                    WHERE cm.sales_channel_id IS NOT NULL
                      AND dp.product_id IS NOT NULL
                      AND NULLIF(TRIM(o.cancelation_return_type), 'nan') IS NOT NULL
                    ON CONFLICT (order_id, product_id, sales_channel_id)
                        WHERE product_id IS NOT NULL
                    DO NOTHING
                """)
                sql_unknown = text("""
                    INSERT INTO fact_returns_online (
                        order_id, product_id, sales_channel_id,
                        cancel_return_reason_id, initiator_id, return_status_id, warehouse_id,
                        qty_returned, amt_refunded, return_event_date_id,
                        source_marketplace, source_filename
                    )
                    SELECT
                        o.order_id,
                        NULL,
                        cm.sales_channel_id,
                        cr.cancel_return_reason_id,
                        CASE TRIM(o.cancel_by)
                            WHEN 'User'     THEN 1
                            WHEN 'Seller'   THEN 2
                            WHEN 'System'   THEN 3
                            WHEN 'Operator' THEN 4
                        END,
                        CASE
                            WHEN TRIM(o.cancelation_return_type) = 'Return/Refund' THEN 1
                            WHEN TRIM(o.cancelation_return_type) = 'Cancel'
                             AND TRIM(o.order_status) = 'Dibatalkan'               THEN 5
                            WHEN TRIM(o.cancelation_return_type) = 'Cancel'
                             AND TRIM(o.order_status) = 'Selesai'                  THEN 8
                        END,
                        wm.warehouse_id,
                        CASE WHEN NULLIF(TRIM(o.sku_quantity_of_return), 'nan') IS NOT NULL
                             THEN TRIM(o.sku_quantity_of_return)::INT ELSE NULL END,
                        CASE WHEN NULLIF(TRIM(o.order_refund_amount), '0') IS NOT NULL
                              AND NULLIF(TRIM(o.order_refund_amount), 'nan') IS NOT NULL
                             THEN TRIM(o.order_refund_amount)::NUMERIC ELSE NULL END,
                        CASE WHEN NULLIF(NULLIF(TRIM(o.cancelled_time), 'nan'), '') IS NOT NULL
                             THEN CAST(TO_CHAR(TO_TIMESTAMP(TRIM(o.cancelled_time), 'DD/MM/YYYY HH24:MI:SS')::DATE, 'YYYYMMDD') AS INT) END,
                        'tiktok_tokopedia',
                        o.source_filename
                    FROM stg_tiktok_tokopedia_orders o
                    LEFT JOIN _tmp_channel_map cm ON cm.nama_toko = o.nama_toko
                        AND LOWER(cm.purchase_channel) = LOWER(NULLIF(TRIM(o.purchase_channel), 'nan'))
                    LEFT JOIN _tmp_warehouse_map wm ON wm.raw_name = LOWER(TRIM(o.warehouse_name))
                    LEFT JOIN dim_product dp ON dp.sku_code = NULLIF(TRIM(o.seller_sku), 'nan')
                    LEFT JOIN dim_cancel_return_reason cr
                        ON cr.reason_text_original = TRIM(o.cancel_reason)
                    WHERE cm.sales_channel_id IS NOT NULL
                      AND dp.product_id IS NULL
                      AND NULLIF(TRIM(o.cancelation_return_type), 'nan') IS NOT NULL
                    ON CONFLICT (order_id, sales_channel_id)
                        WHERE product_id IS NULL
                    DO NOTHING
                """)
                r1 = conn.execute(sql_known)
                r2 = conn.execute(sql_unknown)
                logger.info(f"✅ fact_returns_online TikTok: {r1.rowcount + r2.rowcount} baris")

            elif marketplace == 'lazada':
                sql_known = text("""
                    INSERT INTO fact_returns_online (
                        order_id, product_id, sales_channel_id,
                        cancel_return_reason_id, initiator_id, return_status_id, warehouse_id,
                        exception_type, qty_returned, amt_refunded, return_event_date_id,
                        source_marketplace, source_filename
                    )
                    SELECT
                        o.order_number,
                        dp.product_id,
                        cm.sales_channel_id,
                        cr.cancel_return_reason_id,
                        CASE SPLIT_PART(o.buyer_failed_delivery_return_initiator, '-', 1)
                            WHEN 'cancel' THEN
                                CASE SPLIT_PART(o.buyer_failed_delivery_return_initiator, '-', 2)
                                    WHEN 'buyer'  THEN 1
                                    WHEN 'seller' THEN 2
                                    WHEN 'system' THEN 3
                                END
                            WHEN 'return'      THEN 1
                            WHEN 'only_refund' THEN 1
                        END,
                        CASE TRIM(o.status)
                            WHEN 'canceled'                         THEN 5
                            WHEN 'returned'                         THEN 4
                            WHEN 'Package Returned'                 THEN 4
                            WHEN 'In Transit: Returning to seller'  THEN 3
                            WHEN 'Lost by 3PL'                      THEN 7
                            WHEN 'Damaged by 3PL'                   THEN 7
                            WHEN 'Package scrapped'                 THEN 7
                            ELSE CASE WHEN o.buyer_failed_delivery_return_initiator LIKE 'only_refund%' THEN 6 END
                        END,
                        wm.warehouse_id,
                        CASE WHEN TRIM(o.status) IN ('Lost by 3PL','Damaged by 3PL','Package scrapped')
                             THEN TRIM(o.status) ELSE NULL END,
                        1,
                        CASE WHEN NULLIF(TRIM(o.refund_amount), 'nan') IS NOT NULL
                              AND NULLIF(TRIM(o.refund_amount), '0') IS NOT NULL
                             THEN TRIM(o.refund_amount)::NUMERIC ELSE NULL END,
                        CASE WHEN NULLIF(NULLIF(TRIM(o.update_time), 'nan'), '') IS NOT NULL
                             THEN CAST(TO_CHAR(TO_TIMESTAMP(TRIM(o.update_time), 'DD Mon YYYY HH24:MI')::DATE, 'YYYYMMDD') AS INT) END,
                        'lazada',
                        o.source_filename
                    FROM stg_lazada_orders o
                    LEFT JOIN _tmp_channel_map cm  ON cm.nama_toko = o.nama_toko
                    LEFT JOIN _tmp_warehouse_map wm ON wm.raw_name = LOWER(TRIM(o.warehouse))
                    LEFT JOIN dim_product dp ON dp.sku_code = NULLIF(TRIM(o.seller_sku), 'nan')
                    LEFT JOIN dim_cancel_return_reason cr
                        ON cr.reason_text_original = TRIM(REGEXP_REPLACE(
                            o.buyer_failed_delivery_reason, '[\\r\\n]+', '', 'g'))
                    WHERE cm.sales_channel_id IS NOT NULL
                      AND dp.product_id IS NOT NULL
                      AND (
                          TRIM(o.status) IN ('canceled','returned','Package Returned',
                                             'In Transit: Returning to seller',
                                             'Lost by 3PL','Damaged by 3PL','Package scrapped')
                          OR o.buyer_failed_delivery_return_initiator LIKE 'only_refund%'
                      )
                    ON CONFLICT (order_id, product_id, sales_channel_id)
                        WHERE product_id IS NOT NULL
                    DO NOTHING
                """)
                sql_unknown = text("""
                    INSERT INTO fact_returns_online (
                        order_id, product_id, sales_channel_id,
                        cancel_return_reason_id, initiator_id, return_status_id, warehouse_id,
                        exception_type, qty_returned, amt_refunded, return_event_date_id,
                        source_marketplace, source_filename
                    )
                    SELECT
                        o.order_number,
                        NULL,
                        cm.sales_channel_id,
                        cr.cancel_return_reason_id,
                        CASE SPLIT_PART(o.buyer_failed_delivery_return_initiator, '-', 1)
                            WHEN 'cancel' THEN
                                CASE SPLIT_PART(o.buyer_failed_delivery_return_initiator, '-', 2)
                                    WHEN 'buyer'  THEN 1
                                    WHEN 'seller' THEN 2
                                    WHEN 'system' THEN 3
                                END
                            WHEN 'return'      THEN 1
                            WHEN 'only_refund' THEN 1
                        END,
                        CASE TRIM(o.status)
                            WHEN 'canceled'                         THEN 5
                            WHEN 'returned'                         THEN 4
                            WHEN 'Package Returned'                 THEN 4
                            WHEN 'In Transit: Returning to seller'  THEN 3
                            WHEN 'Lost by 3PL'                      THEN 7
                            WHEN 'Damaged by 3PL'                   THEN 7
                            WHEN 'Package scrapped'                 THEN 7
                            ELSE CASE WHEN o.buyer_failed_delivery_return_initiator LIKE 'only_refund%' THEN 6 END
                        END,
                        wm.warehouse_id,
                        CASE WHEN TRIM(o.status) IN ('Lost by 3PL','Damaged by 3PL','Package scrapped')
                             THEN TRIM(o.status) ELSE NULL END,
                        1,
                        CASE WHEN NULLIF(TRIM(o.refund_amount), 'nan') IS NOT NULL
                              AND NULLIF(TRIM(o.refund_amount), '0') IS NOT NULL
                             THEN TRIM(o.refund_amount)::NUMERIC ELSE NULL END,
                        CASE WHEN NULLIF(NULLIF(TRIM(o.update_time), 'nan'), '') IS NOT NULL
                             THEN CAST(TO_CHAR(TO_TIMESTAMP(TRIM(o.update_time), 'DD Mon YYYY HH24:MI')::DATE, 'YYYYMMDD') AS INT) END,
                        'lazada',
                        o.source_filename
                    FROM stg_lazada_orders o
                    LEFT JOIN _tmp_channel_map cm  ON cm.nama_toko = o.nama_toko
                    LEFT JOIN _tmp_warehouse_map wm ON wm.raw_name = LOWER(TRIM(o.warehouse))
                    LEFT JOIN dim_product dp ON dp.sku_code = NULLIF(TRIM(o.seller_sku), 'nan')
                    LEFT JOIN dim_cancel_return_reason cr
                        ON cr.reason_text_original = TRIM(REGEXP_REPLACE(
                            o.buyer_failed_delivery_reason, '[\\r\\n]+', '', 'g'))
                    WHERE cm.sales_channel_id IS NOT NULL
                      AND dp.product_id IS NULL
                      AND (
                          TRIM(o.status) IN ('canceled','returned','Package Returned',
                                             'In Transit: Returning to seller',
                                             'Lost by 3PL','Damaged by 3PL','Package scrapped')
                          OR o.buyer_failed_delivery_return_initiator LIKE 'only_refund%'
                      )
                    ON CONFLICT (order_id, sales_channel_id)
                        WHERE product_id IS NULL
                    DO NOTHING
                """)
                r1 = conn.execute(sql_known)
                r2 = conn.execute(sql_unknown)
                logger.info(f"✅ fact_returns_online Lazada: {r1.rowcount + r2.rowcount} baris")

            else:
                logger.warning(f"Marketplace '{marketplace}' tidak dikenal.")

    except Exception as e:
        logger.error(f"❌ fact_returns_online gagal untuk {marketplace}: {e}")


# ============================================================
# CONSTANTS: kolom fee → fee_type_id (untuk unpivot Phase 2)
# ============================================================

# TikTok/Tokopedia income — kolom nama staging → fee_type_id
TIKTOK_INCOME_FEE_COLS = {
    'seller_co_funded_voucher_discount':                  20,
    'refund_of_seller_co_funded_voucher_discount':        21,
    'platform_discounts':                                 22,
    'refund_of_platform_discounts':                       23,
    'platform_co_funded_voucher_discounts':               24,
    'refund_of_platform_co_funded_voucher_discounts':     25,
    'seller_shipping_cost_discount':                      26,
    'platform_commission_fee':                            27,
    'pre_order_service_fee':                              28,
    'mall_service_fee':                                   29,
    'payment_fee':                                        30,
    'shipping_fee_program_service_fee':                   31,
    'order_processing_fee':                               32,
    'paylater_program_fee':                               33,
    'affiliate_commission':                               34,
    'affiliate_partner_commission':                       35,
    'affiliate_shop_ads_commission':                      36,
    'affiliate_partner_shop_ads_commission':              37,
    'dynamic_commission':                                 38,
    'gmv_max_ad_fee':                                     39,
    'gmv_max_coupon':                                     40,
    'bonus_cashback_service_fee':                         41,
    'live_specials_service_fee':                          42,
    'voucher_xtra_service_fee':                           43,
    'eams_program_service_fee':                           44,
    'brands_crazy_deals_flash_sale_service_fee':          45,
    'campaign_resource_fee':                              46,
    'shipping_cost':                                      47,
    'shipping_costs_passed_on_to_the_logistics_provider': 48,
    'replacement_shipping_fee_passed_on_to_the_customer': 49,
    'exchange_shipping_fee_passed_on_to_the_customer':    50,
    'shipping_cost_borne_by_the_platform':                51,
    'shipping_cost_paid_by_the_customer':                 52,
    'refunded_shipping_cost_paid_by_the_customer':        53,
    'return_shipping_costs_passed_on_to_the_customer':    54,
    'shipping_cost_subsidy':                              55,
    'distance_shipping_fee_from_horizon_plus_program':    56,
    'distance_item_fee_from_horizon_plus_program':        57,
    'dilayani_tokopedia_fee':                             58,
    'dilayani_tokopedia_handling_fee':                    59,
    'installation_service_fee':                           60,
    'platform_special_service_fee':                       61,
    'article_22_income_tax_withheld':                     63,
    'shipping_fee_adjustment':                            64,
    'shipping_fee_compensation':                          65,
    'chargeback':                                         66,
    'customer_service_compensation':                      67,
    'promotion_adjustment':                               68,
    'platform_compensation':                              69,
    'platform_penalty':                                   70,
    'sample_shipping_fee':                                71,
    'logistics_reimbursement':                            72,
    'platform_reimbursement':                             73,
    'deductions_incurred_by_seller':                      74,
    'shipping_fee_rebate':                                75,
    'warehouse_service_fee':                              76,
    'platform_commission_adjustment':                     77,
    'platform_commission_compensation':                   78,
    'transaction_fee_adjustment':                         79,
    'campaign_package':                                   80,
    'additional_campaign_package':                        81,
    'gmv_payment_for_promote':                            82,
    'gmv_payment_for_tiktok_ads':                         83,
    'shipping_insurance_compensation':                    84,
    'other_adjustment':                                   86,
    'top_up_for_ads_from_settled_balances':               87,
}

# Shopee income_main — kolom fee tunggal (satu kolom = satu fee_type_id)
SHOPEE_INCOME_MAIN_FEE_COLS = {
    'voucher_disponsor_oleh_penjual':                                    88,
    'voucher_co_fund_disponsor_oleh_penjual':                            89,
    'cashback_koin_disponsori_penjual':                                  90,
    'cashback_koin_co_fund_disponsori_penjual':                          91,
    'diskon_produk_dari_shopee':                                         92,
    'promo_gratis_ongkir_dari_penjual':                                  93,
    'gratis_ongkir_dari_shopee':                                         94,
    'diskon_ongkir_ditanggung_jasa_kirim':                               95,
    'biaya_program_hemat_biaya_kirim':                                   96,
    'biaya_administrasi_termasuk_ppn_11':                                97,
    'biaya_layanan':                                                     98,
    'biaya_transaksi':                                                   99,
    'biaya_proses_pesanan':                                             100,
    'premi':                                                            101,
    'biaya_isi_saldo_otomatis_dari_penghasilan':                        103,
    'biaya_komisi_ams':                                                 104,
    'biaya_kampanye':                                                   105,
    'ongkir_dibayar_pembeli':                                           111,
    'ongkir_yang_diteruskan_oleh_shopee_ke_jasa_kirim':                 112,
    'ongkos_kirim_pengembalian_barang':                                 113,
    'kembali_ke_biaya_pengiriman_pengirim':                             114,
    'pengembalian_biaya_kirim':                                         115,
    'bea_masuk_ppn_pph':                                                116,
    'kompensasi':                                                       117,
    'pro_rata_koin_yang_ditukarkan_untuk_pengembalian_barang':          118,
    'pro_rata_voucher_shopee_untuk_pengembalian_barang':                119,
    'pro_rated_bank_payment_channel_promotion_for_return_refund_item':  120,
    'pro_rated_shopee_payment_channel_promotion_for_return_refund_it':  121,
}


# ─── Kolom non-fee (bukan fee, hanya metadata order) ────────────────────────
# Dipakai oleh _warn_unmapped_wide_cols untuk tahu kolom mana yang perlu dicek.

TIKTOK_NON_FEE_COLS = frozenset({
    'order_adjustment_id', 'type', 'order_created_time', 'order_settled_time',
    'currency', 'total_settlement_amount', 'total_revenue',
    'subtotal_after_seller_discounts', 'subtotal_before_discounts',
    'seller_discounts', 'refund_subtotal_after_seller_discounts',
    'refund_subtotal_before_seller_discounts', 'refund_of_seller_discounts',
    'total_fees', 'ajustment_amount', 'related_order_id',
    'customer_payment', 'customer_refund', 'estimated_package_weight',
    'actual_package_weight', 'nama_toko', 'source_filename',
    'order_source', 'shopping_center_items',
})

SHOPEE_MAIN_NON_FEE_COLS = frozenset({
    'no', 'no_pesanan', 'no_pengajuan', 'username_pembeli',
    'waktu_pesanan_dibuat', 'metode_pembayaran_pembeli', 'tanggal_dana_dilepaskan',
    'harga_asli_produk', 'total_diskon_produk', 'jumlah_pengembalian_dana_ke_pembeli',
    'total_penghasilan', 'kode_voucher', 'jasa_kirim', 'nama_kurir',
    'pengembalian_dana_ke_pembeli', 'nama_toko', 'source_filename',
})

# Shopee SF: kolom fee yang sudah di-hardcode di sql_sf
SHOPEE_SF_MAPPED_FEE_COLS = frozenset({
    'biaya_pembayaran',
    'biaya_layanan_gratis_ongkir_xtra', 'biaya_layanan_gratis_ongkir_xtra_2',
    'biaya_layanan_promo_xtra',
    'biaya_layanan_cashback_xtra', 'biaya_layanan_cashbackxtra',
    'biaya_program_shopee_live_xtra',
    'biaya_campaign_1_1',  'biaya_campaign_2_2',  'biaya_campaign_3_3',
    'biaya_campaign_4_4',  'biaya_campaign_5_5',  'biaya_campaign_6_6',
    'biaya_campaign_7_7',  'biaya_campaign_8_8',  'biaya_campaign_9_9',
    'biaya_campaign_10_10', 'biaya_campaign_11_11', 'biaya_campaign_12_12',
})

SHOPEE_SF_NON_FEE_COLS = frozenset({'no', 'no_pesanan', 'nama_toko', 'source_filename'})


# ─── LAPIS 2: Helpers untuk deteksi fee tidak ter-mapping ───────────────────

def _warn_unmapped_wide_cols(conn, table_name, mapped_fee_cols, non_fee_cols, label):
    """
    LAPIS 2 — Wide format: cek apakah ada kolom di staging table yang tidak ada
    di mapped_fee_cols dan non_fee_cols, tapi punya nilai numerik ≠ 0.
    Log WARNING agar bisa ditambahkan ke COLS dict sebelum data hilang.
    """
    rows = conn.execute(text("""
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'staging'
          AND table_name   = :tname
        ORDER BY ordinal_position
    """), {'tname': table_name}).fetchall()

    excluded = set(mapped_fee_cols) | set(non_fee_cols)
    unmapped = [r[0] for r in rows if r[0] not in excluded]
    if not unmapped:
        return

    for col in unmapped:
        try:
            # col berasal dari information_schema — identifier DB yang sudah tervalidasi
            cnt = conn.execute(text(f"""
                SELECT COUNT(*)
                FROM staging."{table_name}"
                WHERE NULLIF(TRIM(CAST("{col}" AS TEXT)), '') IS NOT NULL
                  AND NULLIF(TRIM(CAST("{col}" AS TEXT)), '') <> 'nan'
                  AND TRIM(CAST("{col}" AS TEXT)) ~ '^-?[0-9]+(\\.[0-9]+)?$'
                  AND TRIM(CAST("{col}" AS TEXT))::NUMERIC <> 0
            """)).scalar() or 0
        except Exception:
            cnt = 0
        if cnt > 0:
            logger.warning(
                f"⚠️  LAPIS 2 [{label}]: kolom '{col}' di staging.{table_name} "
                f"tidak ada di mapping fee_type_id, tapi memiliki {cnt} baris bernilai ≠ 0. "
                f"Tambahkan ke COLS dict agar tidak ter-skip!"
            )


def _warn_unmapped_narrow_fees(conn, marketplace, label):
    """
    LAPIS 2 — Narrow format: cek fee_name di staging yang tidak cocok dengan
    dim_fee_type (JOIN gagal → row di-skip diam-diam). Log WARNING per fee_name.
    """
    if marketplace == 'shopee':
        sql = text("""
            SELECT TRIM(o.tipe_penyesuaian_deskripsi) AS fee_name, COUNT(*) AS cnt
            FROM stg_shopee_income_adjustment o
            LEFT JOIN dim_fee_type ft
                ON ft.fee_name         = TRIM(o.tipe_penyesuaian_deskripsi)
               AND ft.marketplace_name = 'Shopee'
            WHERE ft.fee_type_id IS NULL
              AND NULLIF(NULLIF(TRIM(o.biaya_penyesuaian), 'nan'), '') IS NOT NULL
              AND NULLIF(NULLIF(TRIM(o.biaya_penyesuaian), 'nan'), '')::NUMERIC <> 0
            GROUP BY 1
            ORDER BY cnt DESC
        """)
    elif marketplace == 'lazada':
        sql = text("""
            SELECT TRIM(o.nama_biaya) AS fee_name, COUNT(*) AS cnt
            FROM stg_lazada_income o
            LEFT JOIN dim_fee_type ft
                ON ft.fee_name         = TRIM(o.nama_biaya)
               AND ft.marketplace_name = 'Lazada'
            WHERE ft.fee_type_id IS NULL
              AND NULLIF(REPLACE(TRIM(o.jumlah_termasuk_pajak), ',', ''), 'nan') IS NOT NULL
              AND NULLIF(REPLACE(TRIM(o.jumlah_termasuk_pajak), ',', ''), 'nan')::NUMERIC <> 0
            GROUP BY 1
            ORDER BY cnt DESC
        """)
    else:
        return

    rows = conn.execute(sql).fetchall()
    for row in rows:
        logger.warning(
            f"⚠️  LAPIS 2 [{label}]: fee_name '{row[0]}' tidak ada di dim_fee_type "
            f"({row[1]} baris akan di-skip). Tambahkan ke dim_fee_type!"
        )


# ─── ORPHAN: Helper untuk adj tanpa order_id ────────────────────────────────

def _ensure_stg_fee_orphan(conn):
    """Buat tabel staging.stg_fee_orphan jika belum ada."""
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS staging.stg_fee_orphan (
            orphan_id       BIGSERIAL    PRIMARY KEY,
            source          VARCHAR(50)  NOT NULL,
            fee_name        VARCHAR(255),
            fee_amount      NUMERIC(18,2),
            reason          VARCHAR(50)  NOT NULL
                CHECK (reason IN ('no_order_id', 'unmapped_fee_type')),
            raw_reference   VARCHAR(100),
            nama_toko       VARCHAR(255),
            source_filename VARCHAR(255),
            inserted_at     TIMESTAMPTZ  DEFAULT NOW(),
            CONSTRAINT uq_fee_orphan
                UNIQUE (source, raw_reference, source_filename)
        )
    """))


def _save_shopee_adj_orphans(conn):
    """
    ORPHAN: Simpan baris stg_shopee_income_adjustment yang tidak punya
    no_pesanan_terhubung ke staging.stg_fee_orphan untuk investigasi manual.
    Baris ini sebelumnya di-drop diam-diam oleh ETL (WHERE ... IS NOT NULL).
    """
    result = conn.execute(text("""
        INSERT INTO staging.stg_fee_orphan
            (source, fee_name, fee_amount, reason, raw_reference, nama_toko, source_filename)
        SELECT
            'shopee_adj',
            TRIM(o.tipe_penyesuaian_deskripsi),
            ABS(NULLIF(NULLIF(TRIM(o.biaya_penyesuaian), 'nan'), '')::NUMERIC),
            'no_order_id',
            TRIM(o.no),
            TRIM(o.nama_toko),
            o.source_filename
        FROM stg_shopee_income_adjustment o
        WHERE NULLIF(TRIM(o.no_pesanan_terhubung), 'nan') IS NULL
          AND NULLIF(NULLIF(TRIM(o.biaya_penyesuaian), 'nan'), '') IS NOT NULL
          AND NULLIF(NULLIF(TRIM(o.biaya_penyesuaian), 'nan'), '')::NUMERIC <> 0
        ON CONFLICT (source, raw_reference, source_filename) DO NOTHING
    """))
    if result.rowcount > 0:
        logger.warning(
            f"⚠️  ORPHAN: {result.rowcount} baris Shopee Adj tanpa no_pesanan_terhubung "
            f"disimpan ke staging.stg_fee_orphan (reason='no_order_id'). "
            f"Perlu investigasi manual."
        )
    else:
        logger.info("✅ ORPHAN Shopee Adj: tidak ada baris baru tanpa order_id.")


# ============================================================
# TRANSFORM 5: fact_sales_online  (Phase 2)
# Sumber: stg_*_orders
# ============================================================

def transform_fact_sales_online(engine, marketplace):
    logger.info(f"[TRANSFORM] fact_sales_online ← {marketplace}")
    try:
        with engine.begin() as conn:
            _create_temp_tables(conn)
            _load_channel_map(conn, marketplace)

            if marketplace == 'shopee':
                sql_known = text("""
                    INSERT INTO fact_sales_online (
                        order_id, product_id, customer_id, sales_channel_id,
                        store_id, marketplace_id, order_status_id, payment_method_id,
                        order_date, order_date_id, is_pre_order,
                        qty_sold, qty_returned,
                        price_original_unit, amt_product_discount, amt_gross_revenue,
                        source_marketplace, source_filename
                    )
                        SELECT
                            o.no_pesanan,
                            dp.product_id,
                            dc.customer_id,
                            cm.sales_channel_id,
                            dsc.store_id,
                            dsc.marketplace_id,
                            CASE
                                WHEN o.status_pesanan = 'Belum Bayar'     THEN 1
                                WHEN o.status_pesanan = 'Perlu Dikirim'   THEN 2
                                WHEN o.status_pesanan = 'Sedang Dikirim'  THEN 3
                                WHEN o.status_pesanan = 'Telah Dikirim'   THEN 4
                                WHEN o.status_pesanan = 'Pesanan Diterima' THEN 5
                                WHEN o.status_pesanan LIKE 'Pesanan diterima, namun Pembeli masih%' THEN 6
                                WHEN o.status_pesanan = 'Selesai'          THEN 7
                                WHEN o.status_pesanan = 'Pembatalan diajukan' THEN 8
                                WHEN o.status_pesanan = 'Batal'            THEN 9
                                ELSE NULL
                            END,
                            CASE o.metode_pembayaran
                                WHEN 'COD (Bayar di Tempat)'        THEN 1
                                WHEN 'ShopeePay'                    THEN 12
                                WHEN 'Saldo ShopeePay'              THEN 12
                                WHEN 'QRIS'                         THEN 18
                                WHEN 'Kartu Kredit/Debit'           THEN 19
                                WHEN 'Cicilan Kartu Kredit'         THEN 19
                                WHEN 'BCA OneKlik'                  THEN 20
                                WHEN 'BRI Direct Debit'             THEN 21
                                WHEN 'SeaBank Bayar Instan'         THEN 22
                                WHEN 'SPayLater'                    THEN 23
                                WHEN 'Alfamart/Alfamidi/Dan+Dan'    THEN 30
                                WHEN 'Indomaret/i.Saku'             THEN 31
                                WHEN 'Mitra Shopee'                 THEN 32
                                WHEN 'Online Payment'               THEN 33
                                WHEN 'Pembayaran dibebaskan'        THEN 34
                                WHEN 'Bank Lainnya (Dicek Manual)'  THEN 8
                                ELSE NULL
                            END,
                            CASE WHEN NULLIF(NULLIF(NULLIF(TRIM(o.waktu_pesanan_dibuat), 'nan'), ''), '-') IS NOT NULL
                                THEN TO_TIMESTAMP(TRIM(o.waktu_pesanan_dibuat), 'YYYY-MM-DD HH24:MI')::DATE ELSE NULL END,
                            CASE WHEN NULLIF(NULLIF(NULLIF(TRIM(o.waktu_pesanan_dibuat), 'nan'), ''), '-') IS NOT NULL
                                THEN CAST(TO_CHAR(TO_TIMESTAMP(TRIM(o.waktu_pesanan_dibuat), 'YYYY-MM-DD HH24:MI')::DATE, 'YYYYMMDD') AS INT)
                                ELSE NULL END,
                            FALSE,
                            NULLIF(NULLIF(TRIM(o.jumlah), 'nan'), '')::INT,
                            CASE WHEN NULLIF(NULLIF(NULLIF(TRIM(o.returned_quantity), 'nan'), ''), '-') IS NOT NULL
                                THEN NULLIF(NULLIF(NULLIF(TRIM(o.returned_quantity), 'nan'), ''), '-')::INT
                                ELSE 0 END,
                            NULLIF(REPLACE(NULLIF(NULLIF(TRIM(o.harga_awal), 'nan'), ''), '.', ''), '')::NUMERIC,
                            ABS(COALESCE(NULLIF(REPLACE(NULLIF(NULLIF(TRIM(o.total_diskon), 'nan'), ''), '.', ''), '')::NUMERIC, 0)),
                            CASE WHEN NULLIF(NULLIF(TRIM(o.harga_awal), 'nan'), '') IS NOT NULL
                                    AND NULLIF(NULLIF(TRIM(o.jumlah), 'nan'), '') IS NOT NULL
                                THEN NULLIF(REPLACE(NULLIF(NULLIF(TRIM(o.harga_awal), 'nan'), ''), '.', ''), '')::NUMERIC
                                    * NULLIF(NULLIF(TRIM(o.jumlah), 'nan'), '')::INT
                                    - ABS(COALESCE(NULLIF(REPLACE(NULLIF(NULLIF(TRIM(o.total_diskon), 'nan'), ''), '.', ''), '')::NUMERIC, 0))
                                ELSE NULL END,
                            'shopee',
                            o.source_filename
                        FROM stg_shopee_orders o
                        LEFT JOIN _tmp_channel_map cm ON cm.nama_toko = LOWER(TRIM(o.nama_toko))
                        LEFT JOIN dim_sku_alias dsa ON dsa.sku_alias = COALESCE(
                            NULLIF(TRIM(o.nomor_referensi_sku), 'nan'), NULLIF(TRIM(o.sku_induk), 'nan'))
                        LEFT JOIN dim_product dp ON dp.sku_code = COALESCE(
                            (SELECT dp1.sku_code FROM dim_product dp1 WHERE dp1.sku_code = (
                                CASE WHEN COALESCE(NULLIF(TRIM(o.nomor_referensi_sku),'nan'),NULLIF(TRIM(o.sku_induk),'nan')) ~ '^P[0-9]'
                                     THEN 'B'||SUBSTRING(COALESCE(NULLIF(TRIM(o.nomor_referensi_sku),'nan'),NULLIF(TRIM(o.sku_induk),'nan')),2)
                                     ELSE COALESCE(NULLIF(TRIM(o.nomor_referensi_sku),'nan'),NULLIF(TRIM(o.sku_induk),'nan'))
                                END) LIMIT 1),
                            dsa.sku_code)
                        LEFT JOIN dim_customer dc
                            ON dc.marketplace_id = 1 AND dc.username = o.username_pembeli
                        LEFT JOIN dim_sales_channel dsc ON dsc.sales_channel_id = cm.sales_channel_id
                        WHERE cm.sales_channel_id IS NOT NULL AND dp.product_id IS NOT NULL
                    ON CONFLICT (order_id, product_id, sales_channel_id)
                        WHERE product_id IS NOT NULL
                    DO NOTHING
                """)
                sql_unknown = text("""
                    INSERT INTO fact_sales_online (
                        order_id, product_id, customer_id, sales_channel_id,
                        store_id, marketplace_id, order_status_id, payment_method_id,
                        order_date, order_date_id, is_pre_order,
                        qty_sold, qty_returned,
                        price_original_unit, amt_product_discount, amt_gross_revenue,
                        source_marketplace, source_filename
                    )
                    SELECT
                        o.no_pesanan,
                        NULL,
                        dc.customer_id,
                        cm.sales_channel_id,
                        dsc.store_id,
                        dsc.marketplace_id,
                        CASE
                            WHEN o.status_pesanan = 'Belum Bayar'     THEN 1
                            WHEN o.status_pesanan = 'Perlu Dikirim'   THEN 2
                            WHEN o.status_pesanan = 'Sedang Dikirim'  THEN 3
                            WHEN o.status_pesanan = 'Telah Dikirim'   THEN 4
                            WHEN o.status_pesanan = 'Pesanan Diterima' THEN 5
                            WHEN o.status_pesanan LIKE 'Pesanan diterima, namun Pembeli masih%' THEN 6
                            WHEN o.status_pesanan = 'Selesai'          THEN 7
                            WHEN o.status_pesanan = 'Pembatalan diajukan' THEN 8
                            WHEN o.status_pesanan = 'Batal'            THEN 9
                            ELSE NULL
                        END,
                        CASE o.metode_pembayaran
                            WHEN 'COD (Bayar di Tempat)'        THEN 1
                            WHEN 'ShopeePay'                    THEN 12
                            WHEN 'Saldo ShopeePay'              THEN 12
                            WHEN 'QRIS'                         THEN 18
                            WHEN 'Kartu Kredit/Debit'           THEN 19
                            WHEN 'Cicilan Kartu Kredit'         THEN 19
                            WHEN 'BCA OneKlik'                  THEN 20
                            WHEN 'BRI Direct Debit'             THEN 21
                            WHEN 'SeaBank Bayar Instan'         THEN 22
                            WHEN 'SPayLater'                    THEN 23
                            WHEN 'Alfamart/Alfamidi/Dan+Dan'    THEN 30
                            WHEN 'Indomaret/i.Saku'             THEN 31
                            WHEN 'Mitra Shopee'                 THEN 32
                            WHEN 'Online Payment'               THEN 33
                            WHEN 'Pembayaran dibebaskan'        THEN 34
                            WHEN 'Bank Lainnya (Dicek Manual)'  THEN 8
                            ELSE NULL
                        END, 
                        CASE WHEN NULLIF(NULLIF(NULLIF(TRIM(o.waktu_pesanan_dibuat), 'nan'), ''), '-') IS NOT NULL
                             THEN TO_TIMESTAMP(TRIM(o.waktu_pesanan_dibuat), 'YYYY-MM-DD HH24:MI')::DATE ELSE NULL END,
                        CASE WHEN NULLIF(NULLIF(NULLIF(TRIM(o.waktu_pesanan_dibuat), 'nan'), ''), '-') IS NOT NULL
                             THEN CAST(TO_CHAR(TO_TIMESTAMP(TRIM(o.waktu_pesanan_dibuat), 'YYYY-MM-DD HH24:MI')::DATE, 'YYYYMMDD') AS INT)
                             ELSE NULL END,
                        FALSE,
                        NULLIF(NULLIF(TRIM(o.jumlah), 'nan'), '')::INT,
                        CASE WHEN NULLIF(NULLIF(NULLIF(TRIM(o.returned_quantity), 'nan'), ''), '-') IS NOT NULL
                             THEN NULLIF(NULLIF(NULLIF(TRIM(o.returned_quantity), 'nan'), ''), '-')::INT
                             ELSE 0 END,
                        NULLIF(REPLACE(NULLIF(NULLIF(TRIM(o.harga_awal), 'nan'), ''), '.', ''), '')::NUMERIC,
                        ABS(COALESCE(NULLIF(REPLACE(NULLIF(NULLIF(TRIM(o.total_diskon), 'nan'), ''), '.', ''), '')::NUMERIC, 0)),
                        CASE WHEN NULLIF(NULLIF(TRIM(o.harga_awal), 'nan'), '') IS NOT NULL
                                  AND NULLIF(NULLIF(TRIM(o.jumlah), 'nan'), '') IS NOT NULL
                             THEN NULLIF(REPLACE(NULLIF(NULLIF(TRIM(o.harga_awal), 'nan'), ''), '.', ''), '')::NUMERIC
                                  * NULLIF(NULLIF(TRIM(o.jumlah), 'nan'), '')::INT
                                  - ABS(COALESCE(NULLIF(REPLACE(NULLIF(NULLIF(TRIM(o.total_diskon), 'nan'), ''), '.', ''), '')::NUMERIC, 0))
                             ELSE NULL END,
                        'shopee',
                        o.source_filename
                    FROM stg_shopee_orders o
                    LEFT JOIN _tmp_channel_map cm ON cm.nama_toko = LOWER(TRIM(o.nama_toko))
                    LEFT JOIN dim_sku_alias dsa ON dsa.sku_alias = COALESCE(
                        NULLIF(TRIM(o.nomor_referensi_sku), 'nan'), NULLIF(TRIM(o.sku_induk), 'nan'))
                    LEFT JOIN dim_product dp ON dp.sku_code = COALESCE(
                        (SELECT dp1.sku_code FROM dim_product dp1 WHERE dp1.sku_code = (
                            CASE WHEN COALESCE(NULLIF(TRIM(o.nomor_referensi_sku),'nan'),NULLIF(TRIM(o.sku_induk),'nan')) ~ '^P[0-9]'
                                 THEN 'B'||SUBSTRING(COALESCE(NULLIF(TRIM(o.nomor_referensi_sku),'nan'),NULLIF(TRIM(o.sku_induk),'nan')),2)
                                 ELSE COALESCE(NULLIF(TRIM(o.nomor_referensi_sku),'nan'),NULLIF(TRIM(o.sku_induk),'nan'))
                            END) LIMIT 1),
                        dsa.sku_code)
                    LEFT JOIN dim_customer dc
                        ON dc.marketplace_id = 1 AND dc.username = o.username_pembeli
                    LEFT JOIN dim_sales_channel dsc ON dsc.sales_channel_id = cm.sales_channel_id
                    WHERE cm.sales_channel_id IS NOT NULL
                      AND dp.product_id IS NULL
                    ON CONFLICT (order_id, sales_channel_id)
                        WHERE product_id IS NULL
                    DO NOTHING
                """)
                r1 = conn.execute(sql_known)
                r2 = conn.execute(sql_unknown)
                logger.info(f"✅ fact_sales_online Shopee: {r1.rowcount + r2.rowcount} baris")

            elif marketplace == 'tiktok_tokopedia':
                sql_known = text("""
                    INSERT INTO fact_sales_online (
                        order_id, product_id, customer_id, sales_channel_id,
                        store_id, marketplace_id, order_status_id, payment_method_id,
                        order_date, order_date_id, invoice_number, is_pre_order,
                        qty_sold, qty_returned,
                        price_original_unit, amt_product_discount, amt_gross_revenue,
                        source_marketplace, source_filename
                    )
                    SELECT
                        o.order_id,
                        dp.product_id,
                        dc.customer_id,
                        cm.sales_channel_id,
                        dsc.store_id,
                        dsc.marketplace_id,
                        CASE o.order_status
                            WHEN 'Belum dibayar' THEN 1
                            WHEN 'Perlu dikirim' THEN 2
                            WHEN 'Dikirim'       THEN 3
                            WHEN 'Selesai'       THEN 7
                            WHEN 'Dibatalkan'    THEN 9
                            ELSE NULL
                        END,
                        CASE o.payment_method
                            WHEN 'Bayar di tempat'            THEN 1
                            WHEN 'Cash'                       THEN 1
                            WHEN 'KlikBCA'                    THEN 2
                            WHEN 'BRImo'                      THEN 4
                            WHEN 'Transfer bank'              THEN 8
                            WHEN 'Bank Transfer (Manual VA)'  THEN 8
                            WHEN 'GoPay'                      THEN 9
                            WHEN 'OVO'                        THEN 10
                            WHEN 'DANA'                       THEN 11
                            WHEN 'LinkAja'                    THEN 13
                            WHEN 'Jago / Jago Syariah'        THEN 14
                            WHEN 'JakOne Pay'                 THEN 15
                            WHEN 'Jenius Pay'                 THEN 16
                            WHEN 'OCTO Clicks'                THEN 17
                            WHEN 'QRIS'                       THEN 18
                            WHEN 'Kartu kredit/debit'         THEN 19
                            WHEN 'DirectDebit'                THEN 21
                            WHEN 'GoPay Later'                THEN 24
                            WHEN 'Kredivo'                    THEN 25
                            WHEN 'BRI Ceria'                  THEN 26
                            WHEN 'PayLater'                   THEN 27
                            WHEN 'TikTok Shop Balance'        THEN 28
                            WHEN 'Saldo'                      THEN 28
                            WHEN 'Tokopedia History Order'    THEN 35
                            ELSE NULL
                        END,
                        CASE WHEN NULLIF(NULLIF(TRIM(o.created_time), 'nan'), '') IS NOT NULL
                             THEN TO_TIMESTAMP(TRIM(o.created_time), 'DD/MM/YYYY HH24:MI:SS')::DATE ELSE NULL END,
                        CASE WHEN NULLIF(NULLIF(TRIM(o.created_time), 'nan'), '') IS NOT NULL
                             THEN CAST(TO_CHAR(TO_TIMESTAMP(TRIM(o.created_time), 'DD/MM/YYYY HH24:MI:SS')::DATE, 'YYYYMMDD') AS INT)
                             ELSE NULL END,
                        NULLIF(TRIM(o.tokopedia_invoice_number), 'nan'),
                        CASE WHEN TRIM(o.normal_or_pre_order) ILIKE 'pre%' THEN TRUE ELSE FALSE END,
                        NULLIF(NULLIF(TRIM(o.quantity), 'nan'), '')::INT,
                        COALESCE(NULLIF(NULLIF(TRIM(o.sku_quantity_of_return), 'nan'), '')::INT, 0),
                        NULLIF(NULLIF(TRIM(o.sku_unit_original_price), 'nan'), '')::NUMERIC,
                        ABS(COALESCE(NULLIF(NULLIF(TRIM(o.sku_seller_discount), 'nan'), '')::NUMERIC, 0))
                            + ABS(COALESCE(NULLIF(NULLIF(TRIM(o.sku_platform_discount), 'nan'), '')::NUMERIC, 0)),
                        NULLIF(NULLIF(TRIM(o.sku_subtotal_after_discount), 'nan'), '')::NUMERIC,
                        'tiktok_tokopedia',
                        o.source_filename
                    FROM stg_tiktok_tokopedia_orders o
                    LEFT JOIN _tmp_channel_map cm
                        ON cm.nama_toko = LOWER(TRIM(o.nama_toko))
                       AND cm.purchase_channel = LOWER(TRIM(o.purchase_channel))
                    LEFT JOIN dim_sku_alias dsa ON dsa.sku_alias = NULLIF(TRIM(o.seller_sku), 'nan')
                    LEFT JOIN dim_product dp ON dp.sku_code = COALESCE(
                        (SELECT dp1.sku_code FROM dim_product dp1
                         WHERE dp1.sku_code = NULLIF(TRIM(o.seller_sku), 'nan') LIMIT 1),
                        dsa.sku_code)
                    LEFT JOIN dim_customer dc
                        ON dc.marketplace_id = 5 AND dc.username = o.buyer_username
                    LEFT JOIN dim_sales_channel dsc ON dsc.sales_channel_id = cm.sales_channel_id
                    WHERE cm.sales_channel_id IS NOT NULL
                      AND dp.product_id IS NOT NULL
                    ON CONFLICT (order_id, product_id, sales_channel_id)
                        WHERE product_id IS NOT NULL
                    DO NOTHING
                """)
                sql_unknown = text("""
                    INSERT INTO fact_sales_online (
                        order_id, product_id, customer_id, sales_channel_id,
                        store_id, marketplace_id, order_status_id, payment_method_id,
                        order_date, order_date_id, invoice_number, is_pre_order,
                        qty_sold, qty_returned,
                        price_original_unit, amt_product_discount, amt_gross_revenue,
                        source_marketplace, source_filename
                    )
                    SELECT
                        o.order_id,
                        NULL,
                        dc.customer_id,
                        cm.sales_channel_id,
                        dsc.store_id,
                        dsc.marketplace_id,
                        CASE o.order_status
                            WHEN 'Belum dibayar' THEN 1
                            WHEN 'Perlu dikirim' THEN 2
                            WHEN 'Dikirim'       THEN 3
                            WHEN 'Selesai'       THEN 7
                            WHEN 'Dibatalkan'    THEN 9
                            ELSE NULL
                        END,
                        CASE o.payment_method
                            WHEN 'Bayar di tempat'            THEN 1
                            WHEN 'Cash'                       THEN 1
                            WHEN 'KlikBCA'                    THEN 2
                            WHEN 'BRImo'                      THEN 4
                            WHEN 'Transfer bank'              THEN 8
                            WHEN 'Bank Transfer (Manual VA)'  THEN 8
                            WHEN 'GoPay'                      THEN 9
                            WHEN 'OVO'                        THEN 10
                            WHEN 'DANA'                       THEN 11
                            WHEN 'LinkAja'                    THEN 13
                            WHEN 'Jago / Jago Syariah'        THEN 14
                            WHEN 'JakOne Pay'                 THEN 15
                            WHEN 'Jenius Pay'                 THEN 16
                            WHEN 'OCTO Clicks'                THEN 17
                            WHEN 'QRIS'                       THEN 18
                            WHEN 'Kartu kredit/debit'         THEN 19
                            WHEN 'DirectDebit'                THEN 21
                            WHEN 'GoPay Later'                THEN 24
                            WHEN 'Kredivo'                    THEN 25
                            WHEN 'BRI Ceria'                  THEN 26
                            WHEN 'PayLater'                   THEN 27
                            WHEN 'TikTok Shop Balance'        THEN 28
                            WHEN 'Saldo'                      THEN 28
                            WHEN 'Tokopedia History Order'    THEN 35
                            ELSE NULL
                        END,
                        CASE WHEN NULLIF(NULLIF(TRIM(o.created_time), 'nan'), '') IS NOT NULL
                             THEN TO_TIMESTAMP(TRIM(o.created_time), 'DD/MM/YYYY HH24:MI:SS')::DATE ELSE NULL END,
                        CASE WHEN NULLIF(NULLIF(TRIM(o.created_time), 'nan'), '') IS NOT NULL
                             THEN CAST(TO_CHAR(TO_TIMESTAMP(TRIM(o.created_time), 'DD/MM/YYYY HH24:MI:SS')::DATE, 'YYYYMMDD') AS INT)
                             ELSE NULL END,
                        NULLIF(TRIM(o.tokopedia_invoice_number), 'nan'),
                        CASE WHEN TRIM(o.normal_or_pre_order) ILIKE 'pre%' THEN TRUE ELSE FALSE END,
                        NULLIF(NULLIF(TRIM(o.quantity), 'nan'), '')::INT,
                        COALESCE(NULLIF(NULLIF(TRIM(o.sku_quantity_of_return), 'nan'), '')::INT, 0),
                        NULLIF(NULLIF(TRIM(o.sku_unit_original_price), 'nan'), '')::NUMERIC,
                        ABS(COALESCE(NULLIF(NULLIF(TRIM(o.sku_seller_discount), 'nan'), '')::NUMERIC, 0))
                            + ABS(COALESCE(NULLIF(NULLIF(TRIM(o.sku_platform_discount), 'nan'), '')::NUMERIC, 0)),
                        NULLIF(NULLIF(TRIM(o.sku_subtotal_after_discount), 'nan'), '')::NUMERIC,
                        'tiktok_tokopedia',
                        o.source_filename
                    FROM stg_tiktok_tokopedia_orders o
                    LEFT JOIN _tmp_channel_map cm
                        ON cm.nama_toko = LOWER(TRIM(o.nama_toko))
                       AND cm.purchase_channel = LOWER(TRIM(o.purchase_channel))
                    LEFT JOIN dim_sku_alias dsa ON dsa.sku_alias = NULLIF(TRIM(o.seller_sku), 'nan')
                    LEFT JOIN dim_product dp ON dp.sku_code = COALESCE(
                        (SELECT dp1.sku_code FROM dim_product dp1
                         WHERE dp1.sku_code = NULLIF(TRIM(o.seller_sku), 'nan') LIMIT 1),
                        dsa.sku_code)
                    LEFT JOIN dim_customer dc
                        ON dc.marketplace_id = 5 AND dc.username = o.buyer_username
                    LEFT JOIN dim_sales_channel dsc ON dsc.sales_channel_id = cm.sales_channel_id
                    WHERE cm.sales_channel_id IS NOT NULL
                      AND dp.product_id IS NULL
                    ON CONFLICT (order_id, sales_channel_id)
                        WHERE product_id IS NULL
                    DO NOTHING
                """)
                r1 = conn.execute(sql_known)
                r2 = conn.execute(sql_unknown)
                logger.info(f"✅ fact_sales_online TikTok/Tokopedia: {r1.rowcount + r2.rowcount} baris")

            elif marketplace == 'lazada':
                sql_known = text("""
                    INSERT INTO fact_sales_online (
                        order_id, product_id, customer_id, sales_channel_id,
                        store_id, marketplace_id, order_status_id, payment_method_id,
                        order_date, order_date_id, invoice_number, is_pre_order,
                        qty_sold, qty_returned,
                        price_original_unit, amt_product_discount, amt_gross_revenue,
                        source_marketplace, source_filename
                    )
                    SELECT
                        o.order_number,
                        dp.product_id,
                        dc.customer_id,
                        cm.sales_channel_id,
                        dsc.store_id,
                        dsc.marketplace_id,
                        CASE o.status
                            WHEN 'ready_to_ship'                    THEN 2
                            WHEN 'shipped'                          THEN 3
                            WHEN 'confirmed'                        THEN 5
                            WHEN 'delivered'                        THEN 7
                            WHEN 'canceled'                         THEN 9
                            WHEN 'returned'                         THEN 10
                            WHEN 'Package Returned'                 THEN 10
                            WHEN 'In Transit: Returning to seller'  THEN 10
                            WHEN 'Lost by 3PL'                      THEN 11
                            WHEN 'Damaged by 3PL'                   THEN 11
                            WHEN 'Package scrapped'                 THEN 11
                            ELSE NULL
                        END,
                        CASE o.pay_method
                            WHEN 'COD'                THEN 1
                            WHEN 'BCA_VA'             THEN 2
                            WHEN 'KLIKBCA_VA'         THEN 2
                            WHEN 'BNI_VA'             THEN 3
                            WHEN 'BRI_VA'             THEN 4
                            WHEN 'MANDIRIMANDIRI_VA'  THEN 5
                            WHEN 'CIMB_VA'            THEN 6
                            WHEN 'PANIN_VA'           THEN 7
                            WHEN 'GOPAY_WALLET'       THEN 9
                            WHEN 'WALLET_OVO'         THEN 10
                            WHEN 'DANA_WALLET'        THEN 11
                            WHEN 'QRIS'               THEN 18
                            WHEN 'MIXEDCARD'          THEN 19
                            WHEN 'CREDITPAY_KREDIVO'  THEN 25
                            WHEN 'PAY_LATER'          THEN 27
                            WHEN 'SALDO'              THEN 29
                            WHEN 'ALFAMART_OTC'       THEN 30
                            WHEN 'INDOMARET_OTC'      THEN 31
                            WHEN 'PURE_ZERO_PRICE'    THEN 34
                            ELSE NULL
                        END,
                        CASE WHEN NULLIF(NULLIF(TRIM(o.create_time), 'nan'), '') IS NOT NULL
                             THEN TO_TIMESTAMP(TRIM(o.create_time), 'DD Mon YYYY HH24:MI')::DATE
                             ELSE NULL END,
                        CASE WHEN NULLIF(NULLIF(TRIM(o.create_time), 'nan'), '') IS NOT NULL
                             THEN CAST(TO_CHAR(
                                 TO_TIMESTAMP(TRIM(o.create_time), 'DD Mon YYYY HH24:MI')::DATE,
                                 'YYYYMMDD') AS INT)
                             ELSE NULL END,
                        NULLIF(TRIM(o.invoice_number), 'nan'),
                        FALSE,
                        1,
                        0,
                        NULLIF(NULLIF(TRIM(o.unit_price), 'nan'), '')::NUMERIC,
                        ABS(COALESCE(NULLIF(NULLIF(TRIM(o.seller_discount_total), 'nan'), '')::NUMERIC, 0)),
                        CASE WHEN NULLIF(NULLIF(TRIM(o.unit_price), 'nan'), '') IS NOT NULL
                             THEN NULLIF(NULLIF(TRIM(o.unit_price), 'nan'), '')::NUMERIC
                                  - ABS(COALESCE(NULLIF(NULLIF(TRIM(o.seller_discount_total), 'nan'), '')::NUMERIC, 0))
                             ELSE NULL END,
                        'lazada',
                        o.source_filename
                    FROM stg_lazada_orders o
                    LEFT JOIN _tmp_channel_map cm ON cm.nama_toko = LOWER(TRIM(o.nama_toko))
                    LEFT JOIN dim_sku_alias dsa ON dsa.sku_alias = NULLIF(TRIM(o.seller_sku), 'nan')
                    LEFT JOIN dim_product dp ON dp.sku_code = COALESCE(
                        (SELECT dp1.sku_code FROM dim_product dp1 WHERE dp1.sku_code = (
                            CASE WHEN NULLIF(TRIM(o.seller_sku),'nan') ~ '^P[0-9]'
                                 THEN 'B'||SUBSTRING(NULLIF(TRIM(o.seller_sku),'nan'),2)
                                 ELSE NULLIF(TRIM(o.seller_sku),'nan')
                            END) LIMIT 1),
                        dsa.sku_code)
                    LEFT JOIN dim_customer dc
                        ON dc.marketplace_id = 4 AND dc.username = o.customer_name
                    LEFT JOIN dim_sales_channel dsc ON dsc.sales_channel_id = cm.sales_channel_id
                    WHERE cm.sales_channel_id IS NOT NULL
                      AND dp.product_id IS NOT NULL
                    ON CONFLICT (order_id, product_id, sales_channel_id)
                        WHERE product_id IS NOT NULL
                    DO NOTHING
                """)
                sql_unknown = text("""
                    INSERT INTO fact_sales_online (
                        order_id, product_id, customer_id, sales_channel_id,
                        store_id, marketplace_id, order_status_id, payment_method_id,
                        order_date, order_date_id, invoice_number, is_pre_order,
                        qty_sold, qty_returned,
                        price_original_unit, amt_product_discount, amt_gross_revenue,
                        source_marketplace, source_filename
                    )
                    SELECT
                        o.order_number,
                        NULL,
                        dc.customer_id,
                        cm.sales_channel_id,
                        dsc.store_id,
                        dsc.marketplace_id,
                        CASE o.status
                            WHEN 'ready_to_ship'                    THEN 2
                            WHEN 'shipped'                          THEN 3
                            WHEN 'confirmed'                        THEN 5
                            WHEN 'delivered'                        THEN 7
                            WHEN 'canceled'                         THEN 9
                            WHEN 'returned'                         THEN 10
                            WHEN 'Package Returned'                 THEN 10
                            WHEN 'In Transit: Returning to seller'  THEN 10
                            WHEN 'Lost by 3PL'                      THEN 11
                            WHEN 'Damaged by 3PL'                   THEN 11
                            WHEN 'Package scrapped'                 THEN 11
                            ELSE NULL
                        END,
                        CASE o.pay_method
                            WHEN 'COD'                THEN 1
                            WHEN 'BCA_VA'             THEN 2
                            WHEN 'KLIKBCA_VA'         THEN 2
                            WHEN 'BNI_VA'             THEN 3
                            WHEN 'BRI_VA'             THEN 4
                            WHEN 'MANDIRIMANDIRI_VA'  THEN 5
                            WHEN 'CIMB_VA'            THEN 6
                            WHEN 'PANIN_VA'           THEN 7
                            WHEN 'GOPAY_WALLET'       THEN 9
                            WHEN 'WALLET_OVO'         THEN 10
                            WHEN 'DANA_WALLET'        THEN 11
                            WHEN 'QRIS'               THEN 18
                            WHEN 'MIXEDCARD'          THEN 19
                            WHEN 'CREDITPAY_KREDIVO'  THEN 25
                            WHEN 'PAY_LATER'          THEN 27
                            WHEN 'SALDO'              THEN 29
                            WHEN 'ALFAMART_OTC'       THEN 30
                            WHEN 'INDOMARET_OTC'      THEN 31
                            WHEN 'PURE_ZERO_PRICE'    THEN 34
                            ELSE NULL
                        END,
                        CASE WHEN NULLIF(NULLIF(TRIM(o.create_time), 'nan'), '') IS NOT NULL
                             THEN TO_TIMESTAMP(TRIM(o.create_time), 'DD Mon YYYY HH24:MI')::DATE
                             ELSE NULL END,
                        CASE WHEN NULLIF(NULLIF(TRIM(o.create_time), 'nan'), '') IS NOT NULL
                             THEN CAST(TO_CHAR(
                                 TO_TIMESTAMP(TRIM(o.create_time), 'DD Mon YYYY HH24:MI')::DATE,
                                 'YYYYMMDD') AS INT)
                             ELSE NULL END,
                        NULLIF(TRIM(o.invoice_number), 'nan'),
                        FALSE,
                        1,
                        0,
                        NULLIF(NULLIF(TRIM(o.unit_price), 'nan'), '')::NUMERIC,
                        ABS(COALESCE(NULLIF(NULLIF(TRIM(o.seller_discount_total), 'nan'), '')::NUMERIC, 0)),
                        CASE WHEN NULLIF(NULLIF(TRIM(o.unit_price), 'nan'), '') IS NOT NULL
                             THEN NULLIF(NULLIF(TRIM(o.unit_price), 'nan'), '')::NUMERIC
                                  - ABS(COALESCE(NULLIF(NULLIF(TRIM(o.seller_discount_total), 'nan'), '')::NUMERIC, 0))
                             ELSE NULL END,
                        'lazada',
                        o.source_filename
                    FROM stg_lazada_orders o
                    LEFT JOIN _tmp_channel_map cm ON cm.nama_toko = LOWER(TRIM(o.nama_toko))
                    LEFT JOIN dim_sku_alias dsa ON dsa.sku_alias = NULLIF(TRIM(o.seller_sku), 'nan')
                    LEFT JOIN dim_product dp ON dp.sku_code = COALESCE(
                        (SELECT dp1.sku_code FROM dim_product dp1 WHERE dp1.sku_code = (
                            CASE WHEN NULLIF(TRIM(o.seller_sku),'nan') ~ '^P[0-9]'
                                 THEN 'B'||SUBSTRING(NULLIF(TRIM(o.seller_sku),'nan'),2)
                                 ELSE NULLIF(TRIM(o.seller_sku),'nan')
                            END) LIMIT 1),
                        dsa.sku_code)
                    LEFT JOIN dim_customer dc
                        ON dc.marketplace_id = 4 AND dc.username = o.customer_name
                    LEFT JOIN dim_sales_channel dsc ON dsc.sales_channel_id = cm.sales_channel_id
                    WHERE cm.sales_channel_id IS NOT NULL
                      AND dp.product_id IS NULL
                    ON CONFLICT (order_id, sales_channel_id)
                        WHERE product_id IS NULL
                    DO NOTHING
                """)
                r1 = conn.execute(sql_known)
                r2 = conn.execute(sql_unknown)
                logger.info(f"✅ fact_sales_online Lazada: {r1.rowcount + r2.rowcount} baris")

            else:
                logger.warning(f"Marketplace '{marketplace}' tidak dikenal untuk fact_sales_online.")

    except Exception as e:
        logger.error(f"❌ fact_sales_online gagal untuk {marketplace}: {e}")


# ============================================================
# TRANSFORM 6: fact_settlement  (Phase 2)
# Sumber: stg_*_income
# ============================================================

def transform_fact_settlement(engine, marketplace):
    logger.info(f"[TRANSFORM] fact_settlement ← {marketplace}")
    try:
        with engine.begin() as conn:
            _create_temp_tables(conn)
            _load_channel_map(conn, marketplace)

            if marketplace == 'shopee':
                sql = text("""
                    INSERT INTO fact_settlement (
                        order_id, sales_channel_id,
                        amt_settled,
                        time_funds_released, settlement_date_id,
                        source_marketplace, source_filename
                    )
                    SELECT
                        o.no_pesanan,
                        cm.sales_channel_id,
                        NULLIF(NULLIF(TRIM(o.total_penghasilan), 'nan'), '')::NUMERIC,
                        CASE WHEN NULLIF(NULLIF(NULLIF(TRIM(o.tanggal_dana_dilepaskan), 'nan'), ''), '-') IS NOT NULL
                             THEN TRIM(o.tanggal_dana_dilepaskan)::DATE::TIMESTAMP
                             ELSE NULL END,
                        CASE WHEN NULLIF(NULLIF(NULLIF(TRIM(o.tanggal_dana_dilepaskan), 'nan'), ''), '-') IS NOT NULL
                             THEN CAST(TO_CHAR(TRIM(o.tanggal_dana_dilepaskan)::DATE, 'YYYYMMDD') AS INT)
                             ELSE NULL END,
                        'shopee',
                        o.source_filename
                    FROM stg_shopee_income_main o
                    LEFT JOIN _tmp_channel_map cm ON cm.nama_toko = LOWER(TRIM(o.nama_toko))
                    WHERE cm.sales_channel_id IS NOT NULL
                      AND NULLIF(TRIM(o.no_pesanan), 'nan') IS NOT NULL
                    ON CONFLICT (order_id, sales_channel_id) DO NOTHING
                """)
                result = conn.execute(sql)
                logger.info(f"✅ fact_settlement Shopee: {result.rowcount} baris")

            elif marketplace == 'tiktok_tokopedia':
                sql = text("""
                    INSERT INTO fact_settlement (
                        order_id, sales_channel_id,
                        amt_settled,
                        time_funds_released, settlement_date_id,
                        source_marketplace, source_filename
                    )
                    SELECT
                        o.order_adjustment_id,
                        cm.sales_channel_id,
                        NULLIF(NULLIF(TRIM(o.total_settlement_amount), 'nan'), '')::NUMERIC,
                        CASE WHEN NULLIF(NULLIF(TRIM(o.order_settled_time), 'nan'), '') IS NOT NULL
                             THEN TRIM(o.order_settled_time)::DATE::TIMESTAMP
                             ELSE NULL END,
                        CASE WHEN NULLIF(NULLIF(TRIM(o.order_settled_time), 'nan'), '') IS NOT NULL
                             THEN CAST(TO_CHAR(TRIM(o.order_settled_time)::DATE, 'YYYYMMDD') AS INT)
                             ELSE NULL END,
                        'tiktok_tokopedia',
                        o.source_filename
                    FROM stg_tiktok_tokopedia_income o
                    LEFT JOIN _tmp_channel_map cm
                        ON cm.nama_toko = LOWER(TRIM(o.nama_toko))
                       AND cm.purchase_channel = CASE
                           WHEN LOWER(TRIM(o.order_source)) LIKE 'tiktok%' THEN 'tiktok'
                           WHEN LOWER(TRIM(o.order_source)) LIKE 'tokopedia%' THEN 'tokopedia'
                           ELSE LOWER(TRIM(o.order_source))
                       END
                    WHERE cm.sales_channel_id IS NOT NULL
                      AND NULLIF(TRIM(o.order_adjustment_id), 'nan') IS NOT NULL
                      AND o.type = 'Order'
                    ON CONFLICT (order_id, sales_channel_id) DO NOTHING
                """)
                result = conn.execute(sql)
                logger.info(f"✅ fact_settlement TikTok/Tokopedia: {result.rowcount} baris")

            elif marketplace == 'lazada':
                # Lazada income adalah narrow format (satu baris per fee per order)
                # → aggregate per order untuk menghitung net settlement
                sql = text("""
                    INSERT INTO fact_settlement (
                        order_id, sales_channel_id,
                        amt_settled,
                        time_funds_released, settlement_date_id,
                        source_marketplace, source_filename
                    )
                    SELECT
                        sub.order_id,
                        sub.sales_channel_id,
                        sub.amt_settled,
                        sub.time_funds_released,
                        CASE WHEN sub.time_funds_released IS NOT NULL
                             THEN CAST(TO_CHAR(sub.time_funds_released::DATE, 'YYYYMMDD') AS INT)
                             ELSE NULL END,
                        'lazada',
                        sub.source_filename
                    FROM (
                        SELECT
                            COALESCE(
                                NULLIF(TRIM(o.nomor_pesanan), 'nan'),
                                NULLIF(TRIM(o.id_pesanan), 'nan')
                            ) AS order_id,
                            cm.sales_channel_id,
                            SUM(NULLIF(REPLACE(TRIM(o.jumlah_termasuk_pajak), ',', ''), 'nan')::NUMERIC)
                                AS amt_settled,
                            MAX(CASE WHEN NULLIF(NULLIF(TRIM(o.tanggal_dilepas), 'nan'), '') IS NOT NULL
                                     THEN TO_TIMESTAMP(TRIM(o.tanggal_dilepas), 'DD Mon YYYY HH24:MI')
                                     ELSE NULL END)
                                AS time_funds_released,
                            MIN(o.source_filename) AS source_filename
                        FROM stg_lazada_income o
                        LEFT JOIN _tmp_channel_map cm ON cm.nama_toko = LOWER(TRIM(o.nama_toko))
                        WHERE cm.sales_channel_id IS NOT NULL
                          AND COALESCE(
                                NULLIF(TRIM(o.nomor_pesanan), 'nan'),
                                NULLIF(TRIM(o.id_pesanan), 'nan')
                              ) IS NOT NULL
                          AND NULLIF(REPLACE(TRIM(o.jumlah_termasuk_pajak), ',', ''), 'nan') IS NOT NULL
                        GROUP BY 1, 2
                    ) sub
                    ON CONFLICT (order_id, sales_channel_id) DO NOTHING
                """)
                result = conn.execute(sql)
                logger.info(f"✅ fact_settlement Lazada: {result.rowcount} baris")

            else:
                logger.warning(f"Marketplace '{marketplace}' tidak dikenal untuk fact_settlement.")

    except Exception as e:
        logger.error(f"❌ fact_settlement gagal untuk {marketplace}: {e}")


# ============================================================
# TRANSFORM 7: fact_order_fees  (Phase 2)
# Sumber: stg_*_income — unpivot wide→narrow (TikTok & Shopee),
#         lookup narrow (Lazada & Shopee ADJ)
# ============================================================

def transform_fact_order_fees(engine, marketplace):
    logger.info(f"[TRANSFORM] fact_order_fees ← {marketplace}")
    try:
        with engine.begin() as conn:
            _create_temp_tables(conn)
            _load_channel_map(conn, marketplace)

            if marketplace == 'tiktok_tokopedia':
                # Bangun VALUES clause untuk CROSS JOIN LATERAL unpivot
                _fee_values = ",\n                            ".join(
                    f"({fid}, NULLIF(NULLIF(TRIM(o.{col}), 'nan'), '')::NUMERIC)"
                    for col, fid in TIKTOK_INCOME_FEE_COLS.items()
                )
                sql = text(f"""
                    INSERT INTO fact_order_fees (
                        order_id, fee_type_id, sales_channel_id,
                        fee_amount, source_marketplace, source_filename
                    )
                    SELECT
                        sub.order_id, sub.fee_type_id, sub.sales_channel_id,
                        SUM(ABS(sub.fee_value)) AS fee_amount,
                        sub.source_marketplace,
                        MIN(sub.source_filename)
                    FROM (
                        SELECT
                            o.order_adjustment_id   AS order_id,
                            cm.sales_channel_id,
                            u.fee_type_id,
                            u.fee_value,
                            'tiktok_tokopedia'      AS source_marketplace,
                            o.source_filename
                        FROM stg_tiktok_tokopedia_income o
                        LEFT JOIN _tmp_channel_map cm
                            ON cm.nama_toko = LOWER(TRIM(o.nama_toko))
                           AND cm.purchase_channel = CASE
                               WHEN LOWER(TRIM(o.order_source)) LIKE 'tiktok%' THEN 'tiktok'
                               WHEN LOWER(TRIM(o.order_source)) LIKE 'tokopedia%' THEN 'tokopedia'
                               ELSE LOWER(TRIM(o.order_source))
                           END
                        CROSS JOIN LATERAL (VALUES
                            {_fee_values}
                        ) AS u(fee_type_id, fee_value)
                        WHERE cm.sales_channel_id IS NOT NULL
                          AND o.type = 'Order'
                          AND NULLIF(TRIM(o.order_adjustment_id), 'nan') IS NOT NULL
                          AND u.fee_value IS NOT NULL
                          AND u.fee_value <> 0
                    ) sub
                    GROUP BY sub.order_id, sub.fee_type_id, sub.sales_channel_id, sub.source_marketplace, sub.source_filename
                    ON CONFLICT (order_id, fee_type_id, sales_channel_id) DO NOTHING
                """)
                result = conn.execute(sql)
                logger.info(f"✅ fact_order_fees TikTok/Tokopedia: {result.rowcount} baris")
                # LAPIS 2: cek kolom baru yang belum ter-mapping
                _warn_unmapped_wide_cols(
                    conn, 'stg_tiktok_tokopedia_income',
                    TIKTOK_INCOME_FEE_COLS, TIKTOK_NON_FEE_COLS,
                    'TikTok/Tokopedia'
                )

            elif marketplace == 'shopee':
                # ── income_main: wide format ──────────────────────────────
                _main_fee_values = ",\n                            ".join(
                    f"({fid}, NULLIF(NULLIF(TRIM(o.{col}), 'nan'), '')::NUMERIC)"
                    for col, fid in SHOPEE_INCOME_MAIN_FEE_COLS.items()
                )
                sql_main = text(f"""
                    INSERT INTO fact_order_fees (
                        order_id, fee_type_id, sales_channel_id,
                        fee_amount, source_marketplace, source_filename
                    )
                    SELECT
                        sub.order_id, sub.fee_type_id, sub.sales_channel_id,
                        SUM(ABS(sub.fee_value)) AS fee_amount,
                        sub.source_marketplace,
                        MIN(sub.source_filename)
                    FROM (
                        SELECT
                            o.no_pesanan            AS order_id,
                            cm.sales_channel_id,
                            u.fee_type_id,
                            u.fee_value,
                            'shopee'                AS source_marketplace,
                            o.source_filename
                        FROM stg_shopee_income_main o
                        LEFT JOIN _tmp_channel_map cm ON cm.nama_toko = LOWER(TRIM(o.nama_toko))
                        CROSS JOIN LATERAL (VALUES
                            {_main_fee_values}
                        ) AS u(fee_type_id, fee_value)
                        WHERE cm.sales_channel_id IS NOT NULL
                          AND NULLIF(TRIM(o.no_pesanan), 'nan') IS NOT NULL
                          AND u.fee_value IS NOT NULL
                          AND u.fee_value <> 0
                    ) sub
                    GROUP BY sub.order_id, sub.fee_type_id, sub.sales_channel_id, sub.source_marketplace, sub.source_filename
                    ON CONFLICT (order_id, fee_type_id, sales_channel_id) DO NOTHING
                """)

                # ── income_sf: XTRA fees + harbolnas (duplikat kolom → SUM) ──
                sql_sf = text("""
                    INSERT INTO fact_order_fees (
                        order_id, fee_type_id, sales_channel_id,
                        fee_amount, source_marketplace, source_filename
                    )
                    SELECT
                        sub.order_id, sub.fee_type_id, sub.sales_channel_id,
                        SUM(ABS(sub.fee_value)) AS fee_amount,
                        sub.source_marketplace,
                        MIN(sub.source_filename)
                    FROM (
                        SELECT
                            o.no_pesanan    AS order_id,
                            cm.sales_channel_id,
                            u.fee_type_id,
                            u.fee_value,
                            'shopee'        AS source_marketplace,
                            o.source_filename
                        FROM stg_shopee_income_service_fee o
                        LEFT JOIN _tmp_channel_map cm ON cm.nama_toko = LOWER(TRIM(o.nama_toko))
                        CROSS JOIN LATERAL (VALUES
                            (102, NULLIF(NULLIF(TRIM(o.biaya_pembayaran), 'nan'), '')::NUMERIC),
                            (106,
                                COALESCE(NULLIF(NULLIF(TRIM(o.biaya_layanan_gratis_ongkir_xtra),   'nan'), '')::NUMERIC, 0)
                              + COALESCE(NULLIF(NULLIF(TRIM(o.biaya_layanan_gratis_ongkir_xtra_2), 'nan'), '')::NUMERIC, 0)),
                            (107, NULLIF(NULLIF(TRIM(o.biaya_layanan_promo_xtra), 'nan'), '')::NUMERIC),
                            (108,
                                COALESCE(NULLIF(NULLIF(TRIM(o.biaya_layanan_cashback_xtra),  'nan'), '')::NUMERIC, 0)
                              + COALESCE(NULLIF(NULLIF(TRIM(o.biaya_layanan_cashbackxtra),   'nan'), '')::NUMERIC, 0)),
                            (109, NULLIF(NULLIF(TRIM(o.biaya_program_shopee_live_xtra), 'nan'), '')::NUMERIC),
                            (110,
                                COALESCE(NULLIF(NULLIF(TRIM(o.biaya_campaign_1_1),   'nan'), '')::NUMERIC, 0)
                              + COALESCE(NULLIF(NULLIF(TRIM(o.biaya_campaign_2_2),   'nan'), '')::NUMERIC, 0)
                              + COALESCE(NULLIF(NULLIF(TRIM(o.biaya_campaign_3_3),   'nan'), '')::NUMERIC, 0)
                              + COALESCE(NULLIF(NULLIF(TRIM(o.biaya_campaign_4_4),   'nan'), '')::NUMERIC, 0)
                              + COALESCE(NULLIF(NULLIF(TRIM(o.biaya_campaign_5_5),   'nan'), '')::NUMERIC, 0)
                              + COALESCE(NULLIF(NULLIF(TRIM(o.biaya_campaign_6_6),   'nan'), '')::NUMERIC, 0)
                              + COALESCE(NULLIF(NULLIF(TRIM(o.biaya_campaign_7_7),   'nan'), '')::NUMERIC, 0)
                              + COALESCE(NULLIF(NULLIF(TRIM(o.biaya_campaign_8_8),   'nan'), '')::NUMERIC, 0)
                              + COALESCE(NULLIF(NULLIF(TRIM(o.biaya_campaign_9_9),   'nan'), '')::NUMERIC, 0)
                              + COALESCE(NULLIF(NULLIF(TRIM(o.biaya_campaign_10_10), 'nan'), '')::NUMERIC, 0)
                              + COALESCE(NULLIF(NULLIF(TRIM(o.biaya_campaign_11_11), 'nan'), '')::NUMERIC, 0)
                              + COALESCE(NULLIF(NULLIF(TRIM(o.biaya_campaign_12_12), 'nan'), '')::NUMERIC, 0))
                        ) AS u(fee_type_id, fee_value)
                        WHERE cm.sales_channel_id IS NOT NULL
                          AND NULLIF(TRIM(o.no_pesanan), 'nan') IS NOT NULL
                          AND u.fee_value IS NOT NULL
                          AND u.fee_value <> 0
                    ) sub
                    GROUP BY sub.order_id, sub.fee_type_id, sub.sales_channel_id, sub.source_marketplace, sub.source_filename
                    ON CONFLICT (order_id, fee_type_id, sales_channel_id) DO NOTHING
                """)

                # ── income_adj: narrow format → lookup fee_type_id by name ──
                sql_adj = text("""
                    INSERT INTO fact_order_fees (
                        order_id, fee_type_id, sales_channel_id,
                        fee_amount, source_marketplace, source_filename
                    )
                    SELECT
                        NULLIF(TRIM(o.no_pesanan_terhubung), 'nan'),
                        ft.fee_type_id,
                        cm.sales_channel_id,
                        ABS(NULLIF(NULLIF(TRIM(o.biaya_penyesuaian), 'nan'), '')::NUMERIC),
                        'shopee',
                        o.source_filename
                    FROM stg_shopee_income_adjustment o
                    LEFT JOIN _tmp_channel_map cm ON cm.nama_toko = LOWER(TRIM(o.nama_toko))
                    JOIN dim_fee_type ft
                        ON ft.fee_name = TRIM(o.tipe_penyesuaian_deskripsi)
                       AND ft.marketplace_name = 'Shopee'
                    WHERE cm.sales_channel_id IS NOT NULL
                      AND NULLIF(TRIM(o.no_pesanan_terhubung), 'nan') IS NOT NULL
                      AND NULLIF(NULLIF(TRIM(o.biaya_penyesuaian), 'nan'), '') IS NOT NULL
                      AND NULLIF(NULLIF(TRIM(o.biaya_penyesuaian), 'nan'), '')::NUMERIC <> 0
                    ON CONFLICT (order_id, fee_type_id, sales_channel_id) DO NOTHING
                """)

                _ensure_stg_fee_orphan(conn)
                r1 = conn.execute(sql_main)
                r2 = conn.execute(sql_sf)
                r3 = conn.execute(sql_adj)
                logger.info(
                    f"✅ fact_order_fees Shopee: {r1.rowcount} (main) + "
                    f"{r2.rowcount} (sf) + {r3.rowcount} (adj) baris"
                )
                # LAPIS 2: cek kolom baru yang belum ter-mapping (wide format)
                _warn_unmapped_wide_cols(
                    conn, 'stg_shopee_income_main',
                    SHOPEE_INCOME_MAIN_FEE_COLS, SHOPEE_MAIN_NON_FEE_COLS,
                    'Shopee Main'
                )
                _warn_unmapped_wide_cols(
                    conn, 'stg_shopee_income_service_fee',
                    SHOPEE_SF_MAPPED_FEE_COLS, SHOPEE_SF_NON_FEE_COLS,
                    'Shopee SF'
                )
                # LAPIS 2: cek fee_name yang tidak match dim_fee_type (narrow format)
                _warn_unmapped_narrow_fees(conn, 'shopee', 'Shopee Adj')
                # ORPHAN: simpan adj tanpa order_id ke stg_fee_orphan
                _save_shopee_adj_orphans(conn)

            elif marketplace == 'lazada':
                # Lazada income: narrow format → GROUP BY order+channel+fee_type (aggregate)
                sql = text("""
                    INSERT INTO fact_order_fees (
                        order_id, fee_type_id, sales_channel_id,
                        fee_amount, source_marketplace, source_filename
                    )
                    SELECT
                        sub.order_id,
                        sub.fee_type_id,
                        sub.sales_channel_id,
                        SUM(ABS(sub.fee_value)) AS fee_amount,
                        'lazada',
                        MIN(sub.source_filename)
                    FROM (
                        SELECT
                            COALESCE(
                                NULLIF(TRIM(o.nomor_pesanan), 'nan'),
                                NULLIF(TRIM(o.id_pesanan), 'nan')
                            )                       AS order_id,
                            cm.sales_channel_id,
                            ft.fee_type_id,
                            NULLIF(REPLACE(TRIM(o.jumlah_termasuk_pajak), ',', ''), 'nan')::NUMERIC
                                                    AS fee_value,
                            o.source_filename
                        FROM stg_lazada_income o
                        LEFT JOIN _tmp_channel_map cm ON cm.nama_toko = LOWER(TRIM(o.nama_toko))
                        JOIN dim_fee_type ft
                            ON ft.fee_name = TRIM(o.nama_biaya)
                           AND ft.marketplace_name = 'Lazada'
                        WHERE cm.sales_channel_id IS NOT NULL
                          AND COALESCE(
                                NULLIF(TRIM(o.nomor_pesanan), 'nan'),
                                NULLIF(TRIM(o.id_pesanan), 'nan')
                              ) IS NOT NULL
                          AND NULLIF(REPLACE(TRIM(o.jumlah_termasuk_pajak), ',', ''), 'nan') IS NOT NULL
                          AND NULLIF(REPLACE(TRIM(o.jumlah_termasuk_pajak), ',', ''), 'nan')::NUMERIC <> 0
                    ) sub
                    GROUP BY sub.order_id, sub.fee_type_id, sub.sales_channel_id, sub.source_filename
                    ON CONFLICT (order_id, fee_type_id, sales_channel_id) DO NOTHING
                """)
                result = conn.execute(sql)
                logger.info(f"✅ fact_order_fees Lazada: {result.rowcount} baris")
                # LAPIS 2: cek fee_name yang tidak match dim_fee_type (narrow format)
                _warn_unmapped_narrow_fees(conn, 'lazada', 'Lazada')

            else:
                logger.warning(f"Marketplace '{marketplace}' tidak dikenal untuk fact_order_fees.")

    except Exception as e:
        logger.error(f"❌ fact_order_fees gagal untuk {marketplace}: {e}")


# ============================================================
# LAPIS 3: Rekonsiliasi settlement
# Bandingkan net settlement kita vs ground truth dari data sumber
# ============================================================

def check_reconciliation(engine, marketplace):
    """
    LAPIS 3 — Rekonsiliasi settlement per order:
      our_net = gross_net_return + SUM(fee_amount × multiplying_factor)
    Dibandingkan dengan ground truth dari staging:
      Shopee  → stg_shopee_income_main.total_penghasilan
                + SUM(stg_shopee_income_adjustment.biaya_penyesuaian × adj_multiplying_factor)
      TikTok  → stg_tiktok_tokopedia_income.total_settlement_amount
      Lazada  → SUM(stg_lazada_income.jumlah_termasuk_pajak) per order

    Dua perbaikan vs versi awal:
      1. gross_rev disesuaikan untuk return: amt_gross_revenue × (qty_sold − qty_returned) / qty_sold
         Ini mencegah item yang di-return masih terhitung sebagai pendapatan.
      2. truth Shopee = income_main + income_adj per order.
         Tanpa ini, order dengan kompensasi (mis. paket hilang) tampak discrepancy
         karena income_main.total_penghasilan = 0 sementara kompensasi ada di income_adj.

    Log INFO jika semua cocok, log WARNING per order jika discrepancy > 0.01.
    """
    logger.info(f"[LAPIS 3] Rekonsiliasi settlement ← {marketplace.upper()}")
    try:
        with engine.connect() as conn:
            if marketplace == 'shopee':
                sql = text("""
                    WITH order_fees AS (
                        SELECT fof.order_id,
                               SUM(fof.fee_amount * ft.multiplying_factor) AS fee_impact
                        FROM fact_order_fees fof
                        JOIN dim_fee_type ft ON ft.fee_type_id = fof.fee_type_id
                        WHERE fof.source_marketplace = 'shopee'
                        GROUP BY fof.order_id
                    ),
                    gross AS (
                        -- FIX 1: kurangi gross untuk item yang dikembalikan.
                        -- amt_gross_revenue adalah nilai untuk seluruh qty_sold.
                        -- Untuk return sebagian: gross × (qty_sold − qty_returned) / qty_sold
                        -- Untuk full return: hasilnya 0 (tidak terhitung sebagai pendapatan)
                        SELECT
                            order_id,
                            SUM(
                                amt_gross_revenue
                                * (qty_sold - COALESCE(qty_returned, 0))::NUMERIC
                                / NULLIF(qty_sold, 0)
                            ) AS gross_rev
                        FROM fact_sales_online
                        WHERE source_marketplace = 'shopee'
                        GROUP BY order_id
                    ),
                    truth AS (
                        -- FIX 2: ground truth = income_main + adj per order.
                        -- income_adj (kompensasi, penyesuaian kampanye, dll.) tidak masuk ke
                        -- income_main.total_penghasilan, sehingga harus dijumlahkan terpisah.
                        SELECT
                            m.no_pesanan,
                            SUM(NULLIF(NULLIF(TRIM(m.total_penghasilan), 'nan'), '')::NUMERIC)
                            + COALESCE(
                                (SELECT SUM(
                                    ABS(NULLIF(NULLIF(TRIM(a.biaya_penyesuaian), 'nan'), '')::NUMERIC)
                                    * ft_a.multiplying_factor
                                 )
                                 FROM stg_shopee_income_adjustment a
                                 JOIN dim_fee_type ft_a
                                     ON ft_a.fee_name         = TRIM(a.tipe_penyesuaian_deskripsi)
                                    AND ft_a.marketplace_name = 'Shopee'
                                 WHERE NULLIF(TRIM(a.no_pesanan_terhubung), 'nan') = m.no_pesanan
                                   AND NULLIF(NULLIF(TRIM(a.biaya_penyesuaian), 'nan'), '') IS NOT NULL
                                   AND NULLIF(NULLIF(TRIM(a.biaya_penyesuaian), 'nan'), '')::NUMERIC <> 0
                                ), 0
                            )                                AS total_penghasilan
                        FROM stg_shopee_income_main m
                        WHERE NULLIF(NULLIF(TRIM(m.total_penghasilan), 'nan'), '') IS NOT NULL
                        GROUP BY m.no_pesanan
                    )
                    SELECT
                        t.no_pesanan                                     AS order_id,
                        COALESCE(g.gross_rev,   0)                       AS gross_rev,
                        COALESCE(f.fee_impact,  0)                       AS fee_impact,
                        COALESCE(g.gross_rev,   0)
                          + COALESCE(f.fee_impact, 0)                    AS our_net,
                        t.total_penghasilan                              AS ground_truth,
                        ABS(
                            COALESCE(g.gross_rev,  0)
                          + COALESCE(f.fee_impact, 0)
                          - t.total_penghasilan
                        )                                                AS discrepancy
                    FROM truth t
                    LEFT JOIN gross g ON g.order_id  = t.no_pesanan
                    LEFT JOIN order_fees f ON f.order_id = t.no_pesanan
                    WHERE ABS(
                        COALESCE(g.gross_rev,  0)
                      + COALESCE(f.fee_impact, 0)
                      - t.total_penghasilan
                    ) > 0.01
                    ORDER BY discrepancy DESC
                    LIMIT 50
                """)

            elif marketplace == 'tiktok_tokopedia':
                sql = text("""
                    WITH order_fees AS (
                        SELECT fof.order_id,
                               SUM(fof.fee_amount * ft.multiplying_factor) AS fee_impact
                        FROM fact_order_fees fof
                        JOIN dim_fee_type ft ON ft.fee_type_id = fof.fee_type_id
                        WHERE fof.source_marketplace = 'tiktok_tokopedia'
                        GROUP BY fof.order_id
                    ),
                    gross AS (
                        SELECT
                            order_id,
                            SUM(
                                amt_gross_revenue
                                * (qty_sold - COALESCE(qty_returned, 0))::NUMERIC
                                / NULLIF(qty_sold, 0)
                            ) AS gross_rev
                        FROM fact_sales_online
                        WHERE source_marketplace = 'tiktok_tokopedia'
                        GROUP BY order_id
                    ),
                    truth AS (
                        SELECT
                            order_adjustment_id,
                            SUM(NULLIF(NULLIF(TRIM(total_settlement_amount), 'nan'), '')::NUMERIC)
                                AS total_settlement
                        FROM stg_tiktok_tokopedia_income
                        WHERE type = 'Order'
                          AND NULLIF(TRIM(order_adjustment_id), 'nan') IS NOT NULL
                          AND NULLIF(NULLIF(TRIM(total_settlement_amount), 'nan'), '') IS NOT NULL
                        GROUP BY order_adjustment_id
                    )
                    SELECT
                        t.order_adjustment_id                            AS order_id,
                        COALESCE(g.gross_rev,   0)                       AS gross_rev,
                        COALESCE(f.fee_impact,  0)                       AS fee_impact,
                        COALESCE(g.gross_rev,   0)
                          + COALESCE(f.fee_impact, 0)                    AS our_net,
                        t.total_settlement                               AS ground_truth,
                        ABS(
                            COALESCE(g.gross_rev,  0)
                          + COALESCE(f.fee_impact, 0)
                          - t.total_settlement
                        )                                                AS discrepancy
                    FROM truth t
                    LEFT JOIN gross g ON g.order_id  = t.order_adjustment_id
                    LEFT JOIN order_fees f ON f.order_id = t.order_adjustment_id
                    WHERE ABS(
                        COALESCE(g.gross_rev,  0)
                      + COALESCE(f.fee_impact, 0)
                      - t.total_settlement
                    ) > 0.01
                    ORDER BY discrepancy DESC
                    LIMIT 50
                """)

            elif marketplace == 'lazada':
                # Lazada: ground truth = SUM semua jumlah_termasuk_pajak per order
                # (nilai sudah bertanda: positif=pendapatan, negatif=biaya)
                sql = text("""
                    WITH order_fees AS (
                        SELECT fof.order_id,
                               SUM(fof.fee_amount * ft.multiplying_factor) AS fee_impact
                        FROM fact_order_fees fof
                        JOIN dim_fee_type ft ON ft.fee_type_id = fof.fee_type_id
                        WHERE fof.source_marketplace = 'lazada'
                        GROUP BY fof.order_id
                    ),
                    gross AS (
                        SELECT
                            order_id,
                            SUM(
                                amt_gross_revenue
                                * (qty_sold - COALESCE(qty_returned, 0))::NUMERIC
                                / NULLIF(qty_sold, 0)
                            ) AS gross_rev
                        FROM fact_sales_online
                        WHERE source_marketplace = 'lazada'
                        GROUP BY order_id
                    ),
                    truth AS (
                        SELECT
                            COALESCE(
                                NULLIF(TRIM(nomor_pesanan), 'nan'),
                                NULLIF(TRIM(id_pesanan),   'nan')
                            ) AS order_id,
                            SUM(
                                NULLIF(REPLACE(TRIM(jumlah_termasuk_pajak), ',', ''), 'nan')::NUMERIC
                            ) AS total_settlement
                        FROM stg_lazada_income
                        WHERE COALESCE(
                                NULLIF(TRIM(nomor_pesanan), 'nan'),
                                NULLIF(TRIM(id_pesanan),   'nan')
                              ) IS NOT NULL
                          AND NULLIF(REPLACE(TRIM(jumlah_termasuk_pajak), ',', ''), 'nan') IS NOT NULL
                        GROUP BY 1
                    )
                    SELECT
                        t.order_id,
                        COALESCE(g.gross_rev,   0)                       AS gross_rev,
                        COALESCE(f.fee_impact,  0)                       AS fee_impact,
                        COALESCE(g.gross_rev,   0)
                          + COALESCE(f.fee_impact, 0)                    AS our_net,
                        t.total_settlement                               AS ground_truth,
                        ABS(
                            COALESCE(g.gross_rev,  0)
                          + COALESCE(f.fee_impact, 0)
                          - t.total_settlement
                        )                                                AS discrepancy
                    FROM truth t
                    LEFT JOIN gross g ON g.order_id  = t.order_id
                    LEFT JOIN order_fees f ON f.order_id = t.order_id
                    WHERE ABS(
                        COALESCE(g.gross_rev,  0)
                      + COALESCE(f.fee_impact, 0)
                      - t.total_settlement
                    ) > 0.01
                    ORDER BY discrepancy DESC
                    LIMIT 50
                """)

            else:
                logger.warning(f"Marketplace '{marketplace}' tidak dikenal untuk check_reconciliation.")
                return

            rows = conn.execute(sql).fetchall()
            if not rows:
                logger.info(
                    f"✅ LAPIS 3 [{marketplace.upper()}]: Semua order cocok — "
                    f"tidak ada discrepancy > 0.01."
                )
            else:
                logger.warning(
                    f"⚠️  LAPIS 3 [{marketplace.upper()}]: {len(rows)} order dengan discrepancy "
                    f"(top {len(rows)} ditampilkan):"
                )
                for row in rows:
                    logger.warning(
                        f"   order={row[0]}  gross={row[1]:,.2f}  fees={row[2]:,.2f}  "
                        f"kita={row[3]:,.2f}  truth={row[4]:,.2f}  diff={row[5]:,.2f}"
                    )

    except Exception as e:
        logger.error(f"❌ check_reconciliation gagal untuk {marketplace}: {e}")


# ============================================================
# ORCHESTRATOR: run_transform
# ============================================================

def run_transform(engine, marketplace):
    """
    Menjalankan seluruh pipeline TRANSFORM secara berurutan.
    Urutan penting karena ada dependensi antar tabel.
    """
    logger.info(f"🔄 Memulai TRANSFORM untuk marketplace: {marketplace.upper()}")

    transform_dim_customer(engine, marketplace)
    transform_fact_fulfillment_logistics(engine, marketplace)
    transform_fact_balance_transaction(engine, marketplace)
    transform_fact_returns_online(engine, marketplace)
    transform_fact_sales_online(engine, marketplace)
    transform_fact_settlement(engine, marketplace)
    transform_fact_order_fees(engine, marketplace)
    check_reconciliation(engine, marketplace)

    logger.info(f"✅ TRANSFORM selesai untuk {marketplace.upper()}")


# ============================================================
# TRANSFORM CREWDIBLE 1: fact_fulfillment_service_cost
# Grain: 1 baris per order (DISTINCT ON no_transaksi)
# ============================================================

def transform_fact_fulfillment_service_cost(engine):
    logger.info("[TRANSFORM] fact_fulfillment_service_cost ← stg_crewdible")
    try:
        with engine.begin() as conn:
            _create_crewdible_temp_tables(conn)
            _load_crewdible_maps(conn)

            sql = text("""
                INSERT INTO public.fact_fulfillment_service_cost (
                    order_id,
                    store_id, marketplace_id,
                    fulfillment_date_id, warehouse_id,
                    sender_name, sender_phone,
                    recipient_name, recipient_phone, recipient_address,
                    fulfillment_status, logistics_provider, booking_code, airway_bill_number,
                    order_value_declared,
                    transaction_fee, transaction_fee_tax,
                    packaging_cost, packaging_cost_tax,
                    quality_control_cost, quality_control_cost_tax,
                    shipping_label_cost, shipping_label_cost_tax,
                    logistics_cost, total_fulfillment_cost,
                    source_filename
                )
                    SELECT DISTINCT ON (s.no_transaksi)
                        s.no_transaksi,
                        sm.store_id,
                        mm.marketplace_id,
                        -- tanggal_transaksi tersimpan sebagai TEXT (pandas astype str).
                        -- Cek pola YYYY-MM-DD sebelum cast untuk skip serial Excel (e.g. '44927.0').
                        CASE
                            WHEN NULLIF(TRIM(s.tanggal_transaksi), '') IS NOT NULL
                             AND TRIM(s.tanggal_transaksi) ~ E'^\\d{4}-\\d{2}-\\d{2}'
                            THEN CAST(TO_CHAR(CAST(TRIM(s.tanggal_transaksi) AS DATE), 'YYYYMMDD') AS INT)
                        END,
                        wm.warehouse_id,
                        NULLIF(TRIM(s.pengirim), ''),
                        NULLIF(TRIM(s.no_hp_pengirim), ''),
                        NULLIF(TRIM(s.penerima), ''),
                        NULLIF(TRIM(s.no_hp_penerima), ''),
                        NULLIF(TRIM(s.alamat_penerima), ''),
                        NULLIF(TRIM(s.status), ''),
                        NULLIF(TRIM(s.logistik), ''),
                        NULLIF(TRIM(s.kode_booking), ''),
                        NULLIF(TRIM(s.no_awb), ''),
                        -- Semua kolom numerik: staging menyimpan sebagai TEXT → cast eksplisit
                        NULLIF(NULLIF(TRIM(s.total_nilai_transaksi), ''), 'nan')::NUMERIC,
                        NULLIF(NULLIF(TRIM(s.biaya_transaksi), ''), 'nan')::NUMERIC,
                        NULLIF(NULLIF(TRIM(s.ppn_biaya_transaksi), ''), 'nan')::NUMERIC,
                        NULLIF(NULLIF(TRIM(s.total_biaya_packaging), ''), 'nan')::NUMERIC,
                        NULLIF(NULLIF(TRIM(s.ppn_total_biaya_packaging), ''), 'nan')::NUMERIC,
                        NULLIF(NULLIF(TRIM(s.total_biaya_qc), ''), 'nan')::NUMERIC,
                        NULLIF(NULLIF(TRIM(s.ppn_total_biaya_qc), ''), 'nan')::NUMERIC,
                        NULLIF(NULLIF(TRIM(s.total_biaya_shipping_label), ''), 'nan')::NUMERIC,
                        NULLIF(NULLIF(TRIM(s.ppn_total_biaya_shipping_label), ''), 'nan')::NUMERIC,
                        NULLIF(NULLIF(TRIM(s.biaya_logistik), ''), 'nan')::NUMERIC,
                        NULLIF(NULLIF(TRIM(s.total_biaya_transaksi), ''), 'nan')::NUMERIC,
                        s.source_filename
                    FROM staging.stg_crewdible s
                    LEFT JOIN _tmp_crewdible_store_map       sm ON sm.raw_name = LOWER(TRIM(s.nama_toko))
                    LEFT JOIN _tmp_crewdible_marketplace_map mm ON mm.raw_name = LOWER(TRIM(s.nama_marketplace))
                    LEFT JOIN _tmp_crewdible_warehouse_map   wm ON wm.raw_name = LOWER(TRIM(s.gudang))
                    WHERE s.no_transaksi IS NOT NULL
                    AND NOT EXISTS (
                        SELECT 1 FROM public.fact_fulfillment_service_cost f
                        WHERE f.order_id = s.no_transaksi
                    )
                    ORDER BY s.no_transaksi
            """)
            result = conn.execute(sql)
            logger.info(f"✅ fact_fulfillment_service_cost: {result.rowcount} baris dimasukkan")

    except Exception as e:
        logger.error(f"❌ fact_fulfillment_service_cost gagal: {e}")


# ============================================================
# TRANSFORM CREWDIBLE 2: fact_fulfillment_order_product
# Grain: 1 baris per (order × SKU)
# ============================================================

def transform_fact_fulfillment_order_product(engine):
    logger.info("[TRANSFORM] fact_fulfillment_order_product ← stg_crewdible")
    try:
        with engine.begin() as conn:
            sql = text("""
                INSERT INTO public.fact_fulfillment_order_product (
                    order_id, sku_code, product_name,
                    quantity_sold, declared_unit_price, declared_total_product_value,
                    source_filename
                )
                    SELECT DISTINCT ON (s.no_transaksi, s.no_sku)
                        s.no_transaksi,
                        s.no_sku,
                        NULLIF(TRIM(s.nama_produk), ''),
                        NULLIF(NULLIF(TRIM(s.qty_produk), ''), 'nan')::NUMERIC,
                        NULLIF(NULLIF(TRIM(s.harga_produk), ''), 'nan')::NUMERIC,
                        NULLIF(NULLIF(TRIM(s.total_harga_produk), ''), 'nan')::NUMERIC,
                        s.source_filename
                    FROM staging.stg_crewdible s
                    WHERE s.no_transaksi IS NOT NULL
                    AND s.no_sku IS NOT NULL
                    AND NOT EXISTS (
                        SELECT 1 FROM public.fact_fulfillment_order_product f
                        WHERE f.order_id = s.no_transaksi AND f.sku_code = s.no_sku
                    )
                    ORDER BY s.no_transaksi, s.no_sku
            """)
            result = conn.execute(sql)
            logger.info(f"✅ fact_fulfillment_order_product: {result.rowcount} baris dimasukkan")

    except Exception as e:
        logger.error(f"❌ fact_fulfillment_order_product gagal: {e}")


# ============================================================
# TRANSFORM CREWDIBLE 3: fact_fulfillment_packaging_detail
# Grain: 1 baris per (order × material packaging)
# ============================================================

def transform_fact_fulfillment_packaging_detail(engine):
    logger.info("[TRANSFORM] fact_fulfillment_packaging_detail ← stg_crewdible")
    try:
        with engine.begin() as conn:
            sql = text("""
                INSERT INTO public.fact_fulfillment_packaging_detail (
                    order_id, material_name, unit_price, quantity, total_price,
                    source_filename
                )
                    SELECT DISTINCT ON (s.no_transaksi, s.material_packaging)
                        s.no_transaksi,
                        s.material_packaging,
                        NULLIF(NULLIF(TRIM(s.harga_material_packaging), ''), 'nan')::NUMERIC,
                        NULLIF(NULLIF(TRIM(s.qty_material_packaging), ''), 'nan')::NUMERIC,
                        NULLIF(NULLIF(TRIM(s.total_harga_material_packaging), ''), 'nan')::NUMERIC,
                        s.source_filename
                    FROM staging.stg_crewdible s
                    WHERE s.no_transaksi IS NOT NULL
                    AND s.material_packaging IS NOT NULL
                    AND NOT EXISTS (
                        SELECT 1 FROM public.fact_fulfillment_packaging_detail f
                        WHERE f.order_id = s.no_transaksi AND f.material_name = s.material_packaging
                    )
                    ORDER BY s.no_transaksi, s.material_packaging
            """)
            result = conn.execute(sql)
            logger.info(f"✅ fact_fulfillment_packaging_detail: {result.rowcount} baris dimasukkan")

    except Exception as e:
        logger.error(f"❌ fact_fulfillment_packaging_detail gagal: {e}")


# ============================================================
# RUNNER: Semua transform CREWDIBLE
# ============================================================

def run_transform_crewdible(engine):
    """
    Memindahkan data staging.stg_crewdible ke tiga fact tables public:
      1. fact_fulfillment_service_cost     (per order)
      2. fact_fulfillment_order_product    (per order × SKU)
      3. fact_fulfillment_packaging_detail (per order × material)

    Idempoten: gunakan NOT EXISTS sehingga aman dijalankan ulang.
    """
    logger.info("🔄 Memulai TRANSFORM_CREWDIBLE")
    transform_fact_fulfillment_service_cost(engine)
    transform_fact_fulfillment_order_product(engine)
    transform_fact_fulfillment_packaging_detail(engine)


# ============================================================
# LOADER: dim_b2b_partner
# Sumber: Salinan dari ___(Hasan) Update Stok Produksi - List Customer.csv
# ============================================================

# TPY values yang dimasukkan ke dim_b2b_partner
_B2B_VALID_TYPES = {'DISTRIBUTOR', 'KONSIYANSI', 'AGEN', 'AGEN-B', 'COSTUMER', 'SAMPLE'}

# TPY → nilai normal (untuk normalisasi alias)
_B2B_TYPE_NORMALIZE = {'AGEN-B': 'AGEN'}


def load_dim_b2b_partner(csv_path: str, engine):
    """
    Membaca List Customer CSV dan memasukkan mitra bisnis offline ke dim_b2b_partner.

    Idempoten: hapus baris lama berdasarkan source_filename sebelum insert ulang.

    TPY yang dimasukkan : DISTRIBUTOR, KONSIYANSI, AGEN, AGEN-B (→ AGEN), COSTUMER, SAMPLE
    TPY yang diabaikan  : GUDANG, MARKETPLACE, SUPLIER, PAMERAN, dsb.
    """
    logger.info(f"[LOAD] dim_b2b_partner ← {csv_path}")

    # ── 1. Baca CSV ──────────────────────────────────────────────────────────
    df = pd.read_csv(csv_path, dtype=str, keep_default_na=False)
    df.columns = [c.strip() for c in df.columns]

    df = df.rename(columns={
        'TPY':              'partner_type',
        'Online / Offline': 'channel',
        'Wilayah':          'wilayah',
        'NAMA':             'nama',
        'COMPANYNAME':      'company_name',
        'TITLE':            'title',
        'FIRSTNAME':        'firstname',
        'MIDDLENAME':       'middlename',
        'LASTNAME':         'lastname',
        'EMAIL':            'email',
        'MOBILE':           'mobile',
        'PHONE':            'phone',
        'ALAMAT DO':        'address_do',
    })

    # ── 2. Filter & normalise partner_type ──────────────────────────────────
    df['partner_type'] = df['partner_type'].str.strip()
    df = df[df['partner_type'].isin(_B2B_VALID_TYPES)].copy()
    df['partner_type'] = df['partner_type'].replace(_B2B_TYPE_NORMALIZE)

    # ── 3. Bangun contact_name dari komponen nama ────────────────────────────
    def _build_contact_name(row):
        parts = [row[c].strip() for c in ('title', 'firstname', 'middlename', 'lastname') if row[c].strip()]
        return ' '.join(parts) if parts else None

    df['contact_name'] = df.apply(_build_contact_name, axis=1)

    # ── 4. Helper: string kosong / 'nan' → None ──────────────────────────────
    def _clean(val):
        v = str(val).strip() if val is not None else ''
        return v if v and v.lower() != 'nan' else None

    # ── 5. Bangun list of dict untuk insert ──────────────────────────────────
    source_filename = os.path.basename(csv_path)
    records = []

    for _, row in df.iterrows():
        nama_val = _clean(row.get('nama', ''))
        if not nama_val:
            continue
        records.append({
            'partner_type':    _clean(row.get('partner_type')),
            'channel':         _clean(row.get('channel')),
            'wilayah':         _clean(row.get('wilayah')),
            'nama':            nama_val,
            'company_name':    _clean(row.get('company_name')),
            'contact_name':    row.get('contact_name'),
            'email':           _clean(row.get('email')),
            'mobile':          _clean(row.get('mobile')),
            'phone':           _clean(row.get('phone')),
            'address_do':      _clean(row.get('address_do')),
            'source_filename': source_filename,
        })

    logger.info(f"  {len(records)} baris valid ditemukan dari {len(df)} baris setelah filter.")

    # ── 6. Idempoten delete + insert dalam satu transaksi ────────────────────
    with engine.begin() as conn:
        deleted = conn.execute(
            text("DELETE FROM public.dim_b2b_partner WHERE source_filename = :fn"),
            {'fn': source_filename}
        ).rowcount
        if deleted:
            logger.info(f"  Menghapus {deleted} baris lama (source_filename='{source_filename}').")

        if not records:
            logger.warning("  Tidak ada baris untuk dimasukkan.")
            return

        conn.execute(
            text("""
                INSERT INTO public.dim_b2b_partner
                    (partner_type, channel, wilayah, nama, company_name,
                     contact_name, email, mobile, phone, address_do, source_filename)
                VALUES
                    (:partner_type, :channel, :wilayah, :nama, :company_name,
                     :contact_name, :email, :mobile, :phone, :address_do, :source_filename)
            """),
            records
        )

    logger.info(f"✅ dim_b2b_partner: {len(records)} baris berhasil dimasukkan.")
    logger.info("✅ TRANSFORM_CREWDIBLE selesai")