import sys
import os
import requests
import json
from datetime import datetime, timedelta
from prefect import task, flow, get_run_logger
from sqlalchemy import text

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from src.db_config import get_engine
from src.accurate.accurate_helper import AccurateAuthHelper

API_TOKEN        = os.getenv("ACCURATE_API_TOKEN")
SIGNATURE_SECRET = os.getenv("ACCURATE_SIGNATURE_SECRET")

TRANSACTION_ENDPOINT_MAP = {
    # Sales (Siklus Penjualan & Piutang)
    "/api/customer-claim"            : "raw_sales",
    "/api/exchange-invoice"          : "raw_sales",
    "/api/sales-checkin"             : "raw_sales",
    "/api/sales-invoice"             : "raw_sales",
    "/api/sales-order"               : "raw_sales",
    "/api/sales-quotation"           : "raw_sales",
    "/api/sales-receipt"             : "raw_sales",
    "/api/sales-return"              : "raw_sales",
    "/api/salesman-commission"       : "raw_sales",
    "/api/sellingprice-adjustment"   : "raw_sales",
    
    # Purchases (Siklus Pembelian & Utang)
    "/api/purchase-invoice"          : "raw_purchases",
    "/api/purchase-order"            : "raw_purchases",
    "/api/purchase-payment"          : "raw_purchases",
    "/api/purchase-requisition"      : "raw_purchases",
    "/api/purchase-return"           : "raw_purchases",
    "/api/vendor-claim"              : "raw_purchases",
    
    # Inventory (Siklus Stok & Gudang)
    "/api/delivery-order"            : "raw_inventory",
    "/api/item-adjustment"           : "raw_inventory",
    "/api/item-transfer"             : "raw_inventory",
    "/api/receive-item"              : "raw_inventory",
    "/api/stock-opname-order"        : "raw_inventory",
    "/api/stock-opname-result"       : "raw_inventory",
    
    # Finance (Siklus Keuangan & Kas)
    "/api/bank-transfer"             : "raw_finance",
    "/api/expense"                   : "raw_finance",
    "/api/journal-voucher"           : "raw_finance",
    "/api/other-deposit"             : "raw_finance",
    "/api/other-payment"             : "raw_finance",

    # Manufacturing (Siklus Pabrikasi)
    "/api/bill-of-material"          : "raw_manufacturing",
    "/api/bom-process-category"      : "raw_manufacturing",
    "/api/finished-good-slip"        : "raw_manufacturing",
    "/api/job-order"                 : "raw_manufacturing",
    "/api/manufacture-order"         : "raw_manufacturing",
    "/api/material-adjustment"       : "raw_manufacturing",
    "/api/material-slip"             : "raw_manufacturing",
    "/api/process-stages"            : "raw_manufacturing",
    "/api/standard-product-cost"     : "raw_manufacturing",
    "/api/wo-pic"                    : "raw_manufacturing",
    "/api/work-order"                : "raw_manufacturing",

    # POS (Siklus Point of Sale)
    "/api/pos/customer"              : "raw_pos",
    "/api/pos/item"                  : "raw_pos",
    "/api/pos/transaction"           : "raw_pos",

    # System Config (Sistem & Konfigurasi Ekstra)
    "/api/auto-number"               : "raw_system_config",
    "/api/data-classification"       : "raw_system_config",
    "/api/report"                    : "raw_system_config",
    "/api/roll-over"                 : "raw_system_config",
}

@task(retries=2, retry_delay_seconds=10)
def extract_accurate_incremental(dynamic_host, endpoint, helper, start_date_str, end_date_str):
    logger = get_run_logger()
    url = f"{dynamic_host}/accurate{endpoint}.do"
    
    all_data = []
    page = 1
    
    while True:
        logger.info(f"Menarik {endpoint} (Periode: {start_date_str} - {end_date_str}) - Hal {page}...")
        
        headers = helper.get_auth_headers()
        params = {
            "sp.page": page,
            "filter.modifiedAt.gte": start_date_str,
            "filter.modifiedAt.lte": end_date_str
        }
        
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
        logger.info(f"Tidak ada data baru untuk {endpoint}")
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

@flow(name="Accurate_Transaction_Incremental_ETL")
def accurate_transaction_etl():
    logger = get_run_logger()
    helper = AccurateAuthHelper(API_TOKEN, SIGNATURE_SECRET)
    
    try:
        dynamic_host = helper.get_dynamic_host()
    except Exception as e:
        logger.error(f"Gagal inisialisasi Host Accurate: {e}")
        return

    end_date = datetime.now()
    start_date = end_date - timedelta(days=3)
    
    start_str = start_date.strftime("%d/%m/%Y")
    end_str = end_date.strftime("%d/%m/%Y")

    for endpoint, target_table in TRANSACTION_ENDPOINT_MAP.items():
        data = extract_accurate_incremental(dynamic_host, endpoint, helper, start_str, end_str)
        load_to_accurate_table(target_table, endpoint, data)

if __name__ == "__main__":
    accurate_transaction_etl()