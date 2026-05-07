import sys
import os
import requests
import json
from prefect import task, flow, get_run_logger
from sqlalchemy import text

# Setup Path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from src.db_config import get_engine
from src.bigseller.auth_helper import BigSellerAuthHelper

BASE_URL = "https://api.bigseller.com" # Sesuaikan jika menggunakan URL Sandbox/Regional
APP_ID = os.getenv("BIGSELLER_APP_ID")
APP_KEY = os.getenv("BIGSELLER_APP_KEY")

@task(retries=1)
def get_valid_token(engine):
    """Mengambil token dari database. Jika butuh refresh, kembalikan refresh_token juga."""
    logger = get_run_logger()
    query = text("SELECT access_token, refresh_token FROM bigseller_raw.api_tokens WHERE app_id = :app_id")

    with engine.connect() as conn:
        result = conn.execute(query, {"app_id": APP_ID}).fetchone()

    if not result:
        raise ValueError("Token belum diinisialisasi di database. Lakukan manual insert tahap 3 OAuth pertama kali.")

    return result[0], result[1]

@task
def update_token_in_db(engine, new_access, new_refresh):
    """Menyimpan token yang baru di-refresh ke database."""
    query = text("""
        UPDATE bigseller_raw.api_tokens 
        SET access_token = :acc, refresh_token = :ref, last_updated = CURRENT_TIMESTAMP 
        WHERE app_id = :app_id
    """)
    with engine.begin() as conn:
        conn.execute(query, {"acc": new_access, "ref": new_refresh, "app_id": APP_ID})

@task(retries=2, retry_delay_seconds=5)
def extract_orders(access_token, refresh_token, engine):
    logger = get_run_logger()
    auth_helper = BigSellerAuthHelper(APP_ID, APP_KEY, BASE_URL)

    # Endpoint sesuai kaidah /api/{module}/{version}/{interface} dokumen BigSeller
    api_path = "/api/order/v1/getOrderIds" 
    url = f"{BASE_URL}{api_path}"

    # Parameter payload sesuai dokumen (date_type 0 = Order Placement Time)
    payload = {
        "date_type": 0,
        "page": 1,
        "limit": 50
    }

    headers = auth_helper.build_headers(api_path, access_token, payload)

    response = requests.post(url, headers=headers, json=payload)
    result = response.json()

    # Menangani kasus Token Expired (Error code 40101005 dari BigSeller)
    if result.get("error_code") == "40101005":
        logger.warning("Access Token kedaluwarsa. Mencoba refresh token...")
        new_tokens = auth_helper.refresh_access_token(refresh_token)

        new_access = new_tokens.get("access_token")
        new_refresh = new_tokens.get("refresh_token")

        # Update database dengan token baru
        update_token_in_db.fn(engine, new_access, new_refresh)

        # Build ulang header dan request ulang
        logger.info("Mencoba ekstraksi kembali dengan token baru.")
        headers = auth_helper.build_headers(api_path, new_access, payload)
        response = requests.post(url, headers=headers, json=payload)
        result = response.json()

    response.raise_for_status()

    if not result.get("success"):
        logger.error(f"API Error: {result.get('msg')}")
        return []

    return result.get("data", [])

@task
def load_to_postgres(engine, raw_data):
    logger = get_run_logger()
    if not raw_data:
        logger.info("Tidak ada data pesanan baru untuk disimpan.")
        return

    query = text("""
        INSERT INTO bigseller_raw.raw_orders (endpoint_source, raw_data)
        VALUES (:ep, :data)
    """)
    
    with engine.begin() as conn:
        conn.execute(query, {
            "ep": "/api/order/v1/getOrderIds",
            "data": json.dumps(raw_data)
        })
    logger.info("Data pesanan BigSeller berhasil disimpan!")

@flow(name="BigSeller_ETL_Orders")
def bigseller_etl_flow():
    engine = get_engine()
    
    # 1. Ambil token terakhir dari DB
    access_token, refresh_token = get_valid_token(engine)
    
    # 2. Ekstrak pesanan (otomatis refresh jika token mati)
    raw_payload = extract_orders(access_token, refresh_token, engine)
    
    # 3. Load ke DB
    load_to_postgres(engine, raw_payload)

if __name__ == "__main__":
    bigseller_etl_flow()
