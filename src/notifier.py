"""
src/notifier.py

Modul notifikasi untuk schema drift.
Saat enforce_schema() mendeteksi kolom/sheet baru yang tidak dikenal, modul ini:
  1. Mengirim pesan Telegram ke operator
  2. Mencatat kejadian ke tabel staging.schema_drift_log di database
  3. Mengunggah file sumber ke Google Drive untuk pemeriksaan manual

Setup Telegram:
  1. Buat bot via @BotFather → dapatkan TELEGRAM_BOT_TOKEN
  2. Kirim pesan apa saja ke bot, buka:
     https://api.telegram.org/bot<TOKEN>/getUpdates
     Salin nilai "id" dari bagian "chat" → isi ke TELEGRAM_CHAT_ID

Setup Google Drive:
  1. Buka Google Cloud Console → buat Service Account
  2. Download kunci JSON service account → isi path-nya di GDRIVE_SERVICE_ACCOUNT_JSON
  3. Buat folder di Google Drive → salin ID folder dari URL → isi ke GDRIVE_FOLDER_ID
  4. Bagikan folder tersebut ke email service account (dengan akses Editor)
"""

import threading
import requests
from datetime import datetime
from pathlib import Path

from src.db_config import logger


# ============================================================
# KONFIGURASI  ← ISI DI SINI
# ============================================================

# Telegram
TELEGRAM_BOT_TOKEN = ""   # "7412345678:AAFxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
TELEGRAM_CHAT_ID   = ""   # "123456789"

# Google Drive
GDRIVE_SERVICE_ACCOUNT_JSON = ""   # "/path/to/service-account.json"
GDRIVE_FOLDER_ID            = ""   # ID folder Drive tujuan (dari URL)


# ============================================================
# STATE INTERNAL
# ============================================================

# Cegah upload file yang sama lebih dari sekali per sesi ETL
_uploaded_this_session: set = set()

# Flag agar DDL tabel hanya dijalankan sekali
_log_table_ready: bool = False


# ============================================================
# DB LOG
# ============================================================

def _ensure_log_table(engine) -> None:
    global _log_table_ready
    if _log_table_ready:
        return
    from sqlalchemy import text
    ddl = """
        CREATE TABLE IF NOT EXISTS staging.schema_drift_log (
            id            SERIAL PRIMARY KEY,
            detected_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            filename      TEXT        NOT NULL,
            table_name    TEXT,
            drift_type    TEXT        NOT NULL,
            detail        TEXT,
            drive_file_id TEXT,
            drive_url     TEXT
        )
    """
    try:
        with engine.begin() as conn:
            conn.execute(text(ddl))
        _log_table_ready = True
    except Exception as e:
        logger.warning(f"Notifier: Gagal membuat tabel schema_drift_log: {e}")


def _log_to_db(engine, filename: str, table_name: str,
               drift_type: str, detail: str,
               drive_file_id: str = '', drive_url: str = '') -> None:
    if engine is None:
        return
    _ensure_log_table(engine)
    from sqlalchemy import text
    sql = """
        INSERT INTO staging.schema_drift_log
            (filename, table_name, drift_type, detail, drive_file_id, drive_url)
        VALUES
            (:filename, :table_name, :drift_type, :detail, :drive_file_id, :drive_url)
    """
    try:
        with engine.begin() as conn:
            conn.execute(text(sql), {
                'filename':      filename,
                'table_name':    table_name or '',
                'drift_type':    drift_type,
                'detail':        detail,
                'drive_file_id': drive_file_id or '',
                'drive_url':     drive_url or '',
            })
        logger.info(f"Notifier: Drift '{drift_type}' dari '{filename}' dicatat ke schema_drift_log.")
    except Exception as e:
        logger.warning(f"Notifier: Gagal insert ke schema_drift_log: {e}")


# ============================================================
# GOOGLE DRIVE UPLOAD
# ============================================================

def _upload_to_drive(file_path: str, filename: str) -> tuple:
    """
    Upload file ke Google Drive. Kembalikan (file_id, web_url).
    Jika config belum diisi atau file tidak ada, kembalikan ('', '').
    File yang sama (dalam satu sesi) hanya diupload sekali.
    """
    if not GDRIVE_SERVICE_ACCOUNT_JSON or not GDRIVE_FOLDER_ID:
        logger.debug("Notifier: Konfigurasi Google Drive belum diisi, upload dilewati.")
        return '', ''

    if filename in _uploaded_this_session:
        logger.debug(f"Notifier: '{filename}' sudah pernah diupload sesi ini, dilewati.")
        return '', ''

    if not file_path or not Path(file_path).exists():
        logger.warning(f"Notifier: File tidak ditemukan untuk upload Drive: {file_path}")
        return '', ''

    try:
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaFileUpload
        from google.oauth2 import service_account

        creds = service_account.Credentials.from_service_account_file(
            GDRIVE_SERVICE_ACCOUNT_JSON,
            scopes=['https://www.googleapis.com/auth/drive.file'],
        )
        service = build('drive', 'v3', credentials=creds, cache_discovery=False)

        timestamp_prefix = datetime.now().strftime("%Y%m%d_%H%M%S")
        drive_filename = f"[DRIFT] {timestamp_prefix} {filename}"

        file_metadata = {'name': drive_filename, 'parents': [GDRIVE_FOLDER_ID]}
        media = MediaFileUpload(file_path, resumable=False)

        uploaded = service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id, webViewLink',
        ).execute()

        file_id  = uploaded.get('id', '')
        web_url  = uploaded.get('webViewLink', '')

        _uploaded_this_session.add(filename)
        logger.info(f"Notifier: '{filename}' berhasil diunggah ke Google Drive → {web_url}")
        return file_id, web_url

    except ImportError:
        logger.warning(
            "Notifier: google-api-python-client belum terinstall. "
            "Jalankan: pip install google-api-python-client google-auth"
        )
        return '', ''
    except Exception as e:
        logger.warning(f"Notifier: Gagal upload ke Google Drive: {e}")
        return '', ''


# ============================================================
# TELEGRAM
# ============================================================

def _send_telegram(message: str) -> None:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.debug("Notifier: Token/Chat ID Telegram belum diisi, notifikasi dilewati.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        resp = requests.post(
            url,
            json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"},
            timeout=10,
        )
        if resp.status_code != 200:
            logger.warning(f"Notifier: Telegram API {resp.status_code} — {resp.text[:200]}")
    except requests.exceptions.RequestException as e:
        logger.warning(f"Notifier: Gagal kirim Telegram (jaringan/timeout): {e}")
    except Exception as e:
        logger.warning(f"Notifier: Error tak terduga saat kirim Telegram: {e}")


# ============================================================
# WORKER THREAD — dijalankan di background
# ============================================================

def _run_all(telegram_msg: str, engine, filename: str, table_name: str,
             drift_type: str, detail: str, file_path: str) -> None:
    """
    Satu thread background yang mengerjakan tiga tugas secara berurutan:
    Telegram → Drive upload → DB log
    Urutan ini dipilih agar Telegram terkirim secepat mungkin,
    Drive file_id dan drive_url kemudian tersedia untuk disimpan ke DB.
    """
    _send_telegram(telegram_msg)

    drive_file_id, drive_url = _upload_to_drive(file_path, filename)

    _log_to_db(
        engine=engine,
        filename=filename,
        table_name=table_name,
        drift_type=drift_type,
        detail=detail,
        drive_file_id=drive_file_id,
        drive_url=drive_url,
    )


# ============================================================
# PUBLIC API
# ============================================================

def notify_schema_drift(filename: str, extra_cols: set,
                        table_name: str = '',
                        file_path: str = '',
                        engine=None) -> None:
    """
    Notifikasi ketika ditemukan kolom baru yang tidak dikenal.

    Dieksekusi di background thread — ETL tidak tertunda.
    Tidak pernah melempar exception ke pemanggil.
    """
    if not extra_cols:
        return

    cols_sorted = sorted(str(c) for c in extra_cols)
    cols_block  = "\n".join(f"  • {c}" for c in cols_sorted)
    table_info  = f"\n📋 Tabel staging : <code>{table_name}</code>" if table_name else ""
    timestamp   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    telegram_msg = (
        f"⚠️ <b>SCHEMA DRIFT — KOLOM BARU</b>\n"
        f"{'─' * 32}\n"
        f"📄 File          : <code>{filename}</code>{table_info}\n"
        f"🕐 Waktu         : {timestamp}\n\n"
        f"Kolom baru tidak dikenal (<b>{len(extra_cols)}</b> kolom):\n"
        f"<pre>{cols_block}</pre>\n"
        f"Kolom-kolom ini <b>diabaikan</b> dan tidak dimuat ke database.\n"
        f"Periksa apakah skema marketplace berubah dan update "
        f"<code>VALID_*_COLS</code> di <code>extract_loader.py</code> jika kolom ini penting."
    )

    detail = f"Extra columns: {cols_sorted}"

    t = threading.Thread(
        target=_run_all,
        args=(telegram_msg, engine, filename, table_name,
              'extra_columns', detail, file_path),
        daemon=True,
    )
    t.start()


def notify_unknown_sheet(filename: str, sheet_name: str,
                         file_path: str = '',
                         engine=None) -> None:
    """
    Notifikasi ketika ditemukan sheet baru yang tidak dikenal di file Shopee INCOME.
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    telegram_msg = (
        f"📋 <b>SCHEMA DRIFT — SHEET BARU</b>\n"
        f"{'─' * 32}\n"
        f"📄 File  : <code>{filename}</code>\n"
        f"📑 Sheet : <code>{sheet_name}</code>\n"
        f"🕐 Waktu : {timestamp}\n\n"
        f"Sheet ini <b>tidak diproses</b> karena tidak cocok dengan pola yang dikenal.\n"
        f"Periksa apakah Shopee menambahkan tipe laporan baru dan update "
        f"<code>process_income_file()</code> di <code>extract_loader.py</code> jika diperlukan."
    )

    detail = f"Unknown sheet: {sheet_name}"

    t = threading.Thread(
        target=_run_all,
        args=(telegram_msg, engine, filename, '',
              'unknown_sheet', detail, file_path),
        daemon=True,
    )
    t.start()
