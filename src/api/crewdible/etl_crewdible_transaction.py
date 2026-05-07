import sys
import os
import requests
import json
from datetime import datetime, timedelta
from prefect import task, flow, get_run_logger
from sqlalchemy import text

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from src.db_config import get_engine
from src.crewdible.crewdible_helper import CrewdibleAuthHelper

CLIENT_ID = os.getenv("CREWDIBLE_CLIENT_ID")
CLIENT_SECRET = os.getenv("CREWDIBLE_CLIENT_SECRET")
EMAIL = os.getenv("CREWDIBLE_EMAIL")
PASSWORD = os.getenv("CREWDIBLE_PASSWORD")

BASE_URL = "https://oms-beta.api.crewdible.com/api/bites"

# Mapping Endpoint Transaksional
# WAJIB: Jabarkan {{status}} atau {{type}} dengan nilai aktual dari dokumentasi Crewdible.
CREWDIBLE_TRANSACTION_MAP = {
    # --- ORDER ALL ---
    "/order/lists/regular/pending"      : "raw_order_all",     # Contoh penjabaran {{category}} & {{status}}
    "/order/lists/regular/processed"    : "raw_order_all",     # Contoh penjabaran {{category}} & {{status}}
    "/order/lists/move/pending"         : "raw_order_all",     # Contoh penjabaran {{status}}
    
    "/order/search/all"                 : "raw_order_all",
    
    # --- ORDER DETAIL ---
    "/order/detail/inv"                 : "raw_order_detail",
    "/order/detail/dropship"            : "raw_order_detail",
    "/order/detail/cod"                 : "raw_order_detail",
    "/order/detail/exit"                : "raw_order_detail",
    "/order/detail/move"                : "raw_order_detail",

    "/order/detail/regular/address"     : "raw_order_detail",  # Contoh penjabaran {{type}}

    # --- STOCK INBOUND ---
    "/stock/inbound/lists/draft"        : "raw_stock_inbound", # Contoh penjabaran {{status}}
    "/stock/inbound/lists/done"         : "raw_stock_inbound", # Contoh penjabaran {{status}}
    
    "/stock/inbound/detail"             : "raw_stock_inbound",
    "/stock/inbound/shipping-label"     : "raw_stock_inbound",

    # --- STOCK WAREHOUSE (Snapshot Saldo) ---
    "/stock/lists/product"              : "raw_stock_warehouse",
    "/stock/lists/warehouse"            : "raw_stock_warehouse",
    "/stock/lists/export"               : "raw_stock_warehouse",

    # --- STOCK MUTATIONS ---
    "/stock/mutations/summary"          : "raw_stock_mutations",
    "/stock/mutations/history"          : "raw_stock_mutations",

    # --- LOADINGS ---
    "/loadings/get/item/pending"        : "raw_loadings",     # Contoh penjabaran {{status}}
    
    "/loadings/get/info"                : "raw_loadings",

    # --- QC & SO ---
    "/qc/request/items"                 : "raw_qc",
    "/qc/request/detail"                : "raw_qc",
    "/so/request/items"                 : "raw_so",
    "/so/request/detail"                : "raw_so"
}

@task(retries=2, retry_delay_seconds=10)
def extract_crewdible_incremental(endpoint, helper, start_date_str, end_date_str):
    logger = get_run_logger()
    all_items = []
    page = 1
    limit = 50 
    
    headers = helper.get_auth_headers()
    url = f"{BASE_URL}{endpoint}"

    while True:
        logger.info(f"Menarik {endpoint} (Periode: {start_date_str} - {end_date_str}) - Halaman {page}...")
        
        # Inject parameter tanggal ke dalam payload POST.
        # Catatan: Pastikan nama key ('start_date', 'end_date') sesuai dengan 
        # dokumentasi API Crewdible untuk masing-masing endpoint.
        payload = {
            "page": page,
            "limit": limit,
            "start_date": start_date_str,
            "end_date": end_date_str
        }

        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()

        result = response.json()
        data = result.get("data", {})
        
        # Penanganan dinamis karena beberapa endpoint mungkin mengembalikan list langsung di 'data'
        items = data.get("items", []) if isinstance(data, dict) else data
        total_page = data.get("total_page", 1) if isinstance(data, dict) else 1

        if isinstance(items, list):
            all_items.extend(items)
        else:
            all_items.append(items) # Jika return berupa single object

        if page >= total_page:
            break
        page += 1

    return all_items

@task
def load_to_crewdible_table(table_name, endpoint, raw_data):
    logger = get_run_logger()
    if not raw_data:
        logger.info(f"Tidak ada data baru untuk {endpoint}")
        return

    engine = get_engine()
    query = text(f"""
        INSERT INTO crewdible_raw.{table_name} (endpoint_source, raw_data)
        VALUES (:ep, :data)
    """)
    
    with engine.begin() as conn:
        conn.execute(query, {
            "ep": endpoint,
            "data": json.dumps(raw_data)
        })
    logger.info(f"[{endpoint}] berhasil dimuat ke {table_name}. Total: {len(raw_data)} baris.")

@flow(name="Crewdible_Transaction_Incremental_ETL")
def crewdible_transaction_etl():
    logger = get_run_logger()
    helper = CrewdibleAuthHelper(CLIENT_ID, CLIENT_SECRET, EMAIL, PASSWORD)
    
    # Rolling Window (H-3 sampai Hari Ini)
    # Format YYYY-MM-DD adalah standar umum API, sesuaikan jika Crewdible butuh format lain
    end_date = datetime.now()
    start_date = end_date - timedelta(days=3)
    
    start_str = start_date.strftime("%Y-%m-%d")
    end_str = end_date.strftime("%Y-%m-%d")

    for endpoint, target_table in CREWDIBLE_TRANSACTION_MAP.items():
        try:
            data = extract_crewdible_incremental(endpoint, helper, start_str, end_str)
            load_to_crewdible_table(target_table, endpoint, data)
        except Exception as e:
            logger.error(f"Gagal memproses {endpoint}: {e}")

if __name__ == "__main__":
    crewdible_transaction_etl()