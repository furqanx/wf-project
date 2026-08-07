"""streamlit_app.py — Wellfarm Data Hub
Upload file staging + monitoring data per marketplace.
"""

import logging
import os
import sys
import tempfile
import threading
import json
import html
import pandas as pd
import altair as alt
import streamlit as st
from sqlalchemy import text

sys.path.insert(0, os.path.dirname(__file__))

from src.db_config import get_engine
from src.file_inspector import check_file_status, check_duplicate_order_ids
from src.extract_loader import process_order_file, process_income_file, process_report_file, process_crewdible_file
from src.transform.runner import run as run_transform
from src.crewdible.runner import run as run_transform_crewdible

# ── Halaman ────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title='Wellfarm — Data Hub',
    page_icon='🌾',
    layout='wide',
)

# ── CSS ────────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
html, body, [data-testid="stAppViewContainer"] {
    font-family: 'Inter', 'Segoe UI', sans-serif;
}
.wf-header {
    background: linear-gradient(135deg, #1a6b3a 0%, #2d9b5a 100%);
    border-radius: 16px;
    padding: 28px 36px;
    margin-bottom: 28px;
    color: white;
}
.wf-header h1 { margin: 0 0 6px 0; font-size: 2rem; font-weight: 700; letter-spacing: -0.5px; }
.wf-header p  { margin: 0; opacity: 0.85; font-size: 0.95rem; }

.wf-context-card {
    background: #f8fafc;
    border: 1px solid #e2e8f0;
    border-left: 4px solid #2d9b5a;
    border-radius: 10px;
    padding: 16px 20px;
    margin-bottom: 20px;
    font-size: 0.9rem;
    color: #334155;
}
.wf-context-card strong { color: #1a6b3a; }

.wf-stage {
    background: #ffffff;
    border: 1px solid #dbe4ee;
    border-left: 5px solid #64748b;
    border-radius: 10px;
    padding: 16px 18px;
    margin: 16px 0;
    color: #334155;
}
.wf-stage-ready { border-left-color: #2563eb; background: #f8fbff; }
.wf-stage-success { border-left-color: #16a34a; background: #f7fdf9; }
.wf-stage-warning { border-left-color: #d97706; background: #fffaf0; }
.wf-stage-running { border-left-color: #0f766e; background: #f4fbfa; }
.wf-stage-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    margin-bottom: 8px;
}
.wf-stage-title {
    font-size: 0.96rem;
    font-weight: 700;
    color: #172033;
}
.wf-stage-badge {
    border-radius: 999px;
    background: #e2e8f0;
    color: #334155;
    font-size: 0.72rem;
    font-weight: 700;
    padding: 4px 10px;
    white-space: nowrap;
}
.wf-stage-body {
    font-size: 0.86rem;
    line-height: 1.5;
    color: #475569;
}
.wf-stage-meta {
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
    margin-top: 12px;
}
.wf-stage-chip {
    display: inline-flex;
    align-items: center;
    border: 1px solid #cbd5e1;
    border-radius: 999px;
    background: #ffffff;
    color: #334155;
    font-size: 0.76rem;
    font-weight: 600;
    padding: 4px 10px;
}

.wf-file-card {
    background: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 10px;
    padding: 14px 18px;
    margin-bottom: 10px;
    display: flex;
    align-items: center;
    gap: 16px;
}
.wf-filename { flex: 1; font-size: 0.88rem; color: #1e293b; font-weight: 500; word-break: break-all; }

.wf-badge {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    padding: 4px 12px;
    border-radius: 20px;
    font-size: 0.78rem;
    font-weight: 600;
    white-space: nowrap;
}
.badge-new     { background: #dcfce7; color: #166534; }
.badge-loaded  { background: #d1fae5; color: #065f46; }
.badge-partial { background: #fef9c3; color: #854d0e; }
.badge-anomaly { background: #fee2e2; color: #991b1b; }
.badge-unknown { background: #f1f5f9; color: #475569; }

.wf-stat-row { display: flex; gap: 12px; margin: 18px 0; flex-wrap: wrap; }
.wf-stat {
    flex: 1; min-width: 120px;
    background: #f8fafc;
    border: 1px solid #e2e8f0;
    border-radius: 10px;
    padding: 14px 18px;
    text-align: center;
}
.wf-stat .stat-num   { font-size: 1.8rem; font-weight: 700; line-height: 1; }
.wf-stat .stat-label { font-size: 0.75rem; color: #64748b; margin-top: 4px; }
.stat-new     .stat-num { color: #16a34a; }
.stat-loaded  .stat-num { color: #059669; }
.stat-partial .stat-num { color: #d97706; }
.stat-anomaly .stat-num { color: #dc2626; }

.wf-section-title {
    font-size: 0.75rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: #94a3b8;
    margin: 24px 0 10px 0;
}

#MainMenu { visibility: hidden; }
footer    { visibility: hidden; }

[data-testid="stSidebar"] {
    background: #f8fafc;
    border-right: 1px solid #e2e8f0;
}
[data-testid="stSidebar"] > div:first-child {
    padding-top: 24px;
}
.wf-sidebar-brand {
    background: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 10px;
    box-sizing: border-box;
    padding: 14px 16px;
    margin-bottom: 18px;
    width: 100%;
}
.wf-sidebar-brand-title {
    color: #0f172a;
    font-size: 0.98rem;
    font-weight: 800;
    line-height: 1.2;
}
.wf-sidebar-brand-subtitle {
    color: #64748b;
    font-size: 0.76rem;
    line-height: 1.45;
    margin-top: 6px;
}
.wf-sidebar-label {
    color: #94a3b8;
    font-size: 0.72rem;
    font-weight: 800;
    letter-spacing: 0.08em;
    margin: 12px 0 8px 2px;
    text-transform: uppercase;
}
.wf-sidebar-note {
    border-top: 1px solid #e2e8f0;
    color: #64748b;
    font-size: 0.74rem;
    line-height: 1.45;
    margin-top: 20px;
    padding-top: 14px;
}
[data-testid="stSidebar"] [role="radiogroup"] label {
    background: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 8px;
    box-sizing: border-box;
    display: flex;
    margin-bottom: 8px;
    padding: 8px 10px;
    width: 100%;
}
[data-testid="stSidebar"] [role="radiogroup"] label:hover {
    border-color: #94a3b8;
    background: #f9fbfd;
}
hr { border: none; border-top: 1px solid #e2e8f0; margin: 20px 0; }
</style>
""", unsafe_allow_html=True)


def inject_dark_theme_styles():
    st.markdown("""
    <style>
    html, body, [data-testid="stAppViewContainer"] {
        background: #2f3640;
        color: #f1f5f9;
    }
    [data-testid="stHeader"] {
        background: rgba(47, 54, 64, 0.92);
    }
    [data-testid="stToolbar"] {
        color: #d8dee9;
    }
    .block-container {
        color: #f1f5f9;
    }
    h1, h2, h3, h4, h5, h6,
    [data-testid="stMarkdownContainer"],
    [data-testid="stMarkdownContainer"] p,
    [data-testid="stMarkdownContainer"] li,
    label {
        color: #f1f5f9;
    }
    [data-testid="stSidebar"] {
        background: #353d49;
        border-right-color: #4b5563;
    }
    .wf-header {
        background: linear-gradient(135deg, #1f6f43 0%, #2e8b57 100%);
        box-shadow: 0 18px 38px rgba(25, 30, 38, 0.25);
    }
    .wf-sidebar-brand,
    [data-testid="stSidebar"] [role="radiogroup"] label,
    .wf-stage,
    .wf-file-card,
    .wf-stat,
    .wf-context-card {
        background: #3b4452;
        border-color: #55606f;
    }
    .wf-sidebar-brand-title,
    .wf-stage-title,
    .wf-filename,
    .wf-context-card strong {
        color: #ffffff;
    }
    .wf-sidebar-brand-subtitle,
    .wf-sidebar-note,
    .wf-stage-body,
    .wf-stat .stat-label {
        color: #cbd5e1;
    }
    .wf-sidebar-note,
    hr {
        border-color: #55606f;
    }
    [data-testid="stSidebar"] [role="radiogroup"] label:hover {
        background: #465160;
        border-color: #687587;
    }
    .wf-stage-ready {
        background: #37465b;
        border-left-color: #7cb4ff;
    }
    .wf-stage-success {
        background: #334d40;
        border-left-color: #4ade80;
    }
    .wf-stage-warning {
        background: #504836;
        border-left-color: #fbbf24;
    }
    .wf-stage-running {
        background: #334e4d;
        border-left-color: #5eead4;
    }
    .wf-stage-badge,
    .wf-stage-chip {
        background: #465160;
        border-color: #64748b;
        color: #e2e8f0;
    }
    .badge-new,
    .badge-loaded {
        background: rgba(34, 197, 94, 0.16);
        color: #86efac;
    }
    .badge-partial {
        background: rgba(245, 158, 11, 0.16);
        color: #fcd34d;
    }
    .badge-anomaly {
        background: rgba(239, 68, 68, 0.16);
        color: #fca5a5;
    }
    .badge-unknown {
        background: rgba(148, 163, 184, 0.16);
        color: #e2e8f0;
    }
    .wf-section-title,
    .wf-sidebar-label {
        color: #cbd5e1;
    }
    [data-baseweb="select"] > div,
    [data-testid="stFileUploaderDropzone"],
    [data-testid="stNumberInput"] input,
    input,
    textarea {
        background: #3b4452;
        border-color: #64748b;
        color: #f8fafc;
    }
    [data-testid="stFileUploaderDropzone"] small,
    [data-testid="stFileUploaderDropzone"] span,
    [data-testid="stCaptionContainer"] {
        color: #cbd5e1;
    }
    [data-testid="stFileUploaderDropzone"] button {
        background: #f8fafc;
        border: 1px solid #cbd5e1;
        color: #172033;
    }
    [data-testid="stFileUploaderDropzone"] button:hover {
        background: #e2e8f0;
        border-color: #94a3b8;
        color: #0f172a;
    }
    [data-testid="stFileUploaderDropzone"] button svg {
        color: #172033;
        fill: currentColor;
    }
    [data-testid="stFileUploaderDropzone"] button:disabled,
    [data-testid="stFileUploaderDropzone"] button[disabled] {
        background: #e2e8f0;
        border-color: #cbd5e1;
        color: #475569;
        opacity: 1;
    }
    [data-testid="stFileUploaderDropzone"] button:disabled svg,
    [data-testid="stFileUploaderDropzone"] button[disabled] svg {
        color: #475569;
        fill: currentColor;
    }
    div[data-testid="stAlert"] {
        background: #3b4452;
        color: #f1f5f9;
    }
    button[kind="primary"] {
        border-color: #16a34a;
    }
    </style>
    """, unsafe_allow_html=True)

# ── Konstanta ──────────────────────────────────────────────────────────────────
FASE_OPTIONS = ['ORDER', 'INCOME', 'REPORT']

MARKETPLACE_OPTIONS = {
    'Shopee':             'shopee',
    'TikTok / Tokopedia': 'tiktok_tokopedia',
    'Lazada':             'lazada',
}

MARKETPLACE_ID = {
    'shopee':             1,
    'tiktok_tokopedia':   5,
    'lazada':             4,
}
FASE_DESC = {
    'ORDER':  'Data transaksi pesanan',
    'INCOME': 'Data pemasukan & komisi',
    'REPORT': 'Laporan keuangan / saldo',
}
MARKETPLACE_ICON = {
    'Shopee':             '🟠',
    'TikTok / Tokopedia': '🟢',
    'Lazada':             '🟣',
}
STATUS_META = {
    'new':          ('✦', 'Baru',               'badge-new'),
    'fully_loaded': ('✔', 'Sudah Dimuat Penuh',  'badge-loaded'),
    'partial':      ('◑', 'Dimuat Sebagian',     'badge-partial'),
    'anomaly':      ('⚠', 'Anomali',             'badge-anomaly'),
    'unknown':      ('?', 'Tidak Dikenali',       'badge-unknown'),
}

TABLE_INFO = [
    ('stg_shopee_orders',           'Shopee',           'ORDER'),
    ('stg_tiktok_tokopedia_orders', 'TikTok/Tokopedia', 'ORDER'),
    ('stg_lazada_orders',           'Lazada',           'ORDER'),

    ('stg_shopee_income_main',      'Shopee',           'INCOME'),
    ('stg_tiktok_tokopedia_income', 'TikTok/Tokopedia', 'INCOME'),
    ('stg_lazada_income',           'Lazada',           'INCOME'),

    ('stg_shopee_report',           'Shopee',           'REPORT'),
    ('stg_tiktok_tokopedia_report', 'TikTok/Tokopedia', 'REPORT'),
    ('stg_lazada_report',           'Lazada',           'REPORT'),
]

COMPLETE_TABLE_INFO = [
    ('stg_shopee_orders',                        'Shopee',           'ORDER'),
    ('stg_tiktok_tokopedia_orders',              'TikTok/Tokopedia', 'ORDER'),
    ('stg_lazada_orders',                        'Lazada',           'ORDER'),

    ('stg_shopee_income_main',                   'Shopee',           'INCOME'),
    ('stg_shopee_income_adjustment',             'Shopee',           'INCOME'),
    ('stg_shopee_income_order_processing_fee',   'Shopee',           'INCOME'),
    ('stg_shopee_income_service_fee',            'Shopee',           'INCOME'),
    ('stg_shopee_income_shipping_discrepancy',   'Shopee',           'INCOME'),
    ('stg_tiktok_tokopedia_income',              'TikTok/Tokopedia', 'INCOME'),
    ('stg_lazada_income',                        'Lazada',           'INCOME'),

    ('stg_shopee_report',                        'Shopee',           'REPORT'),
    ('stg_tiktok_tokopedia_report',              'TikTok/Tokopedia', 'REPORT'),
    ('stg_lazada_report',                        'Lazada',           'REPORT'),
]


MP_COLORS = {
    'Shopee':           '#EE4D2D',
    'TikTok/Tokopedia': '#2ECC71',
    'Lazada':           '#9B59B6',
}

# ── DB Engine ──────────────────────────────────────────────────────────────────
@st.cache_resource
def get_db_engine():
    return get_engine()


@st.cache_data(ttl=600)
def load_stores(_engine, marketplace_id):
    with _engine.connect() as conn:
        result = conn.execute(text("""
            SELECT channel_name FROM public.dim_sales_channel
            WHERE marketplace_id = :mp_id
            ORDER BY channel_name
        """), {'mp_id': marketplace_id})
        return [r[0] for r in result]


# ── Background Transform ───────────────────────────────────────────────────────
def _run_transform_background(marketplace, engine):
    try:
        run_transform(marketplace=marketplace, engine=engine)
    except Exception as e:
        logging.getLogger().error(f"[TRANSFORM-BG] {marketplace}: {e}")


def _run_transform_job_background(job_ids, marketplace, engine):
    try:
        run_transform(marketplace=marketplace, engine=engine)
        with engine.begin() as conn:
            conn.execute(text("""
                UPDATE staging.transform_job_log
                SET status = 'success',
                    finished_at = NOW(),
                    error_message = NULL
                WHERE job_id = ANY(:job_ids)
            """), {'job_ids': job_ids})
    except Exception as e:
        logging.getLogger().error(f"[TRANSFORM-BG] {marketplace}: {e}")
        with engine.begin() as conn:
            conn.execute(text("""
                UPDATE staging.transform_job_log
                SET status = 'failed',
                    finished_at = NOW(),
                    error_message = :error_message
                WHERE job_id = ANY(:job_ids)
            """), {
                'job_ids': job_ids,
                'error_message': str(e),
            })


def _run_crewdible_transform_background(engine):
    try:
        run_transform_crewdible(engine=engine)
    except Exception as e:
        logging.getLogger().error(f"[TRANSFORM-BG] crewdible: {e}")


# ── Log Handler ────────────────────────────────────────────────────────────────
class StreamlitLogHandler(logging.Handler):
    def emit(self, record):
        st.session_state.setdefault('log_lines', []).append(self.format(record))


def attach_streamlit_handler():
    root = logging.getLogger()
    stale_handlers = [
        h for h in root.handlers
        if getattr(h, '_wf_streamlit_handler', False)
        or h.__class__.__name__ == 'StreamlitLogHandler'
    ]
    for h in stale_handlers[1:]:
        root.removeHandler(h)
        h.close()
    if stale_handlers:
        return
    h = StreamlitLogHandler()
    h._wf_streamlit_handler = True
    h.setFormatter(logging.Formatter('%(asctime)s  %(levelname)-8s  %(message)s', '%H:%M:%S'))
    root.addHandler(h)


# ── Monitoring: data loader ────────────────────────────────────────────────────
@st.cache_data(ttl=300)
def load_staging_summary(_engine):
    rows = []
    with _engine.connect() as conn:
        for table, marketplace, fase in TABLE_INFO:
            try:
                result = conn.execute(text(f"""
                    SELECT
                        source_filename,
                        COUNT(*)          AS baris,
                        MIN(uploaded_at)  AS pertama_upload,
                        MAX(uploaded_at)  AS terakhir_upload
                    FROM staging.{table}
                    GROUP BY source_filename
                    ORDER BY MAX(uploaded_at) DESC
                """))
                for r in result:
                    rows.append({
                        'Marketplace':     marketplace,
                        'Fase':            fase,
                        'File':            r.source_filename,
                        'Baris':           int(r.baris),
                        'Pertama Upload':  r.pertama_upload,
                        'Terakhir Upload': r.terakhir_upload,
                    })
            except Exception:
                pass
    return pd.DataFrame(rows)


# @st.cache_data(ttl=300)
# def load_order_id_summary(_engine):
#     rows = []
#     with _engine.connect() as conn:
#         for table, marketplace, fase in COMPLETE_TABLE_INFO:
#             try:
#                 result = conn.execute(text(f"""
#                     SELECT 
#                         source_filename, 
#                         COUNT(DISTINCT order_number) AS "jumlah_order_id"
#                     FROM staging.stg_lazada_orders
#                     GROUP BY source_filename;
#                 """))
#                 for r in result:
#                     rows.append({
#                         'Marketplace':     marketplace,
#                         'Fase':            fase, 
#                         'File':            r.source_filename,
#                         'Jumlah Order ID': int(r.jumlah_order_id)
#                     })
#             except Exception:
#                 pass
#     return pd.DataFrame(rows)


@st.cache_data(ttl=300)
def load_timeseries(_engine):
    union_parts = [
        f"""
        SELECT
            DATE(uploaded_at)   AS tanggal,
            '{mp}'              AS marketplace,
            '{fase}'            AS fase,
            COUNT(*)            AS baris
        FROM staging.{table}
        GROUP BY DATE(uploaded_at)
        """
        for table, mp, fase in TABLE_INFO
    ]
    query = ' UNION ALL '.join(union_parts) + ' ORDER BY tanggal'
    try:
        with _engine.connect() as conn:
            result = conn.execute(text(query))
            rows = [
                {'Tanggal': r.tanggal, 'Marketplace': r.marketplace,
                 'Fase': r.fase, 'Baris': int(r.baris)}
                for r in result
            ]
        return pd.DataFrame(rows)
    except Exception:
        return pd.DataFrame()


# ── HTML helpers ───────────────────────────────────────────────────────────────
def render_badge(status_key):
    icon, label, css = STATUS_META.get(status_key, STATUS_META['unknown'])
    return f'<span class="wf-badge {css}">{icon}&nbsp;{label}</span>'


def render_file_card(filename, status_key, rows_in_db, rows_in_file):
    badge = render_badge(status_key)
    db_info = ''
    if rows_in_db > 0 or rows_in_file > 0:
        db_info = (
            f'<span style="font-size:0.78rem;color:#64748b;white-space:nowrap;">'
            f'DB&nbsp;<b style="color:#1e293b">{rows_in_db:,}</b>'
            f'&nbsp;/&nbsp;File&nbsp;<b style="color:#1e293b">{rows_in_file:,}</b>&nbsp;baris'
            f'</span>'
        )
    return (
        f'<div class="wf-file-card">'
        f'<span style="font-size:1.1rem;">📄</span>'
        f'<span class="wf-filename">{filename}</span>'
        f'{db_info}{badge}'
        f'</div>'
    )


def render_stat_row(counts):
    def _stat(css, num, label):
        return (
            f'<div class="wf-stat {css}">'
            f'<div class="stat-num">{num}</div>'
            f'<div class="stat-label">{label}</div>'
            f'</div>'
        )
    return (
        f'<div class="wf-stat-row">'
        + _stat('stat-new',     counts.get('new', 0),          'Baru')
        + _stat('stat-loaded',  counts.get('fully_loaded', 0), 'Sudah Dimuat')
        + _stat('stat-partial', counts.get('partial', 0),      'Sebagian')
        + _stat('stat-anomaly', counts.get('anomaly', 0),      'Anomali')
        + '</div>'
    )


def render_stage_panel(title, status, body, variant='ready', chips=None):
    chip_html = ''
    if chips:
        chip_html = (
            '<div class="wf-stage-meta">'
            + ''.join(f'<span class="wf-stage-chip">{html.escape(str(chip))}</span>' for chip in chips)
            + '</div>'
        )
    st.markdown(
        f'''
        <div class="wf-stage wf-stage-{variant}">
            <div class="wf-stage-head">
                <div class="wf-stage-title">{html.escape(title)}</div>
                <span class="wf-stage-badge">{html.escape(status)}</span>
            </div>
            <div class="wf-stage-body">{html.escape(body)}</div>
            {chip_html}
        </div>
        ''',
        unsafe_allow_html=True,
    )


def _normalize_source_filenames(value):
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            return []
    return []


def get_sales_online_transform_jobs(engine, statuses):
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT job_id, marketplace, fase, source_filenames, created_at
            FROM staging.transform_job_log
            WHERE job_type = 'sales_online'
              AND status = ANY(:statuses)
            ORDER BY created_at DESC
        """), {'statuses': statuses})
        return [
            {
                'job_id': r.job_id,
                'marketplace': r.marketplace,
                'fase': r.fase,
                'source_filenames': _normalize_source_filenames(r.source_filenames),
                'created_at': r.created_at,
            }
            for r in result
        ]


def create_sales_online_transform_job(engine, marketplace, fase, filenames):
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO staging.transform_job_log
                (job_type, marketplace, fase, status, source_filenames)
            VALUES
                ('sales_online', :marketplace, :fase, 'pending', CAST(:source_filenames AS jsonb))
        """), {
            'marketplace': marketplace,
            'fase': fase,
            'source_filenames': json.dumps(filenames),
        })


def render_sales_online_transform_control(engine, key_suffix='main'):
    running_key = 'sales_online_transform_running'
    pending_jobs = get_sales_online_transform_jobs(engine, ['pending'])
    running_jobs = get_sales_online_transform_jobs(engine, ['running'])
    if not running_jobs:
        st.session_state[running_key] = False

    if not pending_jobs and not running_jobs:
        return

    st.markdown(
        '<div class="wf-section-title">Migrasi Data ke Tabel Utama</div>',
        unsafe_allow_html=True,
    )

    if running_jobs:
        running_marketplaces = sorted({job['marketplace'].upper() for job in running_jobs})
        render_stage_panel(
            title='4. Migrasi ke Tabel Utama',
            status='Sedang berjalan',
            body=(
                'Migrasi sedang memindahkan data dari staging ke tabel utama. '
                'Tombol akan aktif lagi jika ada upload staging baru.'
            ),
            variant='running',
            chips=[f"Marketplace: {', '.join(running_marketplaces)}"],
        )
        return

    jobs_by_marketplace = {}
    for job in pending_jobs:
        jobs_by_marketplace.setdefault(job['marketplace'], []).append(job)

    for marketplace, marketplace_jobs in jobs_by_marketplace.items():
        files = []
        for job in marketplace_jobs:
            files.extend(job['source_filenames'])
        files = list(dict.fromkeys(files))
        marketplace_label = marketplace.upper()

        render_stage_panel(
            title='4. Migrasi ke Tabel Utama',
            status='Perlu tindakan',
            body=(
                'Data sudah masuk staging, tetapi belum masuk tabel utama dan dashboard. '
                'Jalankan migrasi setelah batch file dipastikan benar.'
            ),
            variant='warning',
            chips=[f'Marketplace: {marketplace_label}', f'{len(marketplace_jobs)} batch pending'],
        )

        if files:
            with st.expander(f'{len(files)} file staging menunggu migrasi ({marketplace_label})', expanded=False):
                st.code('\n'.join(files), language=None)

        run_transform_button = st.button(
            f'Migrasikan {marketplace_label} ke Tabel Utama',
            type='primary',
            use_container_width=True,
            key=f'run_sales_online_transform_button_{key_suffix}_{marketplace}',
        )

        if run_transform_button:
            job_ids = [job['job_id'] for job in marketplace_jobs]
            with engine.begin() as conn:
                conn.execute(text("""
                    UPDATE staging.transform_job_log
                    SET status = 'running',
                        started_at = NOW(),
                        error_message = NULL
                    WHERE job_id = ANY(:job_ids)
                """), {'job_ids': job_ids})
            st.session_state[running_key] = True
            st.session_state['sales_online_transform_running_marketplace'] = marketplace
            load_staging_summary.clear()
            load_timeseries.clear()
            threading.Thread(
                target=_run_transform_job_background,
                args=(job_ids, marketplace, engine),
                daemon=True,
            ).start()
            render_stage_panel(
                title='4. Migrasi ke Tabel Utama',
                status='Dimulai',
                body='Migrasi mulai berjalan di background. Status terbaru akan terbaca dari database.',
                variant='running',
                chips=[f'Marketplace: {marketplace_label}'],
            )


# ── Tab 1: Upload ──────────────────────────────────────────────────────────────
def render_upload_tab(engine):
    st.markdown('#### Upload Data Sales Online')
    st.markdown('<div class="wf-section-title">Pengaturan Upload</div>', unsafe_allow_html=True)

    col_fase, col_marketplace, col_toko = st.columns(3)
    with col_fase:
        fase = st.selectbox(
            'Fase Data',
            FASE_OPTIONS,
            index=0,
            help='Pilih jenis data yang akan diunggah.',
        )
        st.caption(f'_{FASE_DESC.get(fase, "")}_')
    with col_marketplace:
        marketplace_label = st.selectbox(
            'Marketplace',
            list(MARKETPLACE_OPTIONS.keys()),
            index=0,
        )
        marketplace = MARKETPLACE_OPTIONS[marketplace_label]
    with col_toko:
        stores = load_stores(engine, MARKETPLACE_ID[marketplace])
        toko = st.selectbox(
            'Toko',
            stores,
            help='Pilih toko asal file ini.',
        )

    # skip_loaded = st.checkbox('Lewati file yang sudah dimuat penuh', value=True)
    skip_loaded = False

    render_stage_panel(
        title='1. Target Upload',
        status='Dipilih',
        body='File yang diunggah akan dibaca sesuai target berikut.',
        variant='ready',
        chips=[
            f'Fase: {fase}',
            f'Marketplace: {marketplace_label}',
            f'Toko: {toko}',
        ],
    )

    uploaded_files = st.file_uploader(
        'Pilih satu atau beberapa file Excel (.xlsx)',
        type=['xlsx'],
        accept_multiple_files=True,
        key='file_uploader',
    )

    if not uploaded_files:
        st.markdown(
            "<div style='text-align:center;padding:40px 0;color:#94a3b8;font-size:0.9rem;'>"
            "📂&nbsp; Belum ada file yang dipilih.<br>"
            "<span style='font-size:0.8rem;'>Klik tombol di atas atau seret file ke sini.</span>"
            "</div>",
            unsafe_allow_html=True,
        )
        render_sales_online_transform_control(engine, key_suffix='top')
        return

    tmp_dir = tempfile.mkdtemp()
    file_statuses = []
    with st.spinner('Memeriksa status file terhadap database…'):
        for uf in uploaded_files:
            tmp_path = os.path.join(tmp_dir, uf.name)
            with open(tmp_path, 'wb') as f:
                f.write(uf.getbuffer())
            status = check_file_status(
                filename=uf.name, file_path=tmp_path,
                fase=fase, marketplace=marketplace, engine=engine,
            )
            file_statuses.append((uf, status, tmp_path))

    counts = {}
    for _, s, _ in file_statuses:
        counts[s['status']] = counts.get(s['status'], 0) + 1

    render_stage_panel(
        title='2. Pemeriksaan File',
        status='Selesai dicek',
        body='File sudah dianalisis terhadap database. Data belum masuk staging sebelum tombol tahap berikutnya ditekan.',
        variant='ready',
        chips=[
            f'{len(file_statuses)} file',
            f"{counts.get('new', 0)} baru",
            f"{counts.get('fully_loaded', 0)} sudah dimuat",
            f"{counts.get('partial', 0)} sebagian",
            f"{counts.get('anomaly', 0)} anomali",
        ],
    )

    # Tampilan RINGKASAN
    st.markdown(f'<div class="wf-section-title">Ringkasan — {len(file_statuses)} file</div>',
                unsafe_allow_html=True)
    st.markdown(render_stat_row(counts), unsafe_allow_html=True)

    st.markdown('<div class="wf-section-title">Detail Status Per File</div>', unsafe_allow_html=True)
    st.markdown(
        ''.join(render_file_card(uf.name, s['status'], s['rows_in_db'], s['rows_in_file'])
                for uf, s, _ in file_statuses),
        unsafe_allow_html=True,
    )

    anomaly_files = [uf.name for uf, s, _ in file_statuses if s['status'] == 'anomaly']
    partial_files  = [uf.name for uf, s, _ in file_statuses if s['status'] == 'partial']
    if anomaly_files:
        st.warning(
            '**⚠ Anomali Terdeteksi**  \n'
            'File berikut memiliki lebih banyak baris di DB daripada di file aslinya:  \n'
            + '  \n'.join(f'• `{f}`' for f in anomaly_files)
        )
    if partial_files:
        st.info(
            '**◑ File Dimuat Sebagian**  \n'
            'File berikut hanya sebagian masuk ke database:  \n'
            + '  \n'.join(f'• `{f}`' for f in partial_files)
        )

    to_process    = [item for item in file_statuses
                    if not (skip_loaded and item[1]['status'] == 'fully_loaded')]
    skipped_count = len(file_statuses) - len(to_process)

    st.markdown('<hr>', unsafe_allow_html=True)
    render_stage_panel(
        title='3. Input ke Staging',
        status='Siap diproses' if to_process else 'Tidak ada file baru',
        body=(
            'Tahap ini hanya memasukkan file ke staging. '
            'Data belum masuk tabel utama atau dashboard sampai tahap migrasi dijalankan.'
        ),
        variant='ready' if to_process else 'success',
        chips=[f'{len(to_process)} file akan masuk staging'],
    )
    col_info, col_btn = st.columns([4, 1])
    with col_info:
        if not to_process:
            st.success('Semua file sudah dimuat penuh. Tidak ada yang perlu diproses.')
        elif skipped_count > 0:
            st.caption(f'{skipped_count} file dilewati · **{len(to_process)} file akan diproses**')
        else:
            st.caption(f'**{len(to_process)} file akan diproses**')
    with col_btn:
        # PROCESS BUTTON
        run_button = st.button(
            f'Masukkan {len(to_process)} File ke Staging',
            type='primary',
            use_container_width=True,
            disabled=(not to_process),
        )

    if not to_process or not run_button:
        render_sales_online_transform_control(engine, key_suffix='after_check')
        return

    ############################# INSERTION PROCESS #############################

    st.session_state['log_lines'] = []
    st.markdown('<div class="wf-section-title">Progress Input ke Staging</div>', unsafe_allow_html=True)
    progress_bar  = st.progress(0, text='Memulai…')
    log_container = st.empty()
    total, errors = len(to_process), []

    for idx, (uf, _, tmp_path) in enumerate(to_process): # debugging to_process ini
        progress_bar.progress(idx / total, text=f'({idx+1}/{total})  {uf.name}')
        try:
            if fase == 'ORDER':
                process_order_file(tmp_path, marketplace, engine, nama_toko_override=str(toko).lower() if toko else None)
            elif fase == 'INCOME':
                process_income_file(tmp_path, marketplace, engine, nama_toko_override=str(toko).lower() if toko else None)
            elif fase == 'REPORT':
                process_report_file(tmp_path, marketplace, engine, nama_toko_override=str(toko).lower() if toko else None)
        except Exception as e:
            logging.getLogger().error(f'GAGAL memproses {uf.name}: {e}')
            errors.append(uf.name)

    progress_bar.progress(1.0, text='Selesai!')

    final_logs = st.session_state.get('log_lines', [])
    if final_logs:
        with log_container.container():
            with st.expander('📋 Lihat Log Lengkap', expanded=False):
                st.code('\n'.join(final_logs), language=None)

    sukses = total - len(errors)
    if errors:
        st.error(f'**Proses selesai dengan {len(errors)} error.**  \n' + '  \n'.join(f'• `{f}`' for f in errors))
    else:
        render_stage_panel(
            title='3. Input ke Staging',
            status='Berhasil',
            body='File berhasil dimasukkan ke staging. Lanjutkan ke migrasi jika data sudah siap masuk tabel utama.',
            variant='success',
            chips=[f'{total} file masuk staging'],
        )

    if sukses > 0:
        st.session_state['sales_online_transform_running'] = False
        create_sales_online_transform_job(
            engine=engine,
            marketplace=marketplace,
            fase=fase,
            filenames=[uf.name for uf, _, _ in to_process],
        )
        st.markdown('<hr>', unsafe_allow_html=True)
        render_sales_online_transform_control(engine, key_suffix='after_upload')


# # ── Tab 2: Crewdible ───────────────────────────────────────────────────────────
# def _crewdible_rows_in_db(filename, engine):
#     try:
#         with engine.connect() as conn:
#             return conn.execute(
#                 text("SELECT COUNT(*) FROM staging.stg_crewdible WHERE source_filename = :fn"),
#                 {"fn": filename}
#             ).scalar()
#     except Exception:
#         return 0


# def render_crewdible_tab(engine):
#     st.markdown(
#         '<div class="wf-context-card">'
#         'Upload file transaksi <strong>Crewdible</strong> (3PL fulfillment). '
#         'Mendukung format <code>.xlsx</code> standar maupun <code>.xls</code> dari ekspor Crewdible.'
#         '</div>',
#         unsafe_allow_html=True,
#     )

#     uploaded_files = st.file_uploader(
#         'Pilih satu atau beberapa file Crewdible (.xlsx / .xls)',
#         type=['xlsx', 'xls'],
#         accept_multiple_files=True,
#         key='crewdible_uploader',
#     )

#     if not uploaded_files:
#         st.markdown(
#             "<div style='text-align:center;padding:40px 0;color:#94a3b8;font-size:0.9rem;'>"
#             "📂&nbsp; Belum ada file yang dipilih.<br>"
#             "<span style='font-size:0.8rem;'>Klik tombol di atas atau seret file ke sini.</span>"
#             "</div>",
#             unsafe_allow_html=True,
#         )
#         return

#     tmp_dir = tempfile.mkdtemp()
#     file_infos = []
#     with st.spinner('Memeriksa status file terhadap database…'):
#         for uf in uploaded_files:
#             tmp_path = os.path.join(tmp_dir, uf.name)
#             with open(tmp_path, 'wb') as f:
#                 f.write(uf.getbuffer())
#             rows_in_db = _crewdible_rows_in_db(uf.name, engine)
#             status = 'fully_loaded' if rows_in_db > 0 else 'new'
#             file_infos.append((uf, tmp_path, rows_in_db, status))

#     st.markdown(f'<div class="wf-section-title">Status File — {len(file_infos)} file</div>',
#                 unsafe_allow_html=True)
#     cards_html = ''
#     for uf, _, rows_in_db, status in file_infos:
#         badge = render_badge(status)
#         db_info = (
#             f'<span style="font-size:0.78rem;color:#64748b;white-space:nowrap;">'
#             f'DB&nbsp;<b style="color:#1e293b">{rows_in_db:,}</b>&nbsp;baris'
#             f'</span>' if rows_in_db > 0 else ''
#         )
#         cards_html += (
#             f'<div class="wf-file-card">'
#             f'<span style="font-size:1.1rem;">📦</span>'
#             f'<span class="wf-filename">{uf.name}</span>'
#             f'{db_info}{badge}'
#             f'</div>'
#         )
#     st.markdown(cards_html, unsafe_allow_html=True)

#     skip_loaded = st.checkbox('Lewati file yang sudah dimuat', value=True, key='crewdible_skip')
#     to_process = [item for item in file_infos
#                   if not (skip_loaded and item[3] == 'fully_loaded')]
#     skipped_count = len(file_infos) - len(to_process)

#     st.markdown('<hr>', unsafe_allow_html=True)
#     col_info, col_btn = st.columns([4, 1])
#     with col_info:
#         if not to_process:
#             st.success('Semua file sudah dimuat. Tidak ada yang perlu diproses.')
#         elif skipped_count > 0:
#             st.caption(f'{skipped_count} file dilewati · **{len(to_process)} file akan diproses**')
#         else:
#             st.caption(f'**{len(to_process)} file akan diproses**')
#     with col_btn:
#         run_button = st.button(
#             f'▶  Proses  {len(to_process)}  File',
#             type='primary',
#             use_container_width=True,
#             disabled=(not to_process),
#             key='crewdible_run',
#         )

#     if not to_process or not run_button:
#         return

#     st.session_state['log_lines'] = []
#     st.markdown('<div class="wf-section-title">Progress</div>', unsafe_allow_html=True)
#     progress_bar  = st.progress(0, text='Memulai…')
#     log_container = st.empty()
#     total, errors = len(to_process), []

#     for idx, (uf, tmp_path, _, _) in enumerate(to_process):
#         progress_bar.progress(idx / total, text=f'({idx+1}/{total})  {uf.name}')
#         try:
#             process_crewdible_file(tmp_path, engine)
#         except Exception as e:
#             logging.getLogger().error(f'GAGAL memproses {uf.name}: {e}')
#             errors.append(uf.name)

#         log_lines = st.session_state.get('log_lines', [])
#         log_container.text_area('Log', value='\n'.join(log_lines[-200:]),
#                                 height=280, key=f'crewdible_log_{idx}',
#                                 label_visibility='collapsed')

#     progress_bar.progress(1.0, text='Selesai!')
#     st.markdown('<hr>', unsafe_allow_html=True)

#     sukses = total - len(errors)
#     if errors:
#         st.error(f'**Proses selesai dengan {len(errors)} error.**  \n'
#                  + '  \n'.join(f'• `{f}`' for f in errors))
#     else:
#         st.success(f'**Berhasil!** {total} file diproses tanpa error.')

#     if sukses > 0:
#         threading.Thread(
#             target=_run_crewdible_transform_background,
#             args=(engine,),
#             daemon=True,
#         ).start()
#         st.info(f'🔄 Transform Crewdible berjalan di background ({sukses} file berhasil dimuat). Notifikasi dikirim via Telegram setelah selesai.')

#     final_logs = st.session_state.get('log_lines', [])
#     if final_logs:
#         with st.expander('📋 Lihat Log Lengkap', expanded=False):
#             st.code('\n'.join(final_logs), language=None)


# ── Tab 3: Penjualan Offline ───────────────────────────────────────────────────
import datetime

DO_TYPES         = ['', 'DISTRIBUTOR', 'KONSIYANSI', 'AGEN', 'AGEN-B', 'COSTUMER',
                    'SAMPLE', 'GUDANG', 'GUDANG/PENITIPAN', 'PAMERAN', 'KEGIATAN SOSIAL']
PAYMENT_STATUSES = ['', 'Lunas', 'Belum Lunas']
CHANNELS_DO      = ['', 'Offline', 'Online']


def _date_to_id(d):
    if d is None:
        return None
    return int(d.strftime('%Y%m%d'))


def _id_to_date(n):
    if not n:
        return None
    s = str(int(n))
    try:
        return datetime.date(int(s[:4]), int(s[4:6]), int(s[6:8]))
    except Exception:
        return None


def _or_none(v):
    if v is None or v == '' or v == 0:
        return None
    return v


def _empty_do_item():
    return {'sku': '', 'product_name_raw': '', 'qty': 0,
            'unit_price': 0.0, 'total_price': 0.0, 'total_price_after_discount': 0.0}


@st.cache_data(ttl=600)
def load_b2b_partners_do(_engine):
    with _engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT partner_id, nama, partner_type FROM public.dim_b2b_partner "
            "WHERE nama IS NOT NULL ORDER BY nama"
        )).fetchall()
    opts    = [''] + [f"{r.nama} ({r.partner_type})" for r in rows]
    mapping = {f"{r.nama} ({r.partner_type})": (r.partner_id, r.nama) for r in rows}
    return opts, mapping


@st.cache_data(ttl=600)
def load_warehouses_do(_engine):
    with _engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT warehouse_id, warehouse_name FROM public.dim_warehouse ORDER BY warehouse_name"
        )).fetchall()
    opts    = [''] + [r.warehouse_name for r in rows]
    mapping = {r.warehouse_name: r.warehouse_id for r in rows}
    return opts, mapping


@st.cache_data(ttl=600)
def load_geographies_do(_engine):
    with _engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT DISTINCT ON (city_regency) geography_id, city_regency "
            "FROM public.dim_geography WHERE city_regency IS NOT NULL "
            "ORDER BY city_regency, geography_id"
        )).fetchall()
    opts     = [''] + [r.city_regency for r in rows]
    mapping  = {r.city_regency: r.geography_id for r in rows}
    reverse  = {r.geography_id: r.city_regency for r in rows}
    return opts, mapping, reverse


@st.cache_data(ttl=600)
def load_products_do(_engine):
    with _engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT product_id, sku_code, product_name FROM public.dim_product "
            "WHERE sku_code IS NOT NULL AND sku_code != '-' ORDER BY product_name"
        )).fetchall()
    sku_opts = [''] + [r.sku_code for r in rows]
    sku_map  = {r.sku_code: (r.product_id, r.product_name) for r in rows}
    return sku_opts, sku_map


@st.cache_data(ttl=60)
def load_do_list(_engine):
    with _engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT do_number, customer_name, do_date_id "
            "FROM public.fact_do_header ORDER BY do_id DESC"
        )).fetchall()
    return rows


def _fetch_do_for_edit(do_number, engine):
    with engine.connect() as conn:
        h = conn.execute(
            text("SELECT * FROM public.fact_do_header WHERE do_number = :dn"),
            {'dn': do_number}
        ).mappings().fetchone()
        its = conn.execute(
            text("SELECT i.* FROM public.fact_do_item i "
                 "JOIN public.fact_do_header h ON h.do_id = i.do_id "
                 "WHERE h.do_number = :dn ORDER BY i.item_id"),
            {'dn': do_number}
        ).mappings().fetchall()
    return (dict(h) if h else None), [dict(i) for i in its]


def _save_do_to_db(do_number, header, items, engine, is_edit):
    source_filename = f"streamlit:{do_number}" if do_number else "streamlit:manual"
    with engine.begin() as conn:
        if is_edit:
            conn.execute(text(
                "DELETE FROM public.fact_do_item WHERE do_id IN "
                "(SELECT do_id FROM public.fact_do_header WHERE do_number = :dn)"
            ), {'dn': do_number})
            conn.execute(text(
                "DELETE FROM public.fact_do_header WHERE do_number = :dn"
            ), {'dn': do_number})

        result = conn.execute(text("""
            INSERT INTO public.fact_do_header
                (do_number, po_date_id, po_number, do_date_id,
                 customer_name, b2b_partner_id, do_type, channel,
                 courier_raw, warehouse_raw, warehouse_id,
                 invoice_date_id, invoice_number, invoice_amount,
                 shipping_cost, discount, due_date_id,
                 payment_amount, payment_date_id, payment_status,
                 total_bill, box_count, region_raw, geography_id,
                 return_notes, source_filename)
            VALUES
                (:do_number, :po_date_id, :po_number, :do_date_id,
                 :customer_name, :b2b_partner_id, :do_type, :channel,
                 :courier_raw, :warehouse_raw, :warehouse_id,
                 :invoice_date_id, :invoice_number, :invoice_amount,
                 :shipping_cost, :discount, :due_date_id,
                 :payment_amount, :payment_date_id, :payment_status,
                 :total_bill, :box_count, :region_raw, :geography_id,
                 :return_notes, :source_filename)
            RETURNING do_id
        """), {**header, 'source_filename': source_filename})
        do_id = result.scalar()

        for item in items:
            sku = item.get('sku', '').strip()
            if not sku:
                continue
            conn.execute(text("""
                INSERT INTO public.fact_do_item
                    (do_id, do_number, sku, product_id, product_name_raw,
                     qty, unit_price, total_price,
                     total_price_after_discount, source_filename)
                VALUES
                    (:do_id, :do_number, :sku, :product_id, :product_name_raw,
                     :qty, :unit_price, :total_price,
                     :total_price_after_discount, :source_filename)
            """), {
                'do_id':                     do_id,
                'do_number':                 do_number,
                'sku':                       sku,
                'product_id':                item.get('product_id'),
                'product_name_raw':          item.get('product_name_raw') or None,
                'qty':                       _or_none(item.get('qty')),
                'unit_price':                _or_none(item.get('unit_price')),
                'total_price':               _or_none(item.get('total_price')),
                'total_price_after_discount':_or_none(item.get('total_price_after_discount')),
                'source_filename':           source_filename,
            })
    return do_id


def render_sales_offline_tab(engine):
    partner_opts, partner_map  = load_b2b_partners_do(engine)
    warehouse_opts, wh_map     = load_warehouses_do(engine)
    geo_opts, geo_map, geo_rev = load_geographies_do(engine)
    sku_opts, sku_map          = load_products_do(engine)

    if 'so_items' not in st.session_state:
        st.session_state.so_items = [_empty_do_item()]

    # ── Mode selector ────────────────────────────────────────────────────────
    mode = st.radio('Mode', ['Input Baru', 'Edit DO'], horizontal=True, key='so_mode')

    if mode == 'Edit DO':
        do_list  = load_do_list(engine)
        do_labels = [f"{r.do_number}  —  {r.customer_name or ''}  ({r.do_date_id or ''})"
                     for r in do_list]
        sel_label = st.selectbox('Pilih DO yang akan diedit', [''] + do_labels, key='so_edit_sel')

        if sel_label and st.button('Muat Data', key='so_load'):
            do_num_edit = sel_label.split('  —  ')[0].strip()
            header_db, items_db = _fetch_do_for_edit(do_num_edit, engine)
            if header_db:
                ss = st.session_state
                ss['so_do_number']  = header_db.get('do_number', '')
                ss['so_po_number']  = header_db.get('po_number', '') or ''
                ss['so_do_date']    = _id_to_date(header_db.get('do_date_id'))
                ss['so_po_date']    = _id_to_date(header_db.get('po_date_id'))
                ss['so_do_type']    = header_db.get('do_type', '') or ''
                ss['so_channel']    = header_db.get('channel', '') or ''
                ss['so_courier']    = header_db.get('courier_raw', '') or ''
                ss['so_wh']         = header_db.get('warehouse_raw', '') or ''
                ss['so_geo']        = geo_rev.get(header_db.get('geography_id', ''), '')
                ss['so_inv_number'] = header_db.get('invoice_number', '') or ''
                ss['so_inv_date']   = _id_to_date(header_db.get('invoice_date_id'))
                ss['so_inv_amount'] = float(header_db['invoice_amount']) if header_db.get('invoice_amount') else 0.0
                ss['so_shipping']   = float(header_db['shipping_cost'])  if header_db.get('shipping_cost')  else 0.0
                ss['so_discount']   = float(header_db['discount'])       if header_db.get('discount')       else 0.0
                ss['so_total_bill'] = float(header_db['total_bill'])     if header_db.get('total_bill')     else 0.0
                ss['so_due_date']   = _id_to_date(header_db.get('due_date_id'))
                ss['so_pay_amount'] = float(header_db['payment_amount']) if header_db.get('payment_amount') else 0.0
                ss['so_pay_date']   = _id_to_date(header_db.get('payment_date_id'))
                ss['so_pay_status'] = header_db.get('payment_status', '') or ''
                ss['so_box_count']  = int(header_db['box_count']) if header_db.get('box_count') else 0
                ss['so_notes']      = header_db.get('return_notes', '') or ''

                # Partner selectbox: cari label yang cocok dengan customer_name
                cname = (header_db.get('customer_name', '') or '').strip()
                matched = next((lbl for lbl, (_, nama) in partner_map.items()
                                if nama.strip() == cname), '')
                ss['so_partner'] = matched

                # Items
                ss.so_items = []
                for it in items_db:
                    sku = it.get('sku', '') or ''
                    _, pname = sku_map.get(sku, (None, it.get('product_name_raw', '') or ''))
                    ss.so_items.append({
                        'sku':                       sku,
                        'product_name_raw':          pname,
                        'qty':                       int(it['qty']) if it.get('qty') else 0,
                        'unit_price':                float(it['unit_price']) if it.get('unit_price') else 0.0,
                        'total_price':               float(it['total_price']) if it.get('total_price') else 0.0,
                        'total_price_after_discount':float(it['total_price_after_discount']) if it.get('total_price_after_discount') else 0.0,
                    })
                if not ss.so_items:
                    ss.so_items = [_empty_do_item()]
                st.rerun()

        st.divider()

    # ── Header DO ────────────────────────────────────────────────────────────
    st.markdown('<div class="wf-section-title">Header DO</div>', unsafe_allow_html=True)

    c1, c2, c3 = st.columns(3)
    with c1:
        do_number  = st.text_input('No. DO', key='so_do_number')
        do_date    = st.date_input('Tanggal DO', value=None, key='so_do_date')
        do_type    = st.selectbox('Tipe DO', DO_TYPES, key='so_do_type')
    with c2:
        po_number  = st.text_input('No. PO', key='so_po_number')
        po_date    = st.date_input('Tanggal PO', value=None, key='so_po_date')
        partner    = st.selectbox('Customer', partner_opts, key='so_partner')
    with c3:
        wh_sel     = st.selectbox('Gudang', warehouse_opts, key='so_wh')
        channel    = st.selectbox('Channel', CHANNELS_DO, key='so_channel')
        courier    = st.text_input('Ekspedisi', key='so_courier')

    c4, c5, c6 = st.columns(3)
    with c4:
        geo_sel    = st.selectbox('Wilayah', geo_opts, key='so_geo')
        box_count  = st.number_input('Jumlah Box', min_value=0, step=1, value=0, key='so_box_count')
    with c5:
        inv_number = st.text_input('No. Invoice', key='so_inv_number')
        inv_date   = st.date_input('Tanggal Invoice', value=None, key='so_inv_date')
        inv_amount = st.number_input('Nominal Invoice (Rp)', min_value=0.0, step=1000.0, value=0.0, format='%.0f', key='so_inv_amount')
    with c6:
        shipping   = st.number_input('Ongkir (Rp)', min_value=0.0, step=1000.0, value=0.0, format='%.0f', key='so_shipping')
        discount   = st.number_input('Diskon (Rp)', min_value=0.0, step=1000.0, value=0.0, format='%.0f', key='so_discount')
        total_bill = st.number_input('Total Tagihan (Rp)', min_value=0.0, step=1000.0, value=0.0, format='%.0f', key='so_total_bill')

    c7, c8, c9 = st.columns(3)
    with c7:
        due_date   = st.date_input('Jatuh Tempo', value=None, key='so_due_date')
    with c8:
        pay_amount = st.number_input('Nominal Payment (Rp)', min_value=0.0, step=1000.0, value=0.0, format='%.0f', key='so_pay_amount')
        pay_date   = st.date_input('Tanggal Payment', value=None, key='so_pay_date')
    with c9:
        pay_status = st.selectbox('Status Bayar', PAYMENT_STATUSES, key='so_pay_status')

    return_notes = st.text_area('Catatan Retur / Lepas Vacuum', key='so_notes')

    # ── Item DO ──────────────────────────────────────────────────────────────
    st.markdown('<div class="wf-section-title">Item DO</div>', unsafe_allow_html=True)

    edited = st.data_editor(
        st.session_state.so_items,
        num_rows='dynamic',
        use_container_width=True,
        column_config={
            'sku': st.column_config.SelectboxColumn(
                'SKU', options=sku_opts, required=False, width='medium'),
            'product_name_raw': st.column_config.TextColumn(
                'Nama Produk', disabled=True, width='large'),
            'qty': st.column_config.NumberColumn(
                'Qty', min_value=0, step=1, format='%d'),
            'unit_price': st.column_config.NumberColumn(
                'Harga Satuan', min_value=0.0, step=1000.0, format='%.0f'),
            'total_price': st.column_config.NumberColumn(
                'Total Harga', min_value=0.0, step=1000.0, format='%.0f'),
            'total_price_after_discount': st.column_config.NumberColumn(
                'Total Stlh Diskon', min_value=0.0, step=1000.0, format='%.0f'),
        },
        key='so_data_editor',
    )

    # Auto-fill product_name_raw & product_id from SKU, auto-calc total_price
    resolved_items = []
    for row in edited:
        sku = (row.get('sku', '') or '').strip()
        if sku and sku in sku_map:
            pid, pname = sku_map[sku]
            row['product_id']       = pid
            row['product_name_raw'] = pname
        else:
            row['product_id'] = None
        qty = row.get('qty') or 0
        up  = row.get('unit_price') or 0.0
        if qty and up and not row.get('total_price'):
            row['total_price'] = qty * up
        resolved_items.append(row)
    st.session_state.so_items = resolved_items

    # ── Simpan / Reset ───────────────────────────────────────────────────────
    st.divider()
    col_save, col_reset, _ = st.columns([1, 1, 4])
    with col_save:
        save_btn = st.button('💾  Simpan DO', type='primary',
                             use_container_width=True, key='so_save')
    with col_reset:
        if st.button('🔄  Reset Form', use_container_width=True, key='so_reset'):
            for k in [k for k in st.session_state if k.startswith('so_')]:
                del st.session_state[k]
            st.rerun()

    if not save_btn:
        return

    p_id, p_nama = partner_map.get(partner, (None, partner.split(' (')[0] if partner else None))
    header = {
        'do_number':      _or_none(do_number),
        'po_date_id':     _date_to_id(po_date),
        'po_number':      _or_none(po_number),
        'do_date_id':     _date_to_id(do_date),
        'customer_name':  p_nama,
        'b2b_partner_id': p_id,
        'do_type':        _or_none(do_type),
        'channel':        _or_none(channel),
        'courier_raw':    _or_none(courier),
        'warehouse_raw':  _or_none(wh_sel),
        'warehouse_id':   wh_map.get(wh_sel),
        'invoice_date_id':_date_to_id(inv_date),
        'invoice_number': _or_none(inv_number),
        'invoice_amount': _or_none(inv_amount),
        'shipping_cost':  _or_none(shipping),
        'discount':       _or_none(discount),
        'due_date_id':    _date_to_id(due_date),
        'payment_amount': _or_none(pay_amount),
        'payment_date_id':_date_to_id(pay_date),
        'payment_status': _or_none(pay_status),
        'total_bill':     _or_none(total_bill),
        'box_count':      _or_none(box_count),
        'region_raw':     _or_none(geo_sel),
        'geography_id':   geo_map.get(geo_sel),
        'return_notes':   _or_none(return_notes),
    }

    is_edit = (mode == 'Edit DO')
    try:
        do_id = _save_do_to_db(do_number, header, resolved_items, engine, is_edit)
        action = 'diperbarui' if is_edit else 'disimpan'
        st.success(f'DO **{do_number}** berhasil {action}. (do_id: {do_id})')
        load_do_list.clear()
        if not is_edit:
            for k in [k for k in st.session_state if k.startswith('so_')]:
                del st.session_state[k]
            st.rerun()
    except Exception as e:
        st.error(f'Gagal menyimpan: {e}')


# ── Tab 4: Monitoring ──────────────────────────────────────────────────────────
def render_monitoring_tab(engine):
    col_title, col_refresh = st.columns([6, 1])
    with col_title:
        st.markdown('#### Ringkasan Data di Database')
    with col_refresh:
        if st.button('🔄 Refresh', use_container_width=True):
            load_staging_summary.clear()
            load_timeseries.clear()
            st.rerun()

    with st.spinner('Memuat data dari database…'):
        df    = load_staging_summary(engine)
        df_ts = load_timeseries(engine)

    if df.empty:
        st.info('Belum ada data di database staging.')
        return

    # Summary matrix
    st.markdown('<div class="wf-section-title">Total Baris per Marketplace & Fase</div>', unsafe_allow_html=True)
    pivot = df.groupby(['Marketplace', 'Fase'])['Baris'].sum().reset_index()
    pivot_wide = pivot.pivot(index='Marketplace', columns='Fase', values='Baris').fillna(0).astype(int)
    for col in ['ORDER', 'INCOME', 'REPORT']:
        if col not in pivot_wide.columns:
            pivot_wide[col] = 0
    pivot_wide = pivot_wide[['ORDER', 'INCOME', 'REPORT']]
    pivot_wide['Total'] = pivot_wide.sum(axis=1)
    st.dataframe(pivot_wide.style.format('{:,}'), use_container_width=True)

    st.markdown('<br>', unsafe_allow_html=True)

    # Time-series chart
    if not df_ts.empty:
        st.markdown('<div class="wf-section-title">Riwayat Upload per Hari</div>',
                    unsafe_allow_html=True)

        col_f1, col_f2, _ = st.columns([2, 2, 4])
        with col_f1:
            mp_filter   = st.selectbox('Marketplace', ['Semua'] + sorted(df_ts['Marketplace'].unique()), key='ts_mp')
        with col_f2:
            fase_filter = st.selectbox('Fase', ['Semua'] + sorted(df_ts['Fase'].unique()), key='ts_fase')

        df_chart = df_ts.copy()
        if mp_filter   != 'Semua': df_chart = df_chart[df_chart['Marketplace'] == mp_filter]
        if fase_filter != 'Semua': df_chart = df_chart[df_chart['Fase'] == fase_filter]

        if not df_chart.empty:
            domain = sorted(df_chart['Marketplace'].unique().tolist())
            chart = (
                alt.Chart(df_chart)
                .mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3)
                .encode(
                    x=alt.X('Tanggal:T', title='Tanggal Upload', axis=alt.Axis(format='%d %b %Y')),
                    y=alt.Y('Baris:Q', title='Jumlah Baris'),
                    color=alt.Color('Marketplace:N',
                                    scale=alt.Scale(domain=domain,
                                                    range=[MP_COLORS.get(d, '#888') for d in domain])),
                    tooltip=[
                        alt.Tooltip('Tanggal:T', format='%d %b %Y'),
                        'Marketplace:N', 'Fase:N',
                        alt.Tooltip('Baris:Q', format=','),
                    ],
                )
                .properties(height=300)
                .facet(column=alt.Column('Fase:N', title=None))
                .resolve_scale(y='independent')
            )
            st.altair_chart(chart, use_container_width=True)

    # Detail per file
    st.markdown('<div class="wf-section-title">Detail Per File</div>', unsafe_allow_html=True)

    col1, col2, col3 = st.columns(3)
    with col1:
        f_mp     = st.selectbox('Marketplace', ['Semua'] + sorted(df['Marketplace'].unique()), key='detail_mp')
    with col2:
        f_fase   = st.selectbox('Fase', ['Semua'] + sorted(df['Fase'].unique()), key='detail_fase')
    with col3:
        f_search = st.text_input('Cari nama file', placeholder='ketik untuk filter…', key='detail_search')

    df_filtered = df.copy()
    if f_mp     != 'Semua': df_filtered = df_filtered[df_filtered['Marketplace'] == f_mp]
    if f_fase   != 'Semua': df_filtered = df_filtered[df_filtered['Fase'] == f_fase]
    if f_search:
        df_filtered = df_filtered[df_filtered['File'].str.contains(f_search, case=False, na=False)]

    st.caption(f"{len(df_filtered)} file · {df_filtered['Baris'].sum():,} baris total")
    st.dataframe(
        df_filtered[['Marketplace', 'Fase', 'File', 'Baris', 'Pertama Upload', 'Terakhir Upload']]
        .reset_index(drop=True)
        .style.format({'Baris': '{:,}'}),
        use_container_width=True,
        height=420,
    )


# ── Tab 5: Konfigurasi ────────────────────────────────────────────────────────

@st.cache_data(ttl=60)
def load_config(_engine):
    with _engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT key, value, description FROM public.dim_config ORDER BY key"
        )).fetchall()
    return {r.key: {'value': float(r.value), 'description': r.description} for r in rows}


def _refresh_buffer_mvs(engine):
    with engine.begin() as conn:
        conn.execute(text("REFRESH MATERIALIZED VIEW public.mv_production_buffer"))
        conn.execute(text("REFRESH MATERIALIZED VIEW public.mv_distribution_buffer"))


def render_config_tab(engine):
    st.markdown('#### Konfigurasi Parameter Sistem')
    st.markdown(
        '<div class="wf-context-card">'
        'Parameter di halaman ini mempengaruhi kalkulasi <strong>buffer harian</strong> '
        'untuk tim Produksi dan Distribusi. Perubahan akan langsung tersimpan ke database '
        'dan materialized view buffer akan di-refresh otomatis.'
        '</div>',
        unsafe_allow_html=True,
    )

    cfg = load_config(engine)

    # ── Buffer Multiplier ────────────────────────────────────────────────────
    st.markdown('<div class="wf-section-title">Buffer Harian</div>', unsafe_allow_html=True)

    current_multiplier = cfg.get('buffer_multiplier', {}).get('value', 10)

    col_desc, col_form = st.columns([2, 1])
    with col_desc:
        st.markdown(f"""
**Buffer Multiplier** saat ini: **`{int(current_multiplier)}`**

Formula buffer:
- **Tim Produksi (kg):** Total penjualan kemarin (kg) × multiplier
- **Tim Distribusi (pcs):** Penjualan per toko kemarin (pcs) × multiplier

Nilai ini menentukan berapa hari stok cadangan yang harus disiapkan berdasarkan penjualan hari terakhir.
        """)
    with col_form:
        with st.form('form_buffer_multiplier'):
            new_multiplier = st.number_input(
                'Nilai Baru',
                min_value=1,
                max_value=365,
                value=int(current_multiplier),
                step=1,
                help='Angka hari cadangan. Default: 10',
            )
            submitted = st.form_submit_button('💾  Simpan & Refresh', use_container_width=True, type='primary')

        if submitted:
            try:
                with engine.begin() as conn:
                    conn.execute(text(
                        "UPDATE public.dim_config SET value = :val WHERE key = 'buffer_multiplier'"
                    ), {'val': new_multiplier})
                with st.spinner('Refresh materialized view buffer…'):
                    _refresh_buffer_mvs(engine)
                load_config.clear()
                st.success(f'Buffer multiplier diperbarui menjadi **{new_multiplier}**. MV buffer sudah di-refresh.')
                st.rerun()
            except Exception as e:
                st.error(f'Gagal menyimpan: {e}')


# ── Tab 6: Master Partner ─────────────────────────────────────────────────────

PARTNER_TYPES = ['AGEN', 'DISTRIBUTOR', 'KONSIYANSI', 'COSTUMER', 'SAMPLE']


@st.cache_data(ttl=60)
def load_all_partners(_engine):
    with _engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT partner_id, nama, partner_type, wilayah, join_date_id "
            "FROM public.dim_b2b_partner ORDER BY nama"
        )).fetchall()
    return rows


def render_master_partner_tab(engine):
    st.markdown('#### Data Partner B2B')

    if st.button('🔄 Refresh', key='mp_refresh'):
        load_all_partners.clear()
        st.rerun()

    # ── Tambah Partner Baru ──────────────────────────────────────────────────
    with st.expander('➕ Tambah Partner Baru', expanded=False):
        with st.form('form_tambah_partner', clear_on_submit=True):
            c1, c2 = st.columns(2)
            with c1:
                p_nama         = st.text_input('Nama Partner *')
                p_type         = st.selectbox('Tipe Partner *', PARTNER_TYPES)
                p_wilayah      = st.text_input('Wilayah')
            with c2:
                p_join_date    = st.date_input('Tanggal Bergabung *', value=None)
                p_company      = st.text_input('Nama Perusahaan')
                p_contact      = st.text_input('Nama Kontak')

            submitted = st.form_submit_button('Simpan Partner', use_container_width=True)
            if submitted:
                if not p_nama or not p_type or not p_join_date:
                    st.error('Nama Partner, Tipe, dan Tanggal Bergabung wajib diisi.')
                else:
                    join_date_id = _date_to_id(p_join_date)
                    try:
                        with engine.begin() as conn:
                            conn.execute(text('''
                                INSERT INTO public.dim_b2b_partner
                                    (nama, partner_type, wilayah, join_date_id, company_name, contact_name)
                                VALUES
                                    (:nama, :partner_type, :wilayah, :join_date_id, :company_name, :contact_name)
                            '''), {
                                'nama':         p_nama.strip(),
                                'partner_type': p_type,
                                'wilayah':      _or_none(p_wilayah),
                                'join_date_id': join_date_id,
                                'company_name': _or_none(p_company),
                                'contact_name': _or_none(p_contact),
                            })
                        st.success(f'Partner "{p_nama}" berhasil ditambahkan.')
                        load_all_partners.clear()
                        load_b2b_partners_do.clear()
                        st.rerun()
                    except Exception as e:
                        st.error(f'Gagal menyimpan: {e}')

    # ── Update Join Date Partner Lama ────────────────────────────────────────
    with st.expander('✏️ Update Tanggal Bergabung Partner Lama', expanded=False):
        partners = load_all_partners(engine)
        no_date  = [r for r in partners if not r.join_date_id]

        if not no_date:
            st.success('Semua partner sudah memiliki tanggal bergabung.')
        else:
            st.caption(f'{len(no_date)} partner belum memiliki tanggal bergabung.')
            with st.form('form_update_join_date'):
                opts    = {f"{r.nama} ({r.partner_type})": r.partner_id for r in no_date}
                sel     = st.selectbox('Pilih Partner', list(opts.keys()))
                new_date = st.date_input('Tanggal Bergabung', value=None, key='upd_join_date')
                if st.form_submit_button('Update', use_container_width=True):
                    if not new_date:
                        st.error('Tanggal bergabung wajib diisi.')
                    else:
                        try:
                            with engine.begin() as conn:
                                conn.execute(text(
                                    'UPDATE public.dim_b2b_partner SET join_date_id = :jd '
                                    'WHERE partner_id = :pid'
                                ), {'jd': _date_to_id(new_date), 'pid': opts[sel]})
                            st.success(f'Tanggal bergabung "{sel}" berhasil diupdate.')
                            load_all_partners.clear()
                            st.rerun()
                        except Exception as e:
                            st.error(f'Gagal update: {e}')

    # ── Tabel Partner ────────────────────────────────────────────────────────
    st.markdown('<div class="wf-section-title">Daftar Partner</div>', unsafe_allow_html=True)

    partners = load_all_partners(engine)
    df_partners = pd.DataFrame([{
        'Nama':               r.nama,
        'Tipe':               r.partner_type,
        'Wilayah':            r.wilayah or '-',
        'Tanggal Bergabung':  str(_id_to_date(r.join_date_id)) if r.join_date_id else '-',
    } for r in partners])

    f1, f2 = st.columns(2)
    with f1:
        f_type = st.selectbox('Filter Tipe', ['Semua'] + PARTNER_TYPES, key='mp_ftype')
    with f2:
        f_search = st.text_input('Cari nama', placeholder='ketik untuk filter…', key='mp_search')

    if f_type != 'Semua':
        df_partners = df_partners[df_partners['Tipe'] == f_type]
    if f_search:
        df_partners = df_partners[df_partners['Nama'].str.contains(f_search, case=False, na=False)]

    st.caption(f'{len(df_partners)} partner')
    st.dataframe(df_partners.reset_index(drop=True), use_container_width=True, height=400)


# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    attach_streamlit_handler()

    st.markdown("""
    <div class="wf-header">
        <h1>🌾 Wellfarm Data Hub</h1>
        <p>Upload dan pantau data dari Shopee, TikTok/Tokopedia, dan Lazada.</p>
    </div>
    """, unsafe_allow_html=True)

    try:
        engine = get_db_engine()
    except Exception as e:
        st.error(f'Gagal terhubung ke database: {e}')
        return

    with st.sidebar:
        st.markdown(
            """
            <div class="wf-sidebar-brand">
                <div class="wf-sidebar-brand-title">Wellfarm Data Hub</div>
                <div class="wf-sidebar-brand-subtitle">Panel internal untuk upload data dan pengaturan sistem.</div>
            </div>
            <div class="wf-sidebar-label">Navigasi</div>
            """,
            unsafe_allow_html=True,
        )
        page = st.radio(
            'Halaman',
            [
                '📤 Upload Data Sales Online',
                '⚙️ Konfigurasi',
            ],
            label_visibility='collapsed',
        )
        st.markdown('<div class="wf-sidebar-label">Tampilan</div>', unsafe_allow_html=True)
        dark_theme = st.toggle('Mode gelap', key='wf_dark_theme')
        st.markdown(
            '<div class="wf-sidebar-note">Pilih halaman dari menu ini. Pengaturan kerja tersedia di halaman masing-masing.</div>',
            unsafe_allow_html=True,
        )

    if dark_theme:
        inject_dark_theme_styles()

    if page == '📤 Upload Data Sales Online':
        render_upload_tab(engine)
    elif page == '⚙️ Konfigurasi':
        render_config_tab(engine)


if __name__ == '__main__':
    main()
