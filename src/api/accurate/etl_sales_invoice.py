import sys
import os
import requests
import json
from prefect import task, flow, get_run_logger
from sqlalchemy import text

# Setup Path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from src.db_config import get_engine
from src.accurate.accurate_helper import AccurateAuthHelper

API_TOKEN = os.getenv("ACCURATE_API_TOKEN")
SIGNATURE_SECRET = os.getenv("ACCURATE_SIGNATURE_SECRET")

@task(retries=2, retry_delay_seconds=10)
def extract_sales_invoices():
    logger = get_run_logger()
    helper = AccurateAuthHelper(API_TOKEN, SIGNATURE_SECRET)

    # 1. Dapatkan URL Host Dinamis
    try:
        dynamic_host = helper.get_dynamic_host()
        logger.info(f"Berhasil mendapatkan Dynamic Host: {dynamic_host}")
    except Exception as e:
        logger.error(str(e))
        return []

    # Target Endpoint
    url = f"{dynamic_host}/accurate/api/sales-invoice/list.do"

    all_data = []
    page = 1

    while True:
        logger.info(f"Menarik faktur penjualan halaman {page}...")

        # Selalu generate header baru per halaman agar X-Api-Timestamp update terus
        headers = helper.get_auth_headers()

        # Tambahkan header bahasa (opsional, id / US / CN)
        headers["X-Language-Profile"] = "id"

        # Parameter request (sp.page untuk paginasi Accurate)
        params = {
            "fields": "id,number,transDate,totalAmount", # Bisa disesuaikan
            "sp.page": page
        }

        # Method GET. Default requests di Python sudah include "Follow Redirects"
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()

        result = response.json()

        if not result.get("s"): # 's' adalah flag success
            logger.error(f"API Error: {result}")
            break

        data = result.get("d", [])
        all_data.extend(data)

        # Cek status Paginasi Accurate
        sp = result.get("sp", {})
        page_count = sp.get("pageCount", 1)

        if page >= page_count:
            break

        page += 1

    logger.info(f"Total berhasil menarik {len(all_data)} faktur penjualan.")
    return all_data

@task
def load_to_postgres(raw_data):
    logger = get_run_logger()
    if not raw_data:
        logger.info("Tidak ada data baru untuk disimpan.")
        return

    engine = get_engine()
    query = text("""
        INSERT INTO accurate_raw.raw_sales_invoices (endpoint_source, raw_data)
        VALUES (:ep, :data)
    """)

    with engine.begin() as conn:
        conn.execute(query, {
            "ep": "/api/sales-invoice/list.do",
            "data": json.dumps(raw_data)
        })
    logger.info("Data Accurate berhasil disimpan ke database!")

@flow(name="Accurate_ETL_Sales_Invoice")
def accurate_etl_flow():
    data_faktur = extract_sales_invoices()
    load_to_postgres(data_faktur)

if __name__ == "__main__":
    accurate_etl_flow()
