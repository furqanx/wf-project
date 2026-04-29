# src/notifier.py
"""
Modul notifikasi untuk schema drift dan anomali data.

Mengirim notifikasi via Telegram dan mencatat ke:
    - staging.schema_drift_log (database)
    - Google Drive (opsional, untuk file sumber)

Setup Telegram:
    1. Buka Telegram, cari @BotFather
    2. Ketik /newbot → ikuti instruksi → dapatkan BOT_TOKEN
    3. Kirim pesan apa saja ke bot Anda
    4. Buka: https://api.telegram.org/bot<TOKEN>/getUpdates
    5. Salin nilai "id" dari bagian "chat" → isi ke TELEGRAM_CHAT_ID

Tambahkan ke src/.env:
    TELEGRAM_BOT_TOKEN=7412345678:AAFxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
    TELEGRAM_CHAT_ID=123456789
    GDRIVE_SERVICE_ACCOUNT_JSON=/path/to/service-account.json  (opsional)
    GDRIVE_FOLDER_ID=1AbCdEfGhIjKlMnOpQrStUvWx                (opsional)
"""

import os
import threading
import requests
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

from src.db_config import logger

load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))

# ── Konfigurasi Telegram ───────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CHAT_ID   = os.getenv('TELEGRAM_CHAT_ID', '')

# ── Konfigurasi Google Drive ───────────────────────────────────────────────────
GDRIVE_SERVICE_ACCOUNT_JSON = os.getenv('GDRIVE_SERVICE_ACCOUNT_JSON', '')
GDRIVE_FOLDER_ID            = os.getenv('GDRIVE_FOLDER_ID', '')

# ── State internal ─────────────────────────────────────────────────────────────
_uploaded_this_session: set = set()
_log_table_ready: bool = False


# ── DB Log ─────────────────────────────────────────────────────────────────────

def _ensure_log_table(engine):
    global _log_table_ready
    if _log_table_ready:
        return
    from sqlalchemy import text
    try:
        with engine.begin() as conn:
            conn.execute(text("""
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
            """))
        _log_table_ready = True
    except Exception as e:
        logger.warning(f"Notifier: Gagal membuat tabel schema_drift_log: {e}")


def _log_to_db(engine, filename, table_name, drift_type, detail, drive_file_id='', drive_url=''):
    if engine is None:
        return
    _ensure_log_table(engine)
    from sqlalchemy import text
    try:
        with engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO staging.schema_drift_log
                    (filename, table_name, drift_type, detail, drive_file_id, drive_url)
                VALUES
                    (:filename, :table_name, :drift_type, :detail, :drive_file_id, :drive_url)
            """), 
            {
                'filename':      filename,
                'table_name':    table_name or '',
                'drift_type':    drift_type,
                'detail':        detail,
                'drive_file_id': drive_file_id or '',
                'drive_url':     drive_url or '',
            })
    except Exception as e:
        logger.warning(f"Notifier: Gagal insert ke schema_drift_log: {e}")


# ── Telegram ───────────────────────────────────────────────────────────────────

def _send_telegram(message: str):
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
        else:
            logger.info("Notifier: Pesan Telegram berhasil dikirim.")
    except Exception as e:
        logger.warning(f"Notifier: Gagal kirim Telegram: {e}")


# ── Google Drive ───────────────────────────────────────────────────────────────

def _upload_to_drive(file_path: str, filename: str) -> tuple:
    if not GDRIVE_SERVICE_ACCOUNT_JSON or not GDRIVE_FOLDER_ID:
        logger.debug("Notifier: Konfigurasi Google Drive belum diisi, upload dilewati.")
        return '', ''

    if filename in _uploaded_this_session:
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
            body=file_metadata, media_body=media, fields='id, webViewLink',
        ).execute()

        file_id = uploaded.get('id', '')
        web_url = uploaded.get('webViewLink', '')

        _uploaded_this_session.add(filename)
        logger.info(f"Notifier: '{filename}' berhasil diunggah ke Google Drive.")
        return file_id, web_url

    except ImportError:
        logger.warning("Notifier: google-api-python-client belum terinstall.")
        return '', ''
    except Exception as e:
        logger.warning(f"Notifier: Gagal upload ke Google Drive: {e}")
        return '', ''


# ── Worker thread ──────────────────────────────────────────────────────────────

def _run_all(message, engine, filename, table_name, drift_type, detail, file_path):
    _send_telegram(message)
    drive_file_id, drive_url = _upload_to_drive(file_path, filename)
    _log_to_db(engine, filename, table_name, drift_type, detail,
               drive_file_id, drive_url)


def _notify(message, engine, filename, table_name, drift_type, detail, file_path=''):
    t = threading.Thread(
        target=_run_all,
        args=(message, engine, filename, table_name, drift_type, detail, file_path),
        daemon=True,
    )
    t.start()


# ── Public API ─────────────────────────────────────────────────────────────────

def notify_schema_drift(filename: str, extra_cols: set,
                        table_name: str = '',
                        file_path: str = '',
                        engine=None):
    """Notifikasi saat ada kolom baru yang tidak dikenal di file."""
    if not extra_cols:
        return

    cols_sorted = sorted(str(c) for c in extra_cols)
    cols_block  = "\n".join(f"  • {c}" for c in cols_sorted)
    timestamp   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    table_info  = f"\n📋 Tabel staging : <code>{table_name}</code>" if table_name else ""

    message = (
        f"⚠️ <b>SCHEMA DRIFT — KOLOM BARU</b>\n"
        f"{'─' * 32}\n"
        f"📄 File    : <code>{filename}</code>{table_info}\n"
        f"🕐 Waktu   : {timestamp}\n\n"
        f"<b>{len(extra_cols)} kolom baru tidak dikenal:</b>\n"
        f"<pre>{cols_block}</pre>\n"
        f"Kolom-kolom ini <b>diabaikan</b> dan tidak dimuat ke database.\n"
        f"Update <code>VALID_*_COLS</code> di <code>extract_loader.py</code> jika kolom ini penting."
    )

    _notify(message, engine, filename, table_name,
            'extra_columns', f"Extra columns: {cols_sorted}", file_path)


def notify_unknown_sheet(filename: str, sheet_name: str,
                         file_path: str = '',
                         engine=None):
    """Notifikasi saat ada sheet baru yang tidak dikenal."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    message = (
        f"📋 <b>SCHEMA DRIFT — SHEET BARU</b>\n"
        f"{'─' * 32}\n"
        f"📄 File  : <code>{filename}</code>\n"
        f"📑 Sheet : <code>{sheet_name}</code>\n"
        f"🕐 Waktu : {timestamp}\n\n"
        f"Sheet ini <b>tidak diproses</b> karena tidak cocok dengan pola yang dikenal.\n"
        f"Update <code>process_income_file()</code> di <code>extract_loader.py</code> jika diperlukan."
    )

    _notify(message, engine, filename, '',
            'unknown_sheet', f"Unknown sheet: {sheet_name}", file_path)


def notify_unmapped_values(source: str, category: str,
                           values: list, engine=None):
    """Notifikasi saat ada nilai baru yang tidak ada di mapping (Kategori 2)."""
    if not values:
        return

    timestamp  = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    vals_block = "\n".join(f"  • {v}" for v in values)

    message = (
        f"⚠️ <b>NILAI TIDAK DIKENAL — {category}</b>\n"
        f"{'─' * 32}\n"
        f"📦 Sumber : <code>{source}</code>\n"
        f"🕐 Waktu  : {timestamp}\n\n"
        f"<b>{len(values)} nilai tidak ada di mapping:</b>\n"
        f"<pre>{vals_block}</pre>\n"
        f"Nilai-nilai ini <b>di-skip</b> saat transform.\n"
        f"Tambahkan ke mapping yang sesuai agar data tidak hilang."
    )

    _notify(message, engine, source, '',
            'unmapped_values', f"{category}: {values}")
