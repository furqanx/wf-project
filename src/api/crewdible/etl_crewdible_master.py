import sys
import os
import requests
import json
from prefect import task, flow, get_run_logger
from sqlalchemy import text
from dotenv import load_dotenv

load_dotenv()
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
from src.db_config import get_engine
from src.api.crewdible.crewdible_helper import CrewdibleAuthHelper

# Konfigurasi
CLIENT_ID = os.getenv("CREWDIBLE_CLIENT_ID")
CLIENT_SECRET = os.getenv("CREWDIBLE_CLIENT_SECRET")
EMAIL = os.getenv("CREWDIBLE_EMAIL")
PASSWORD = os.getenv("CREWDIBLE_PASSWORD")

BASE_URL = "https://oms-beta.api.crewdible.com/api/bites"

# Mapping Endpoint Crewdible ke Tabel Modular
# WAJIB: Jabarkan variabel dinamis seperti {{warehouse}} dan {{type}} dengan nilai aslinya.
CREWDIBLE_MASTER_MAP = {
    # --- PRODUCTS ---
    "/products/get/info"                : "raw_master_data",
    "/products/get/items"               : "raw_master_data",
    # --- WAREHOUSES ---
    # Contoh penjabaran {{warehouse}}. Ganti "JKT01" dengan ID/kode gudang yang sebenarnya.
    "/warehouses/info/contract/JKT01"   : "raw_master_data", 
    # --- PACKAGING ---
    "/packaging/items"                  : "raw_master_data",
    # --- LOGISTICS ---
    "/logistics/lists/all"              : "raw_master_data",
    # Contoh penjabaran {{type}} (misal: regular, sameday, instant)
    "/logistics/lists/outbound/regular" : "raw_master_data",
    "/logistics/lists/inbound/regular"  : "raw_master_data",
}

@task(retries=2, retry_delay_seconds=10)
def extract_crewdible_bulk(endpoint, helper):
    logger = get_run_logger()
    all_items = []
    page = 1
    limit = 50 
    
    headers = helper.get_auth_headers()
    url = f"{BASE_URL}{endpoint}"

    while True:
        logger.info(f"Menarik {endpoint} - Halaman {page}...")
        payload = {
            "page": page,
            "limit": limit
        }

        # Metode default API Crewdible biasanya menggunakan POST untuk penarikan data
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()

        result = response.json()
        data = result.get("data", {})
        items = data.get("items", [])
        total_page = data.get("total_page", 1)

        all_items.extend(items)

        if page >= total_page:
            break
        page += 1

    return all_items

@task
def load_to_crewdible_table(table_name, endpoint, raw_data):
    logger = get_run_logger()
    if not raw_data:
        logger.info(f"Tidak ada data untuk {endpoint}")
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

@flow(name="Crewdible_Master_Bulk_ETL")
def crewdible_master_etl():
    logger = get_run_logger()
    helper = CrewdibleAuthHelper(CLIENT_ID, CLIENT_SECRET, EMAIL, PASSWORD)
    
    for endpoint, target_table in CREWDIBLE_MASTER_MAP.items():
        try:
            data = extract_crewdible_bulk(endpoint, helper)
            load_to_crewdible_table(target_table, endpoint, data)
        except Exception as e:
            logger.error(f"Gagal memproses {endpoint}: {e}")

if __name__ == "__main__":
    crewdible_master_etl()