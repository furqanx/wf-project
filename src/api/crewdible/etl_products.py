import sys
import os
import requests
import json
import hashlib
import base64
from prefect import task, flow, get_run_logger
from sqlalchemy import text

# Setup Path agar bisa import src.db_config
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from src.db_config import get_engine

# Konfigurasi Global berdasarkan Dokumen
BASE_URL = "https://oms-beta.api.crewdible.com/api/bites"

@task(retries=3, retry_delay_seconds=10)
def get_auth_tokens():
    logger = get_run_logger()

    # 1. Request OAuth Token (Tahap 1)
    client_id = os.getenv("CREWDIBLE_CLIENT_ID")
    client_secret = os.getenv("CREWDIBLE_CLIENT_SECRET")

    # Format Basic Auth: base64(ClientId:ClientSecret)
    auth_str = f"{client_id}:{client_secret}"
    encoded_auth = base64.b64encode(auth_str.encode()).decode()

    headers_oauth = {
        "Authorization": f"Basic {encoded_auth}",
        "Content-Type": "application/x-www-form-urlencoded"
    }
    payload_oauth = {"grant_type": "client_credentials"}

    res_oauth = requests.post(f"{BASE_URL}/oauth/token", headers=headers_oauth, data=payload_oauth)
    res_oauth.raise_for_status()
    token_api = res_oauth.json().get("access_token") # Sesuai output doc: "access token"

    # 2. User Login (Tahap 2)[cite: 1]
    email = os.getenv("CREWDIBLE_EMAIL")
    password_plain = os.getenv("CREWDIBLE_PASSWORD")
    # Password harus MD5[cite: 1]
    password_md5 = hashlib.md5(password_plain.encode()).hexdigest()

    headers_login = {
        "Authorization": f"Bearer {token_api}",
        "Content-Type": "application/json"
    }
    payload_login = {
        "email": email,
        "password": password_md5
    }

    res_login = requests.post(f"{BASE_URL}/users/login", headers=headers_login, json=payload_login)
    res_login.raise_for_status()
    token_login = res_login.json().get("data", {}).get("token") # Sesuai output doc: "token"[cite: 1]

    logger.info("Berhasil mendapatkan Token API dan Token Login.")
    return token_api, token_login

@task(retries=2)
def extract_products(token_api, token_login):
    logger = get_run_logger()
    all_items = []
    page = 1
    limit = 50 # Anda bisa sesuaikan limitnya[cite: 1]

    headers = {
        "Authorization": f"Bearer {token_api}",
        "X-CREW-TOKEN": token_login,
        "Content-Type": "application/json"
    }

    while True:
        logger.info(f"Menarik data Produk halaman {page}...")
        payload = {
            "page": page,
            "limit": limit
        }

        # Menggunakan endpoint /products/get/items[cite: 1]
        response = requests.post(f"{BASE_URL}/products/get/items", headers=headers, json=payload)
        response.raise_for_status()

        result = response.json()
        data = result.get("data", {})
        items = data.get("items", [])
        total_page = data.get("total_page", 1) # Sesuai output doc[cite: 1]

        all_items.extend(items)

        if page >= total_page:
            break
        page += 1

    logger.info(f"Total berhasil menarik {len(all_items)} produk.")
    return all_items

@task
def load_to_db(products):
    logger = get_run_logger()
    if not products:
        return

    engine = get_engine()
    query = text("INSERT INTO crewdible_raw.raw_products (endpoint_source, raw_data) VALUES (:ep, :data)")

    with engine.begin() as conn:
        conn.execute(query, {"ep": "/products/get/items", "data": json.dumps(products)})
    logger.info("Data produk berhasil disimpan ke tabel raw.")

@flow(name="Crewdible_Full_ETL_Products")
def crewdible_full_etl():
    t_api, t_login = get_auth_tokens()
    data_produk = extract_products(t_api, t_login)
    load_to_db(data_produk)

if __name__ == "__main__":
    crewdible_full_etl()
