"""
streamlit_app.py

UI manual upload untuk klien — memuat file spreadsheet ke staging database.
Menampilkan status per file sebelum proses dimulai, dan log real-time saat proses berjalan.
"""

import logging
import os
import sys
import tempfile
import streamlit as st

sys.path.insert(0, os.path.dirname(__file__))

from src.db_config import get_engine
from src.file_inspector import check_file_status
from src.extract_loader import process_order_file, process_income_file, process_report_file

# ============================================================
# KONFIGURASI HALAMAN
# ============================================================
st.set_page_config(
    page_title="Wellfarm — Upload Data",
    page_icon="🌾",
    layout="wide",
)

# ============================================================
# CUSTOM CSS
# ============================================================
st.markdown("""
<style>
/* ── Font & warna dasar ── */
html, body, [class*="css"] {
    font-family: 'Inter', 'Segoe UI', sans-serif;
}

/* ── Header utama ── */
.wf-header {
    background: linear-gradient(135deg, #1a6b3a 0%, #2d9b5a 100%);
    border-radius: 16px;
    padding: 28px 36px;
    margin-bottom: 28px;
    color: white;
}
.wf-header h1 {
    margin: 0 0 6px 0;
    font-size: 2rem;
    font-weight: 700;
    letter-spacing: -0.5px;
}
.wf-header p {
    margin: 0;
    opacity: 0.85;
    font-size: 0.95rem;
}

/* ── Kartu konteks upload ── */
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
.wf-context-card strong {
    color: #1a6b3a;
}

/* ── Kartu status file ── */
.wf-file-card {
    background: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 10px;
    padding: 14px 18px;
    margin-bottom: 10px;
    display: flex;
    align-items: center;
    gap: 16px;
    transition: box-shadow 0.15s ease;
}
.wf-file-card:hover {
    box-shadow: 0 2px 8px rgba(0,0,0,0.07);
}
.wf-filename {
    flex: 1;
    font-size: 0.88rem;
    color: #1e293b;
    font-weight: 500;
    word-break: break-all;
}

/* ── Badge status ── */
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
.badge-new      { background: #dcfce7; color: #166534; }
.badge-loaded   { background: #d1fae5; color: #065f46; }
.badge-partial  { background: #fef9c3; color: #854d0e; }
.badge-anomaly  { background: #fee2e2; color: #991b1b; }
.badge-unknown  { background: #f1f5f9; color: #475569; }

/* ── Statistik ringkasan ── */
.wf-stat-row {
    display: flex;
    gap: 12px;
    margin: 18px 0;
    flex-wrap: wrap;
}
.wf-stat {
    flex: 1;
    min-width: 120px;
    background: #f8fafc;
    border: 1px solid #e2e8f0;
    border-radius: 10px;
    padding: 14px 18px;
    text-align: center;
}
.wf-stat .stat-num {
    font-size: 1.8rem;
    font-weight: 700;
    line-height: 1;
}
.wf-stat .stat-label {
    font-size: 0.75rem;
    color: #64748b;
    margin-top: 4px;
}
.stat-new     .stat-num { color: #16a34a; }
.stat-loaded  .stat-num { color: #059669; }
.stat-partial .stat-num { color: #d97706; }
.stat-anomaly .stat-num { color: #dc2626; }

/* ── Seksi judul ── */
.wf-section-title {
    font-size: 0.75rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: #94a3b8;
    margin: 24px 0 10px 0;
}

/* ── Tabel header log ── */
.wf-log-header {
    font-size: 0.75rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: #94a3b8;
    margin-bottom: 6px;
}

/* ── Sembunyikan elemen Streamlit bawaan yang mengganggu ── */
#MainMenu { visibility: hidden; }
footer    { visibility: hidden; }

/* ── Sidebar styling ── */
[data-testid="stSidebar"] {
    background: #f8fafc;
    border-right: 1px solid #e2e8f0;
}
[data-testid="stSidebar"] .stSelectbox label,
[data-testid="stSidebar"] .stCheckbox label {
    font-weight: 600;
    font-size: 0.85rem;
    color: #334155;
}

/* ── Divider tipis ── */
hr {
    border: none;
    border-top: 1px solid #e2e8f0;
    margin: 20px 0;
}
</style>
""", unsafe_allow_html=True)

# ============================================================
# KONSTANTA
# ============================================================
FASE_OPTIONS = ['ORDER', 'INCOME', 'REPORT']
MARKETPLACE_OPTIONS = {
    'Shopee':             'shopee',
    'TikTok / Tokopedia': 'tiktok_tokopedia',
    'Lazada':             'lazada',
}

FASE_DESC = {
    'ORDER':  'Data transaksi pesanan',
    'INCOME': 'Data pemasukan & komisi',
    'REPORT': 'Laporan keuangan / saldo',
}

MARKETPLACE_ICON = {
    'Shopee':             '🟠',
    'TikTok / Tokopedia': '⚫',
    'Lazada':             '🔵',
}

STATUS_META = {
    'new':          ('✦',  'Baru',               'badge-new'),
    'fully_loaded': ('✔',  'Sudah Dimuat Penuh',  'badge-loaded'),
    'partial':      ('◑',  'Dimuat Sebagian',     'badge-partial'),
    'anomaly':      ('⚠',  'Anomali',             'badge-anomaly'),
    'unknown':      ('?',  'Tidak Dikenali',      'badge-unknown'),
}


# ============================================================
# DB ENGINE (cached)
# ============================================================
@st.cache_resource
def get_db_engine():
    return get_engine()


# ============================================================
# LOG HANDLER
# ============================================================
class StreamlitLogHandler(logging.Handler):
    def emit(self, record):
        msg = self.format(record)
        st.session_state.setdefault('log_lines', []).append(msg)


def attach_streamlit_handler():
    root_logger = logging.getLogger()
    for h in root_logger.handlers:
        if isinstance(h, StreamlitLogHandler):
            return
    handler = StreamlitLogHandler()
    handler.setFormatter(logging.Formatter('%(asctime)s  %(levelname)-8s  %(message)s', '%H:%M:%S'))
    root_logger.addHandler(handler)


# ============================================================
# PROSES SATU FILE
# ============================================================
def process_file(file_path, fase, marketplace, engine):
    if fase == 'ORDER':
        process_order_file(file_path, marketplace, engine)
    elif fase == 'INCOME':
        process_income_file(file_path, marketplace, engine)
    elif fase == 'REPORT':
        process_report_file(file_path, marketplace, engine)


# ============================================================
# KOMPONEN HTML HELPER
# ============================================================
def render_badge(status_key):
    icon, label, css_class = STATUS_META.get(status_key, STATUS_META['unknown'])
    return f'<span class="wf-badge {css_class}">{icon}&nbsp;{label}</span>'


def render_file_card(filename, status_key, rows_in_db, rows_in_file):
    badge = render_badge(status_key)
    db_info = ""
    if rows_in_db > 0 or rows_in_file > 0:
        db_info = f"""
        <span style="font-size:0.78rem; color:#64748b; white-space:nowrap;">
            DB&nbsp;<b style="color:#1e293b">{rows_in_db:,}</b>&nbsp;/&nbsp;File&nbsp;<b style="color:#1e293b">{rows_in_file:,}</b>&nbsp;baris
        </span>
        """
    return f"""
    <div class="wf-file-card">
        <span style="font-size:1.1rem;">📄</span>
        <span class="wf-filename">{filename}</span>
        {db_info}
        {badge}
    </div>
    """


def render_stat_row(counts):
    new_c     = counts.get('new', 0)
    loaded_c  = counts.get('fully_loaded', 0)
    partial_c = counts.get('partial', 0)
    anomaly_c = counts.get('anomaly', 0)
    return f"""
    <div class="wf-stat-row">
        <div class="wf-stat stat-new">
            <div class="stat-num">{new_c}</div>
            <div class="stat-label">Baru</div>
        </div>
        <div class="wf-stat stat-loaded">
            <div class="stat-num">{loaded_c}</div>
            <div class="stat-label">Sudah Dimuat</div>
        </div>
        <div class="wf-stat stat-partial">
            <div class="stat-num">{partial_c}</div>
            <div class="stat-label">Sebagian</div>
        </div>
        <div class="wf-stat stat-anomaly">
            <div class="stat-num">{anomaly_c}</div>
            <div class="stat-label">Anomali</div>
        </div>
    </div>
    """


# ============================================================
# MAIN
# ============================================================
def main():
    attach_streamlit_handler()

    # ── Hero header ──────────────────────────────────────────
    st.markdown("""
    <div class="wf-header">
        <h1>🌾 Wellfarm Data Upload</h1>
        <p>Upload file spreadsheet dari Shopee, TikTok/Tokopedia, atau Lazada ke database staging.</p>
    </div>
    """, unsafe_allow_html=True)

    # ── Sidebar ───────────────────────────────────────────────
    with st.sidebar:
        st.markdown("### ⚙️ Pengaturan Upload")
        st.markdown("---")

        fase = st.selectbox("Fase Data", FASE_OPTIONS, index=0,
                            help="Pilih jenis data yang akan diunggah.")
        st.caption(f"_{FASE_DESC.get(fase, '')}_")

        st.markdown(" ")

        marketplace_label = st.selectbox(
            "Marketplace",
            list(MARKETPLACE_OPTIONS.keys()),
            index=0,
        )
        marketplace = MARKETPLACE_OPTIONS[marketplace_label]

        st.markdown(" ")

        skip_loaded = st.checkbox(
            "Lewati file yang sudah dimuat penuh",
            value=True,
            help="File dengan status 'Sudah Dimuat Penuh' tidak akan diproses ulang.",
        )

        st.markdown("---")
        st.markdown(
            f"<div style='font-size:0.78rem; color:#64748b;'>"
            f"<b>Database</b><br>wellfarm_alternate<br><br>"
            f"<b>Target</b><br>{MARKETPLACE_ICON.get(marketplace_label,'')} {marketplace_label} &mdash; {fase}"
            f"</div>",
            unsafe_allow_html=True,
        )

    # ── Konteks aktif ────────────────────────────────────────
    st.markdown(
        f'<div class="wf-context-card">'
        f'Anda akan mengupload file <strong>{fase}</strong> dari marketplace '
        f'<strong>{MARKETPLACE_ICON.get(marketplace_label,"")} {marketplace_label}</strong>. '
        f'Pastikan file yang dipilih sudah sesuai sebelum menekan tombol proses.'
        f'</div>',
        unsafe_allow_html=True,
    )

    # ── Uploader ──────────────────────────────────────────────
    uploaded_files = st.file_uploader(
        "Pilih satu atau beberapa file Excel (.xlsx)",
        type=["xlsx"],
        accept_multiple_files=True,
        key="file_uploader",
    )

    if not uploaded_files:
        st.markdown(
            "<div style='text-align:center; padding:40px 0; color:#94a3b8; font-size:0.9rem;'>"
            "📂&nbsp; Belum ada file yang dipilih.<br>"
            "<span style='font-size:0.8rem;'>Klik tombol di atas atau seret file ke sini.</span>"
            "</div>",
            unsafe_allow_html=True,
        )
        return

    # ── Koneksi DB ────────────────────────────────────────────
    try:
        engine = get_db_engine()
    except Exception as e:
        st.error(f"Gagal terhubung ke database: {e}")
        return

    # ── Cek status tiap file ──────────────────────────────────
    tmp_dir = tempfile.mkdtemp()
    file_statuses = []

    with st.spinner("Memeriksa status file terhadap database…"):
        for uf in uploaded_files:
            tmp_path = os.path.join(tmp_dir, uf.name)
            with open(tmp_path, 'wb') as f:
                f.write(uf.getbuffer())

            status = check_file_status(
                filename=uf.name,
                file_path=tmp_path,
                fase=fase,
                marketplace=marketplace,
                engine=engine,
            )
            file_statuses.append((uf, status, tmp_path))

    # ── Statistik ringkasan ───────────────────────────────────
    counts = {}
    for _, s, _ in file_statuses:
        counts[s['status']] = counts.get(s['status'], 0) + 1

    st.markdown(f'<div class="wf-section-title">Ringkasan — {len(file_statuses)} file dipilih</div>',
                unsafe_allow_html=True)
    st.markdown(render_stat_row(counts), unsafe_allow_html=True)

    # ── Daftar file + status ──────────────────────────────────
    st.markdown('<div class="wf-section-title">Detail Status Per File</div>', unsafe_allow_html=True)
    cards_html = "".join(
        render_file_card(
            uf.name,
            s['status'],
            s['rows_in_db'],
            s['rows_in_file'],
        )
        for uf, s, _ in file_statuses
    )
    st.markdown(cards_html, unsafe_allow_html=True)

    # ── Alert anomali / partial ───────────────────────────────
    anomaly_files = [uf.name for uf, s, _ in file_statuses if s['status'] == 'anomaly']
    partial_files = [uf.name for uf, s, _ in file_statuses if s['status'] == 'partial']

    if anomaly_files:
        st.warning(
            "**⚠ Anomali Terdeteksi**  \n"
            "File berikut memiliki lebih banyak baris di database daripada di file aslinya. "
            "Harap periksa secara manual sebelum melanjutkan:  \n"
            + "  \n".join(f"• `{f}`" for f in anomaly_files)
        )

    if partial_files:
        st.info(
            "**◑ File Dimuat Sebagian**  \n"
            "File berikut sebelumnya hanya sebagian masuk ke database. "
            "Proses akan menambahkan seluruh baris dari file (duplikasi mungkin terjadi):  \n"
            + "  \n".join(f"• `{f}`" for f in partial_files)
        )

    # ── Tombol proses ─────────────────────────────────────────
    to_process = [
        item for item in file_statuses
        if not (skip_loaded and item[1]['status'] == 'fully_loaded')
    ]
    skipped_count = len(file_statuses) - len(to_process)

    st.markdown("<hr>", unsafe_allow_html=True)

    col_info, col_btn = st.columns([4, 1])
    with col_info:
        if len(to_process) == 0:
            st.success("Semua file sudah dimuat penuh. Tidak ada yang perlu diproses.")
        elif skipped_count > 0:
            st.caption(
                f"{skipped_count} file dilewati (sudah dimuat penuh) · "
                f"**{len(to_process)} file akan diproses**"
            )
        else:
            st.caption(f"**{len(to_process)} file akan diproses**")

    with col_btn:
        run_button = st.button(
            f"▶  Proses  {len(to_process)}  File",
            type="primary",
            use_container_width=True,
            disabled=(len(to_process) == 0),
        )

    if len(to_process) == 0:
        return

    # ── Eksekusi proses ───────────────────────────────────────
    if run_button:
        st.session_state['log_lines'] = []
        st.markdown('<div class="wf-section-title">Progress</div>', unsafe_allow_html=True)

        progress_bar  = st.progress(0, text="Memulai…")
        log_container = st.empty()
        total  = len(to_process)
        errors = []

        for idx, (uf, status, tmp_path) in enumerate(to_process):
            progress_bar.progress(
                idx / total,
                text=f"({idx + 1}/{total})  {uf.name}",
            )
            try:
                process_file(tmp_path, fase, marketplace, engine)
            except Exception as e:
                logging.getLogger().error(f"GAGAL memproses {uf.name}: {e}")
                errors.append(uf.name)

            log_lines = st.session_state.get('log_lines', [])
            log_container.text_area(
                "Log",
                value="\n".join(log_lines[-200:]),
                height=280,
                key=f"log_{idx}",
                label_visibility="collapsed",
            )

        progress_bar.progress(1.0, text="Selesai!")

        st.markdown("<hr>", unsafe_allow_html=True)
        if errors:
            st.error(
                f"**Proses selesai dengan {len(errors)} error.**  \n"
                + "  \n".join(f"• `{f}`" for f in errors)
            )
        else:
            st.success(f"**Berhasil!** {total} file diproses tanpa error.")

        final_logs = st.session_state.get('log_lines', [])
        if final_logs:
            with st.expander("📋 Lihat Log Lengkap", expanded=False):
                st.code("\n".join(final_logs), language=None)


if __name__ == "__main__":
    main()
