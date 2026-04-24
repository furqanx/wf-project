"""
src/file_inspector.py

Bertugas menghitung jumlah baris yang akan dimuat ke tabel staging primer
dari sebuah file spreadsheet, tanpa benar-benar memuatnya ke database.

Logika pembacaan file di sini mereplikasi persis logika di extract_loader.py
agar angka yang dihasilkan selalu konsisten dengan yang akan masuk ke DB.
"""

import openpyxl
import pandas as pd
from sqlalchemy import text
from src.db_config import logger

# ============================================================
# MAPPING: (fase, marketplace) → tabel staging primer
# ============================================================
PRIMARY_TABLE = {
    ('ORDER',  'shopee'):           'stg_shopee_orders',
    ('ORDER',  'tiktok_tokopedia'): 'stg_tiktok_tokopedia_orders',
    ('ORDER',  'lazada'):           'stg_lazada_orders',
    ('INCOME', 'shopee'):           'stg_shopee_income_main',
    ('INCOME', 'tiktok_tokopedia'): 'stg_tiktok_tokopedia_income',
    ('INCOME', 'lazada'):           'stg_lazada_income',
    ('REPORT', 'shopee'):           'stg_shopee_report',
    ('REPORT', 'tiktok_tokopedia'): 'stg_tiktok_tokopedia_report',
    ('REPORT', 'lazada'):           'stg_lazada_report',
}


# ============================================================
# FUNGSI PENGHITUNG BARIS PER (FASE, MARKETPLACE)
# ============================================================

def _count_shopee_order(file_path):
    df = pd.read_excel(file_path, dtype=str, engine='openpyxl')
    return len(df)


def _count_tiktok_order(file_path):
    wb = openpyxl.load_workbook(file_path, data_only=True, read_only=True)
    ws = wb.active
    rows = list(ws.values)
    wb.close()
    if len(rows) < 3:
        return 0
    # Baris index 0 = header, index 1 = deskripsi kolom (dilewati), data mulai index 2
    data_rows = [r for r in rows[2:] if any(v is not None for v in r)]
    return len(data_rows)


def _count_lazada_order(file_path):
    df = pd.read_excel(file_path, dtype=str, engine='openpyxl')
    return len(df)


def _count_shopee_income(file_path):
    """
    Shopee INCOME bisa punya banyak sheet Income (Income, Income - 1, Income - 2, dst.).
    Semua sheet yang mengandung kata 'income' dijumlahkan — sama persis dengan
    logika process_income_file() di extract_loader.py.
    """
    wb = openpyxl.load_workbook(file_path, data_only=True, read_only=True)
    total = 0
    for sheet in wb.sheetnames:
        if 'income' not in sheet.lower():
            continue
        ws = wb[sheet]
        rows = list(ws.values)
        if len(rows) < 7:
            continue
        # Header di row index 5, data mulai index 6
        data_rows = [r for r in rows[6:] if any(v is not None for v in r)]
        total += len(data_rows)
    wb.close()
    return total


def _count_tiktok_income(file_path):
    xl = pd.ExcelFile(file_path, engine='openpyxl')
    target_sheet = 'Order details' if 'Order details' in xl.sheet_names else 0
    df = pd.read_excel(file_path, sheet_name=target_sheet, dtype=str, engine='openpyxl')
    return len(df)


def _count_lazada_income(file_path):
    df = pd.read_excel(file_path, dtype=str, engine='openpyxl')
    return len(df)


def _count_shopee_report(file_path):
    wb = openpyxl.load_workbook(file_path, data_only=True, read_only=True)
    if 'Transaction Report' not in wb.sheetnames:
        wb.close()
        return 0
    ws = wb['Transaction Report']
    rows = list(ws.values)
    wb.close()
    if len(rows) < 19:
        return 0
    # Header di row index 17, data mulai index 18
    data_rows = [r for r in rows[18:] if any(v is not None for v in r)]
    return len(data_rows)


def _count_tiktok_report(file_path):
    wb = openpyxl.load_workbook(file_path, data_only=True, read_only=True)
    ws = wb.active
    rows = list(ws.values)
    wb.close()
    if len(rows) < 2:
        return 0
    # Header di row index 0, data mulai index 1
    data_rows = [r for r in rows[1:] if any(v is not None for v in r)]
    return len(data_rows)


def _count_lazada_report(file_path):
    wb = openpyxl.load_workbook(file_path, data_only=True, read_only=True)
    if 'Balance Transactions' not in wb.sheetnames:
        wb.close()
        return 0
    ws = wb['Balance Transactions']
    rows = list(ws.values)
    wb.close()
    if len(rows) < 2:
        return 0
    data_rows = [r for r in rows[1:] if any(v is not None for v in r)]
    return len(data_rows)


# ============================================================
# DISPATCHER
# ============================================================

_COUNTER_MAP = {
    ('ORDER',  'shopee'):           _count_shopee_order,
    ('ORDER',  'tiktok_tokopedia'): _count_tiktok_order,
    ('ORDER',  'lazada'):           _count_lazada_order,
    ('INCOME', 'shopee'):           _count_shopee_income,
    ('INCOME', 'tiktok_tokopedia'): _count_tiktok_income,
    ('INCOME', 'lazada'):           _count_lazada_income,
    ('REPORT', 'shopee'):           _count_shopee_report,
    ('REPORT', 'tiktok_tokopedia'): _count_tiktok_report,
    ('REPORT', 'lazada'):           _count_lazada_report,
}


def count_rows_in_file(file_path, fase, marketplace):
    """
    Menghitung jumlah baris data yang akan masuk ke tabel staging primer
    dari file spreadsheet yang diberikan.
    """
    key = (fase.upper(), marketplace.lower())
    counter_fn = _COUNTER_MAP.get(key)
    if counter_fn is None:
        logger.warning(f"Tidak ada counter untuk kombinasi fase={fase}, marketplace={marketplace}")
        return 0
    try:
        return counter_fn(file_path)
    except Exception as e:
        logger.error(f"Gagal menghitung baris dari file {file_path}: {e}")
        return 0


# ============================================================
# PENGECEKAN DUA LAPIS
# ============================================================

def check_file_status(filename, file_path, fase, marketplace, engine):
    """
    Melakukan pengecekan dua lapis untuk satu file:

    Lapis 1 — cek source_filename di tabel staging primer.
              Jika tidak ditemukan → status 'new', selesai.

    Lapis 2 — bandingkan jumlah baris di DB vs di file.
              Menghasilkan salah satu dari empat status:
              - 'new'          : belum pernah dimuat
              - 'fully_loaded' : seluruh baris sudah ada di DB
              - 'partial'      : sebagian baris sudah ada di DB
              - 'anomaly'      : baris di DB lebih banyak dari file

    Returns dict:
        {
            'status'       : str,
            'rows_in_db'   : int,
            'rows_in_file' : int,
            'table'        : str,
        }
    """
    key   = (fase.upper(), marketplace.lower())
    table = PRIMARY_TABLE.get(key)

    if table is None:
        return {'status': 'unknown', 'rows_in_db': 0, 'rows_in_file': 0, 'table': ''}

    # --- Lapis 1: cek keberadaan source_filename di DB ---
    try:
        with engine.connect() as conn:
            rows_in_db = conn.execute(
                text(f"SELECT COUNT(*) FROM {table} WHERE source_filename = :fn"),
                {"fn": filename}
            ).scalar()
    except Exception as e:
        logger.error(f"Gagal query DB saat check_file_status: {e}")
        return {'status': 'unknown', 'rows_in_db': 0, 'rows_in_file': 0, 'table': table}

    if rows_in_db == 0:
        return {'status': 'new', 'rows_in_db': 0, 'rows_in_file': 0, 'table': table}

    # --- Lapis 2: bandingkan jumlah baris ---
    rows_in_file = count_rows_in_file(file_path, fase, marketplace)

    if rows_in_db == rows_in_file:
        status = 'fully_loaded'
    elif rows_in_db < rows_in_file:
        status = 'partial'
    else:
        status = 'anomaly'

    return {
        'status'       : status,
        'rows_in_db'   : rows_in_db,
        'rows_in_file' : rows_in_file,
        'table'        : table,
    }
