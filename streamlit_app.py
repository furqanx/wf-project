"""streamlit_app.py — Wellfarm Data Hub
Upload file staging + monitoring data per marketplace.
"""

import logging
import os
import sys
import tempfile
import threading
import pandas as pd
import altair as alt
import streamlit as st
from sqlalchemy import text

sys.path.insert(0, os.path.dirname(__file__))

from src.db_config import get_engine
from src.file_inspector import check_file_status, check_duplicate_order_ids
from src.extract_loader import process_order_file, process_income_file, process_report_file
from src.transform.runner import run as run_transform

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
hr { border: none; border-top: 1px solid #e2e8f0; margin: 20px 0; }
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


# ── Log Handler ────────────────────────────────────────────────────────────────
class StreamlitLogHandler(logging.Handler):
    def emit(self, record):
        st.session_state.setdefault('log_lines', []).append(self.format(record))


def attach_streamlit_handler():
    root = logging.getLogger()
    if any(isinstance(h, StreamlitLogHandler) for h in root.handlers):
        return
    h = StreamlitLogHandler()
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


# ── Tab 1: Upload ──────────────────────────────────────────────────────────────
def render_upload_tab(engine):
    with st.sidebar:
        st.markdown('### ⚙️ Pengaturan Upload')
        st.markdown('---')
        fase = st.selectbox('Fase Data', FASE_OPTIONS, index=0,
                            help='Pilih jenis data yang akan diunggah.')
        st.caption(f'_{FASE_DESC.get(fase, "")}_')
        st.markdown(' ')
        marketplace_label = st.selectbox('Marketplace', list(MARKETPLACE_OPTIONS.keys()), index=0)
        marketplace = MARKETPLACE_OPTIONS[marketplace_label]
        st.markdown(' ')
        stores = load_stores(engine, MARKETPLACE_ID[marketplace])
        toko = st.selectbox('Toko', stores, help='Pilih toko asal file ini.')
        st.markdown(' ')
        skip_loaded = st.checkbox('Lewati file yang sudah dimuat penuh', value=True)
        st.markdown('---')
        st.markdown(
            f"<div style='font-size:0.78rem;color:#64748b;'>"
            f"<b>Target</b><br>"
            f"{MARKETPLACE_ICON.get(marketplace_label,'')} {marketplace_label} &mdash; {fase}"
            f"</div>",
            unsafe_allow_html=True,
        )

    st.markdown(
        f'<div class="wf-context-card">'
        f'Upload file <strong>{fase}</strong> dari '
        f'<strong>{MARKETPLACE_ICON.get(marketplace_label,"")} {marketplace_label}</strong>'
        f' &mdash; Toko: <strong>{toko}</strong>. '
        f'Pastikan file sudah sesuai sebelum menekan tombol proses.'
        f'</div>',
        unsafe_allow_html=True,
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

    st.markdown(f'<div class="wf-section-title">Ringkasan — {len(file_statuses)} file</div>',
                unsafe_allow_html=True)
    st.markdown(render_stat_row(counts), unsafe_allow_html=True)

    st.markdown('<div class="wf-section-title">Detail Status Per File</div>', unsafe_allow_html=True)
    st.markdown(
        ''.join(render_file_card(uf.name, s['status'], s['rows_in_db'], s['rows_in_file'])
                for uf, s, _ in file_statuses),
        unsafe_allow_html=True,
    )

    # ── Cek duplikasi order ID ──────────────────────────────────────────────────
    st.markdown('<div class="wf-section-title">Cek Duplikasi Order ID</div>', unsafe_allow_html=True)
    dup_results = {}
    with st.spinner('Memeriksa duplikasi order ID...'):
        for uf, _, tmp_path in file_statuses:
            dup = check_duplicate_order_ids(tmp_path, fase, marketplace, engine)
            dup_results[uf.name] = dup

    has_duplicates = any(d['already_in_db'] > 0 for d in dup_results.values())
    for fname, dup in dup_results.items():
        if dup['total_in_file'] == 0:
            continue
        if dup['already_in_db'] > 0:
            st.warning(
                f"**{fname}** — "
                f"{dup['already_in_db']} dari {dup['total_in_file']} order ID sudah ada di database. "
                f"({dup['new']} baru)"
            )
            if dup['duplicate_ids']:
                with st.expander(f"Lihat sample duplikat ({fname})"):
                    st.code('\n'.join(dup['duplicate_ids']))
        else:
            st.success(f"**{fname}** — Semua {dup['total_in_file']} order ID baru.")

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
    col_info, col_btn = st.columns([4, 1])
    with col_info:
        if not to_process:
            st.success('Semua file sudah dimuat penuh. Tidak ada yang perlu diproses.')
        elif skipped_count > 0:
            st.caption(f'{skipped_count} file dilewati · **{len(to_process)} file akan diproses**')
        else:
            st.caption(f'**{len(to_process)} file akan diproses**')
    with col_btn:
        run_button = st.button(
            f'▶  Proses  {len(to_process)}  File',
            type='primary',
            use_container_width=True,
            disabled=(not to_process),
        )

    if not to_process or not run_button:
        return

    st.session_state['log_lines'] = []
    st.markdown('<div class="wf-section-title">Progress</div>', unsafe_allow_html=True)
    progress_bar  = st.progress(0, text='Memulai…')
    log_container = st.empty()
    total, errors = len(to_process), []

    for idx, (uf, _, tmp_path) in enumerate(to_process):
        progress_bar.progress(idx / total, text=f'({idx+1}/{total})  {uf.name}')
        try:
            if fase == 'ORDER':
                process_order_file(tmp_path, marketplace, engine, nama_toko_override=toko)
            elif fase == 'INCOME':
                process_income_file(tmp_path, marketplace, engine, nama_toko_override=toko)
            elif fase == 'REPORT':
                process_report_file(tmp_path, marketplace, engine, nama_toko_override=toko)
        except Exception as e:
            logging.getLogger().error(f'GAGAL memproses {uf.name}: {e}')
            errors.append(uf.name)

        log_lines = st.session_state.get('log_lines', [])
        log_container.text_area('Log', value='\n'.join(log_lines[-200:]),
                                height=280, key=f'log_{idx}', label_visibility='collapsed')

    progress_bar.progress(1.0, text='Selesai!')
    st.markdown('<hr>', unsafe_allow_html=True)

    sukses = total - len(errors)
    if errors:
        st.error(f'**Proses selesai dengan {len(errors)} error.**  \n' + '  \n'.join(f'• `{f}`' for f in errors))
    else:
        st.success(f'**Berhasil!** {total} file diproses tanpa error.')

    if sukses > 0:
        load_staging_summary.clear()
        load_timeseries.clear()
        threading.Thread(
            target=_run_transform_background,
            args=(marketplace, engine),
            daemon=True,
        ).start()
        st.info(f'🔄 Transform berjalan di background ({sukses} file berhasil dimuat). Notifikasi dikirim via Telegram setelah selesai.')

    final_logs = st.session_state.get('log_lines', [])
    if final_logs:
        with st.expander('📋 Lihat Log Lengkap', expanded=False):
            st.code('\n'.join(final_logs), language=None)


# ── Tab 2: Monitoring ──────────────────────────────────────────────────────────
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
    st.markdown('<div class="wf-section-title">Total Baris per Marketplace & Fase</div>',
                unsafe_allow_html=True)
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

    tab1, tab2 = st.tabs(['📤  Upload Data', '📊  Status Data'])
    with tab1:
        render_upload_tab(engine)
    with tab2:
        render_monitoring_tab(engine)


if __name__ == '__main__':
    main()
