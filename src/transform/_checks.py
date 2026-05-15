# src/transform/_checks.py
"""
Fungsi pemantauan nilai tidak dikenal (Kategori 2).
Dipanggil setelah setiap INSERT di fact tables.
Menggunakan koneksi yang sama agar temp tables (_tmp_*) masih tersedia.
"""

from sqlalchemy import text
from src.db_config import logger
from src.notifier import notify_unmapped_values

# ── Nilai yang dikenal per kolom ───────────────────────────────────────────────

_SHOPEE_ORDER_STATUS = {
    'Belum Bayar', 'Perlu Dikirim', 'Sedang Dikirim', 'Telah Dikirim',
    'Pesanan Diterima', 'Selesai', 'Pembatalan diajukan', 'Batal',
}
_TIKTOK_ORDER_STATUS = {'Belum dibayar', 'Perlu dikirim', 'Dikirim', 'Selesai', 'Dibatalkan'}
_LAZADA_ORDER_STATUS = {
    'ready_to_ship', 'shipped', 'confirmed', 'delivered', 'canceled',
    'returned', 'Package Returned', 'In Transit: Returning to seller',
    'Lost by 3PL', 'Damaged by 3PL', 'Package scrapped',
}

_SHOPEE_PAYMENT = {
    'COD (Bayar di Tempat)', 'ShopeePay', 'Saldo ShopeePay', 'QRIS',
    'Kartu Kredit/Debit', 'Cicilan Kartu Kredit', 'BCA OneKlik',
    'BRI Direct Debit', 'SeaBank Bayar Instan', 'SPayLater',
    'Alfamart/Alfamidi/Dan+Dan', 'Indomaret/i.Saku', 'Mitra Shopee',
    'Online Payment', 'Pembayaran dibebaskan', 'Bank Lainnya (Dicek Manual)',
}
_TIKTOK_PAYMENT = {
    'Bayar di tempat', 'Cash', 'KlikBCA', 'BRImo', 'Transfer bank',
    'Bank Transfer (Manual VA)', 'GoPay', 'OVO', 'DANA', 'LinkAja',
    'Jago / Jago Syariah', 'JakOne Pay', 'Jenius Pay', 'OCTO Clicks',
    'QRIS', 'Kartu kredit/debit', 'DirectDebit', 'GoPay Later', 'Kredivo',
    'BRI Ceria', 'PayLater', 'TikTok Shop Balance', 'Saldo',
    'Tokopedia History Order',
}
_LAZADA_PAYMENT = {
    'COD', 'BCA_VA', 'KLIKBCA_VA', 'BNI_VA', 'BRI_VA', 'MANDIRIMANDIRI_VA',
    'CIMB_VA', 'PANIN_VA', 'GOPAY_WALLET', 'WALLET_OVO', 'DANA_WALLET',
    'QRIS', 'MIXEDCARD', 'CREDITPAY_KREDIVO', 'PAY_LATER', 'SALDO',
    'ALFAMART_OTC', 'INDOMARET_OTC', 'PURE_ZERO_PRICE',
}

_SHOPEE_RETURN_STATUS = {
    'Permintaan Disetujui', 'Permintaan Dibatalkan', 'Pengembalian Diproses',
}
_TIKTOK_INITIATOR    = {'User', 'Seller', 'System', 'Operator'}
_TIKTOK_RETURN_TYPE  = {'Return/Refund', 'Cancel'}
_LAZADA_RETURN_STATUS = {
    'canceled', 'returned', 'Package Returned',
    'In Transit: Returning to seller', 'Lost by 3PL',
    'Damaged by 3PL', 'Package scrapped',
}

_SHOPEE_BALANCE_TYPE = {
    'Penghasilan dari Pesanan', 'Pembayaran dengan Saldo Penjual',
    'Penarikan Dana', 'Penyesuaian', 'Pengembalian Dana atas Pesanan',
}
_TIKTOK_BALANCE_TYPE = {'Withdrawal', 'Earnings', 'GMV Pay Deduction'}
_LAZADA_BALANCE_TYPE = {'Withdrawal', 'Deposit', 'Payment', 'Penalty'}


# ── Helper ─────────────────────────────────────────────────────────────────────

def _distinct(conn, sql, params=None):
    result = conn.execute(text(sql), params or {})
    return [r[0] for r in result if r[0] is not None]


def _unknown(values, known_set):
    return [v for v in values if v not in known_set]


def _notify_if_any(values, source, category, engine):
    if values:
        notify_unmapped_values(source, category, values, engine)
        logger.warning(f"⚠️ [{source}] {category}: {values}")


# ── fact_sales_online ──────────────────────────────────────────────────────────

def check_fact_sales_online(conn, marketplace, engine):
    src = f"fact_sales_online/{marketplace}"

    if marketplace == 'shopee':
        statuses = _distinct(conn, """
            SELECT DISTINCT o.status_pesanan FROM staging.stg_shopee_orders o
            JOIN _tmp_channel_map cm ON cm.nama_toko = LOWER(TRIM(o.nama_toko))
            WHERE cm.sales_channel_id IS NOT NULL
              AND NULLIF(TRIM(o.status_pesanan), 'nan') IS NOT NULL
        """)
        _notify_if_any(_unknown(statuses, _SHOPEE_ORDER_STATUS), src, 'Order Status', engine)

        payments = _distinct(conn, """
            SELECT DISTINCT o.metode_pembayaran FROM staging.stg_shopee_orders o
            JOIN _tmp_channel_map cm ON cm.nama_toko = LOWER(TRIM(o.nama_toko))
            WHERE cm.sales_channel_id IS NOT NULL
              AND NULLIF(TRIM(o.metode_pembayaran), 'nan') IS NOT NULL
        """)
        _notify_if_any(_unknown(payments, _SHOPEE_PAYMENT), src, 'Metode Pembayaran', engine)

    elif marketplace == 'tiktok_tokopedia':
        statuses = _distinct(conn, """
            SELECT DISTINCT o.order_status FROM staging.stg_tiktok_tokopedia_orders o
            JOIN _tmp_channel_map cm ON cm.nama_toko = LOWER(TRIM(o.nama_toko))
            WHERE cm.sales_channel_id IS NOT NULL
              AND NULLIF(TRIM(o.order_status), 'nan') IS NOT NULL
        """)
        _notify_if_any(_unknown(statuses, _TIKTOK_ORDER_STATUS), src, 'Order Status', engine)

        payments = _distinct(conn, """
            SELECT DISTINCT o.payment_method FROM staging.stg_tiktok_tokopedia_orders o
            JOIN _tmp_channel_map cm ON cm.nama_toko = LOWER(TRIM(o.nama_toko))
            WHERE cm.sales_channel_id IS NOT NULL
              AND NULLIF(TRIM(o.payment_method), 'nan') IS NOT NULL
        """)
        _notify_if_any(_unknown(payments, _TIKTOK_PAYMENT), src, 'Metode Pembayaran', engine)

    elif marketplace == 'lazada':
        statuses = _distinct(conn, """
            SELECT DISTINCT o.status FROM staging.stg_lazada_orders o
            JOIN _tmp_channel_map cm ON cm.nama_toko = LOWER(TRIM(o.nama_toko))
            WHERE cm.sales_channel_id IS NOT NULL
              AND NULLIF(TRIM(o.status), 'nan') IS NOT NULL
        """)
        _notify_if_any(_unknown(statuses, _LAZADA_ORDER_STATUS), src, 'Order Status', engine)

        payments = _distinct(conn, """
            SELECT DISTINCT o.pay_method FROM staging.stg_lazada_orders o
            JOIN _tmp_channel_map cm ON cm.nama_toko = LOWER(TRIM(o.nama_toko))
            WHERE cm.sales_channel_id IS NOT NULL
              AND NULLIF(TRIM(o.pay_method), 'nan') IS NOT NULL
        """)
        _notify_if_any(_unknown(payments, _LAZADA_PAYMENT), src, 'Metode Pembayaran', engine)


# ── fact_returns_online ────────────────────────────────────────────────────────

def check_fact_returns_online(conn, marketplace, engine):
    src = f"fact_returns_online/{marketplace}"

    if marketplace == 'shopee':
        statuses = _distinct(conn, """
            SELECT DISTINCT o.status_pembatalan_pengembalian
            FROM staging.stg_shopee_orders o
            JOIN _tmp_channel_map cm ON cm.nama_toko = LOWER(TRIM(o.nama_toko))
            WHERE cm.sales_channel_id IS NOT NULL
              AND NULLIF(TRIM(o.status_pembatalan_pengembalian), 'nan') IS NOT NULL
        """)
        _notify_if_any(_unknown(statuses, _SHOPEE_RETURN_STATUS), src, 'Return Status', engine)

    elif marketplace == 'tiktok_tokopedia':
        initiators = _distinct(conn, """
            SELECT DISTINCT NULLIF(TRIM(o.cancel_by), 'nan')
            FROM staging.stg_tiktok_tokopedia_orders o
            JOIN _tmp_channel_map cm ON cm.nama_toko = LOWER(TRIM(o.nama_toko))
            WHERE cm.sales_channel_id IS NOT NULL
              AND NULLIF(TRIM(o.cancelation_return_type), 'nan') IS NOT NULL
              AND NULLIF(TRIM(o.cancel_by), 'nan') IS NOT NULL
        """)
        _notify_if_any(_unknown(initiators, _TIKTOK_INITIATOR), src, 'Initiator (cancel_by)', engine)

        reasons = _distinct(conn, """
            SELECT DISTINCT TRIM(o.cancel_reason)
            FROM staging.stg_tiktok_tokopedia_orders o
            LEFT JOIN public.dim_cancel_return_reason cr
                ON cr.reason_text_original = TRIM(o.cancel_reason)
            JOIN _tmp_channel_map cm ON cm.nama_toko = LOWER(TRIM(o.nama_toko))
            WHERE cm.sales_channel_id IS NOT NULL
              AND NULLIF(TRIM(o.cancelation_return_type), 'nan') IS NOT NULL
              AND NULLIF(TRIM(o.cancel_reason), 'nan') IS NOT NULL
              AND cr.cancel_return_reason_id IS NULL
        """)
        _notify_if_any(reasons, src, 'Cancel Return Reason', engine)

    elif marketplace == 'lazada':
        statuses = _distinct(conn, """
            SELECT DISTINCT o.status FROM staging.stg_lazada_orders o
            JOIN _tmp_channel_map cm ON cm.nama_toko = LOWER(TRIM(o.nama_toko))
            WHERE cm.sales_channel_id IS NOT NULL
              AND (TRIM(o.status) IN ('canceled','returned','Package Returned',
                  'In Transit: Returning to seller','Lost by 3PL',
                  'Damaged by 3PL','Package scrapped')
              OR o.buyer_failed_delivery_return_initiator LIKE 'only_refund%')
        """)
        _notify_if_any(_unknown(statuses, _LAZADA_RETURN_STATUS), src, 'Return Status', engine)

        reasons = _distinct(conn, """
            SELECT DISTINCT TRIM(REGEXP_REPLACE(o.buyer_failed_delivery_reason, '[\r\n]+', '', 'g'))
            FROM staging.stg_lazada_orders o
            LEFT JOIN public.dim_cancel_return_reason cr
                ON cr.reason_text_original = TRIM(REGEXP_REPLACE(
                    o.buyer_failed_delivery_reason, '[\r\n]+', '', 'g'))
            JOIN _tmp_channel_map cm ON cm.nama_toko = LOWER(TRIM(o.nama_toko))
            WHERE cm.sales_channel_id IS NOT NULL
              AND NULLIF(TRIM(o.buyer_failed_delivery_reason), 'nan') IS NOT NULL
              AND cr.cancel_return_reason_id IS NULL
        """)
        _notify_if_any(reasons, src, 'Cancel Return Reason', engine)


# ── fact_fulfillment_logistics ─────────────────────────────────────────────────

def check_fact_fulfillment_logistics(conn, marketplace, engine):
    src = f"fact_fulfillment_logistics/{marketplace}"

    if marketplace == 'shopee':
        providers = _distinct(conn, """
            SELECT DISTINCT CASE WHEN o.opsi_pengiriman LIKE '%-%'
                THEN TRIM(SUBSTRING(o.opsi_pengiriman FROM STRPOS(o.opsi_pengiriman, '-') + 1))
                ELSE TRIM(o.opsi_pengiriman) END AS provider
            FROM staging.stg_shopee_orders o
            JOIN _tmp_channel_map cm ON cm.nama_toko = o.nama_toko
            LEFT JOIN _tmp_shipping_map sm ON sm.provider = CASE
                WHEN o.opsi_pengiriman LIKE '%-%'
                THEN TRIM(SUBSTRING(o.opsi_pengiriman FROM STRPOS(o.opsi_pengiriman, '-') + 1))
                ELSE TRIM(o.opsi_pengiriman) END
            WHERE cm.sales_channel_id IS NOT NULL
              AND NULLIF(TRIM(o.opsi_pengiriman), 'nan') IS NOT NULL
              AND sm.service_id IS NULL
        """)
        _notify_if_any(providers, src, 'Shipping Provider', engine)

        warehouses = _distinct(conn, """
            SELECT DISTINCT LOWER(TRIM(o.nama_gudang))
            FROM staging.stg_shopee_orders o
            JOIN _tmp_channel_map cm ON cm.nama_toko = o.nama_toko
            LEFT JOIN _tmp_warehouse_map wm ON wm.raw_name = LOWER(TRIM(o.nama_gudang))
            WHERE cm.sales_channel_id IS NOT NULL
              AND NULLIF(TRIM(o.nama_gudang), 'nan') IS NOT NULL
              AND wm.warehouse_id IS NULL
        """)
        _notify_if_any(warehouses, src, 'Warehouse', engine)

    elif marketplace == 'tiktok_tokopedia':
        providers = _distinct(conn, """
            SELECT DISTINCT TRIM(o.shipping_provider_name)
            FROM staging.stg_tiktok_tokopedia_orders o
            JOIN _tmp_channel_map cm ON cm.nama_toko = o.nama_toko
            LEFT JOIN _tmp_shipping_map sm_exact
                ON sm_exact.provider = TRIM(o.shipping_provider_name)
               AND sm_exact.delivery_option = TRIM(o.delivery_option)
            LEFT JOIN _tmp_shipping_map sm_wild
                ON sm_wild.provider = TRIM(o.shipping_provider_name)
               AND sm_wild.delivery_option = '_'
            WHERE cm.sales_channel_id IS NOT NULL
              AND NULLIF(TRIM(o.shipping_provider_name), 'nan') IS NOT NULL
              AND sm_exact.service_id IS NULL
              AND sm_wild.service_id IS NULL
        """)
        _notify_if_any(providers, src, 'Shipping Provider', engine)

        warehouses = _distinct(conn, """
            SELECT DISTINCT LOWER(TRIM(o.warehouse_name))
            FROM staging.stg_tiktok_tokopedia_orders o
            JOIN _tmp_channel_map cm ON cm.nama_toko = o.nama_toko
            LEFT JOIN _tmp_warehouse_map wm ON wm.raw_name = LOWER(TRIM(o.warehouse_name))
            WHERE cm.sales_channel_id IS NOT NULL
              AND NULLIF(TRIM(o.warehouse_name), 'nan') IS NOT NULL
              AND wm.warehouse_id IS NULL
        """)
        _notify_if_any(warehouses, src, 'Warehouse', engine)

    elif marketplace == 'lazada':
        providers = _distinct(conn, """
            SELECT DISTINCT TRIM(o.shipping_provider)
            FROM staging.stg_lazada_orders o
            JOIN _tmp_channel_map cm ON cm.nama_toko = o.nama_toko
            LEFT JOIN _tmp_shipping_map sm ON sm.provider = TRIM(o.shipping_provider)
            WHERE cm.sales_channel_id IS NOT NULL
              AND NULLIF(TRIM(o.shipping_provider), 'nan') IS NOT NULL
              AND sm.service_id IS NULL
        """)
        _notify_if_any(providers, src, 'Shipping Provider', engine)

        warehouses = _distinct(conn, """
            SELECT DISTINCT LOWER(TRIM(o.warehouse))
            FROM staging.stg_lazada_orders o
            JOIN _tmp_channel_map cm ON cm.nama_toko = o.nama_toko
            LEFT JOIN _tmp_warehouse_map wm ON wm.raw_name = LOWER(TRIM(o.warehouse))
            WHERE cm.sales_channel_id IS NOT NULL
              AND NULLIF(TRIM(o.warehouse), 'nan') IS NOT NULL
              AND wm.warehouse_id IS NULL
        """)
        _notify_if_any(warehouses, src, 'Warehouse', engine)


# ── fact_balance_transaction ───────────────────────────────────────────────────

def check_fact_balance_transaction(conn, marketplace, engine):
    src = f"fact_balance_transaction/{marketplace}"

    if marketplace == 'shopee':
        types = _distinct(conn, """
            SELECT DISTINCT TRIM(r.tipe_transaksi)
            FROM staging.stg_shopee_report r
            JOIN _tmp_channel_map cm ON cm.nama_toko = r.nama_toko
            WHERE cm.sales_channel_id IS NOT NULL
              AND NULLIF(TRIM(r.tipe_transaksi), 'nan') IS NOT NULL
        """)
        _notify_if_any(_unknown(types, _SHOPEE_BALANCE_TYPE), src, 'Tipe Transaksi', engine)

    elif marketplace == 'tiktok_tokopedia':
        types = _distinct(conn, """
            SELECT DISTINCT TRIM(r.type)
            FROM staging.stg_tiktok_tokopedia_report r
            JOIN _tmp_channel_map cm ON cm.nama_toko = r.nama_toko
            WHERE cm.sales_channel_id IS NOT NULL
              AND NULLIF(TRIM(r.type), 'nan') IS NOT NULL
        """)
        _notify_if_any(_unknown(types, _TIKTOK_BALANCE_TYPE), src, 'Transaction Type', engine)

    elif marketplace == 'lazada':
        types = _distinct(conn, """
            SELECT DISTINCT TRIM(r.type)
            FROM staging.stg_lazada_report r
            JOIN _tmp_channel_map cm ON cm.nama_toko = r.nama_toko
            WHERE cm.sales_channel_id IS NOT NULL
              AND NULLIF(TRIM(r.type), 'nan') IS NOT NULL
        """)
        _notify_if_any(_unknown(types, _LAZADA_BALANCE_TYPE), src, 'Transaction Type', engine)


# ── fact_order_fees ────────────────────────────────────────────────────────────

def check_fact_order_fees_narrow(conn, marketplace, engine):
    """Cek fee name yang tidak ada di dim_fee_type (narrow format)."""
    src = f"fact_order_fees/{marketplace}"

    if marketplace == 'shopee':
        fees = _distinct(conn, """
            SELECT DISTINCT TRIM(o.tipe_penyesuaian_deskripsi)
            FROM staging.stg_shopee_income_adjustment o
            LEFT JOIN public.dim_fee_type ft
                ON ft.fee_name = TRIM(o.tipe_penyesuaian_deskripsi)
               AND ft.marketplace_name = 'Shopee'
            WHERE ft.fee_type_id IS NULL
              AND NULLIF(NULLIF(TRIM(o.biaya_penyesuaian), 'nan'), '') IS NOT NULL
              AND NULLIF(NULLIF(TRIM(o.biaya_penyesuaian), 'nan'), '')::NUMERIC <> 0
        """)
        _notify_if_any(fees, src, 'Fee Name Baru (Shopee Adj)', engine)

    elif marketplace == 'lazada':
        fees = _distinct(conn, """
            SELECT DISTINCT TRIM(o.nama_biaya)
            FROM staging.stg_lazada_income o
            LEFT JOIN public.dim_fee_type ft
                ON ft.fee_name = TRIM(o.nama_biaya)
               AND ft.marketplace_name = 'Lazada'
            WHERE ft.fee_type_id IS NULL
              AND NULLIF(REPLACE(TRIM(o.jumlah_termasuk_pajak), ',', ''), 'nan') IS NOT NULL
              AND NULLIF(REPLACE(TRIM(o.jumlah_termasuk_pajak), ',', ''), 'nan')::NUMERIC <> 0
        """)
        _notify_if_any(fees, src, 'Fee Name Baru (Lazada)', engine)
