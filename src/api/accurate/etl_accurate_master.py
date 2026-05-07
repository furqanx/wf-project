import sys
import os
import requests
import json
from prefect import task, flow, get_run_logger
from sqlalchemy import text

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from src.db_config import get_engine
from src.accurate.accurate_helper import AccurateAuthHelper

API_TOKEN        = os.getenv("ACCURATE_API_TOKEN")
SIGNATURE_SECRET = os.getenv("ACCURATE_SIGNATURE_SECRET")

MASTER_ENDPOINT_MAP = {
    # Master Data (Data Referensi & Entitas Statis)
    # Master Data (Seringkali ditarik Full Load, tapi kita pasang filter modifikasi jika dukung)
    "/api/branch"               : "raw_master_data",
    "/api/currency"             : "raw_master_data",
    "/api/customer"             : "raw_master_data",
    "/api/customer-category"    : "raw_master_data",
    "/api/department"           : "raw_master_data",
    "/api/employee"             : "raw_master_data",
    "/api/fixed-asset"          : "raw_master_data",
    "/api/fob"                  : "raw_master_data",
    "/api/freeonboard"          : "raw_master_data",
    "/api/glaccount"            : "raw_master_data",
    "/api/item"                 : "raw_master_data",
    "/api/item-category"        : "raw_master_data",
    "/api/payment-term"         : "raw_master_data",
    "/api/price-category"       : "raw_master_data",
    "/api/project"              : "raw_master_data",
    "/api/shipment"             : "raw_master_data",
    "/api/tax"                  : "raw_master_data",
    "/api/unit"                 : "raw_master_data",
    "/api/vendor"               : "raw_master_data",
    "/api/vendor-category"      : "raw_master_data",
    "/api/vendor-price"         : "raw_master_data",
    "/api/warehouse"            : "raw_master_data",
}

@task(retries=2, retry_delay_seconds=10)
def extract_accurate_bulk(dynamic_host, endpoint, helper):
    logger = get_run_logger()
    url = f"{dynamic_host}/accurate{endpoint}.do"
    
    all_data = []
    page = 1
    
    while True:
        logger.info(f"Menarik {endpoint} (Full Load) - Halaman {page}...")
        
        headers = helper.get_auth_headers()
        params = {"sp.page": page} # Tanpa filter tanggal
        
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()
        
        result = response.json()
        
        if not result.get("s"):
            logger.error(f"API Error pada {endpoint}: {result}")
            break
            
        data = result.get("d", [])
        all_data.extend(data)
        
        sp = result.get("sp", {})
        if page >= sp.get("pageCount", 1):
            break
            
        page += 1
        
    return all_data

@task
def load_to_accurate_table(table_name, endpoint, raw_data):
    logger = get_run_logger()
    if not raw_data:
        logger.info(f"Tidak ada data untuk {endpoint}")
        return

    engine = get_engine()
    query = text(f"""
        INSERT INTO accurate_raw.{table_name} (endpoint_source, raw_data)
        VALUES (:ep, :data)
    """)
    
    with engine.begin() as conn:
        conn.execute(query, {
            "ep": endpoint,
            "data": json.dumps(raw_data)
        })
    logger.info(f"[{endpoint}] berhasil dimuat ke {table_name}. Total: {len(raw_data)} baris.")

@flow(name="Accurate_Master_Bulk_ETL")
def accurate_master_etl():
    logger = get_run_logger()
    helper = AccurateAuthHelper(API_TOKEN, SIGNATURE_SECRET)
    
    try:
        dynamic_host = helper.get_dynamic_host()
    except Exception as e:
        logger.error(f"Gagal inisialisasi Host Accurate: {e}")
        return

    for endpoint, target_table in MASTER_ENDPOINT_MAP.items():
        data = extract_accurate_bulk(dynamic_host, endpoint, helper)
        load_to_accurate_table(target_table, endpoint, data)

if __name__ == "__main__":
    accurate_master_etl()