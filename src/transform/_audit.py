from sqlalchemy import text

from src.db_config import logger
from src.transform._maps import SHOPEE_INCOME_MAIN_FEE_COLS, TIKTOK_INCOME_FEE_COLS


def ensure_transform_audit_log(conn):
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS staging.transform_audit_log (
            audit_id    SERIAL PRIMARY KEY,
            detected_at TIMESTAMPTZ DEFAULT NOW(),
            phase       TEXT,
            module_name TEXT,
            marketplace TEXT,
            severity    TEXT,
            check_name  TEXT,
            row_count   BIGINT,
            message     TEXT
        )
    """))
    conn.execute(text("""
        ALTER TABLE staging.transform_audit_log
            ADD COLUMN IF NOT EXISTS detected_at TIMESTAMPTZ DEFAULT NOW(),
            ADD COLUMN IF NOT EXISTS phase TEXT,
            ADD COLUMN IF NOT EXISTS module_name TEXT,
            ADD COLUMN IF NOT EXISTS marketplace TEXT,
            ADD COLUMN IF NOT EXISTS severity TEXT,
            ADD COLUMN IF NOT EXISTS check_name TEXT,
            ADD COLUMN IF NOT EXISTS row_count BIGINT,
            ADD COLUMN IF NOT EXISTS message TEXT
    """))


def log_transform_audit(
    conn,
    phase,
    module_name,
    marketplace,
    severity,
    check_name,
    row_count,
    message,
):
    ensure_transform_audit_log(conn)
    conn.execute(text("""
        INSERT INTO staging.transform_audit_log
            (phase, module_name, marketplace, severity, check_name, row_count, message)
        VALUES
            (:phase, :module_name, :marketplace, :severity, :check_name, :row_count, :message)
    """), {
        "phase": phase,
        "module_name": module_name,
        "marketplace": marketplace,
        "severity": severity,
        "check_name": check_name,
        "row_count": row_count,
        "message": message,
    })

    log_message = (
        f"[AUDIT:{phase}] {module_name}/{marketplace} | "
        f"{severity} | {check_name}={row_count} | {message}"
    )
    if severity == "ERROR":
        logger.error(log_message)
    elif severity == "WARNING":
        logger.warning(log_message)
    else:
        logger.info(log_message)


def _scalar(conn, sql):
    return conn.execute(text(sql)).scalar() or 0


def _audit_count(conn, module_name, marketplace, check_name, row_count, message, severity="INFO"):
    log_transform_audit(
        conn,
        "pre",
        module_name,
        marketplace,
        severity,
        check_name,
        row_count,
        message,
    )


def _severity_for_skipped(row_count):
    return "WARNING" if row_count else "INFO"


def _severity_for_zero_eligible(total_rows, eligible_rows):
    return "ERROR" if total_rows and not eligible_rows else "INFO"


def pre_audit_fact_sales_online(conn, marketplace):
    module_name = "fact_sales_online"

    if marketplace == "shopee":
        total = _scalar(conn, "SELECT COUNT(*) FROM staging.stg_shopee_orders")
        null_order = _scalar(conn, """
            SELECT COUNT(*) FROM staging.stg_shopee_orders
            WHERE NULLIF(TRIM(no_pesanan), 'nan') IS NULL
        """)
        unmapped_channel = _scalar(conn, """
            SELECT COUNT(*)
            FROM staging.stg_shopee_orders o
            LEFT JOIN _tmp_channel_map cm ON cm.nama_toko = LOWER(TRIM(o.nama_toko))
            WHERE cm.sales_channel_id IS NULL
        """)
        unmapped_product = _scalar(conn, """
            SELECT COUNT(*)
            FROM staging.stg_shopee_orders o
            LEFT JOIN _tmp_channel_map cm ON cm.nama_toko = LOWER(TRIM(o.nama_toko))
            LEFT JOIN public.dim_sku_alias dsa ON dsa.sku_alias = COALESCE(
                NULLIF(TRIM(o.nomor_referensi_sku),'nan'), NULLIF(TRIM(o.sku_induk),'nan'))
            LEFT JOIN public.dim_product dp ON dp.sku_code = COALESCE(
                (SELECT dp1.sku_code FROM public.dim_product dp1 WHERE dp1.sku_code = (
                    CASE WHEN COALESCE(NULLIF(TRIM(o.nomor_referensi_sku),'nan'),NULLIF(TRIM(o.sku_induk),'nan')) ~ '^P[0-9]'
                        THEN 'B'||SUBSTRING(COALESCE(NULLIF(TRIM(o.nomor_referensi_sku),'nan'),NULLIF(TRIM(o.sku_induk),'nan')),2)
                        ELSE COALESCE(NULLIF(TRIM(o.nomor_referensi_sku),'nan'),NULLIF(TRIM(o.sku_induk),'nan'))
                    END) LIMIT 1),
                dsa.sku_code)
            WHERE cm.sales_channel_id IS NOT NULL
              AND NULLIF(TRIM(o.no_pesanan), 'nan') IS NOT NULL
              AND dp.product_id IS NULL
        """)
        eligible = _scalar(conn, """
            SELECT COUNT(DISTINCT (o.no_pesanan, dp.product_id, cm.sales_channel_id))
            FROM staging.stg_shopee_orders o
            LEFT JOIN _tmp_channel_map cm ON cm.nama_toko = LOWER(TRIM(o.nama_toko))
            LEFT JOIN public.dim_sku_alias dsa ON dsa.sku_alias = COALESCE(
                NULLIF(TRIM(o.nomor_referensi_sku),'nan'), NULLIF(TRIM(o.sku_induk),'nan'))
            LEFT JOIN public.dim_product dp ON dp.sku_code = COALESCE(
                (SELECT dp1.sku_code FROM public.dim_product dp1 WHERE dp1.sku_code = (
                    CASE WHEN COALESCE(NULLIF(TRIM(o.nomor_referensi_sku),'nan'),NULLIF(TRIM(o.sku_induk),'nan')) ~ '^P[0-9]'
                        THEN 'B'||SUBSTRING(COALESCE(NULLIF(TRIM(o.nomor_referensi_sku),'nan'),NULLIF(TRIM(o.sku_induk),'nan')),2)
                        ELSE COALESCE(NULLIF(TRIM(o.nomor_referensi_sku),'nan'),NULLIF(TRIM(o.sku_induk),'nan'))
                    END) LIMIT 1),
                dsa.sku_code)
            WHERE cm.sales_channel_id IS NOT NULL
              AND dp.product_id IS NOT NULL
        """)
        duplicate_grain = _scalar(conn, """
            WITH eligible AS (
                SELECT o.no_pesanan, dp.product_id, cm.sales_channel_id
                FROM staging.stg_shopee_orders o
                LEFT JOIN _tmp_channel_map cm ON cm.nama_toko = LOWER(TRIM(o.nama_toko))
                LEFT JOIN public.dim_sku_alias dsa ON dsa.sku_alias = COALESCE(
                    NULLIF(TRIM(o.nomor_referensi_sku),'nan'), NULLIF(TRIM(o.sku_induk),'nan'))
                LEFT JOIN public.dim_product dp ON dp.sku_code = COALESCE(
                    (SELECT dp1.sku_code FROM public.dim_product dp1 WHERE dp1.sku_code = (
                        CASE WHEN COALESCE(NULLIF(TRIM(o.nomor_referensi_sku),'nan'),NULLIF(TRIM(o.sku_induk),'nan')) ~ '^P[0-9]'
                            THEN 'B'||SUBSTRING(COALESCE(NULLIF(TRIM(o.nomor_referensi_sku),'nan'),NULLIF(TRIM(o.sku_induk),'nan')),2)
                            ELSE COALESCE(NULLIF(TRIM(o.nomor_referensi_sku),'nan'),NULLIF(TRIM(o.sku_induk),'nan'))
                        END) LIMIT 1),
                    dsa.sku_code)
                WHERE cm.sales_channel_id IS NOT NULL
                  AND dp.product_id IS NOT NULL
            )
            SELECT COALESCE(SUM(cnt - 1), 0)
            FROM (
                SELECT COUNT(*) AS cnt
                FROM eligible
                GROUP BY no_pesanan, product_id, sales_channel_id
                HAVING COUNT(*) > 1
            ) d
        """)

    elif marketplace == "tiktok_tokopedia":
        total = _scalar(conn, "SELECT COUNT(*) FROM staging.stg_tiktok_tokopedia_orders")
        null_order = _scalar(conn, """
            SELECT COUNT(*) FROM staging.stg_tiktok_tokopedia_orders
            WHERE NULLIF(TRIM(order_id), 'nan') IS NULL
        """)
        unmapped_channel = _scalar(conn, """
            SELECT COUNT(*)
            FROM staging.stg_tiktok_tokopedia_orders o
            LEFT JOIN _tmp_channel_map cm ON cm.nama_toko = LOWER(TRIM(o.nama_toko))
            WHERE cm.sales_channel_id IS NULL
        """)
        unmapped_product = _scalar(conn, """
            SELECT COUNT(*)
            FROM staging.stg_tiktok_tokopedia_orders o
            LEFT JOIN _tmp_channel_map cm ON cm.nama_toko = LOWER(TRIM(o.nama_toko))
            LEFT JOIN public.dim_sku_alias dsa ON dsa.sku_alias = NULLIF(TRIM(o.seller_sku),'nan')
            LEFT JOIN public.dim_product dp ON dp.sku_code = COALESCE(
                (SELECT dp1.sku_code FROM public.dim_product dp1
                WHERE dp1.sku_code = NULLIF(TRIM(o.seller_sku),'nan') LIMIT 1),
                dsa.sku_code)
            WHERE cm.sales_channel_id IS NOT NULL
              AND NULLIF(TRIM(o.order_id), 'nan') IS NOT NULL
              AND dp.product_id IS NULL
        """)
        eligible = _scalar(conn, """
            SELECT COUNT(DISTINCT (o.order_id, dp.product_id, cm.sales_channel_id))
            FROM staging.stg_tiktok_tokopedia_orders o
            LEFT JOIN _tmp_channel_map cm ON cm.nama_toko = LOWER(TRIM(o.nama_toko))
            LEFT JOIN public.dim_sku_alias dsa ON dsa.sku_alias = NULLIF(TRIM(o.seller_sku),'nan')
            LEFT JOIN public.dim_product dp ON dp.sku_code = COALESCE(
                (SELECT dp1.sku_code FROM public.dim_product dp1
                WHERE dp1.sku_code = NULLIF(TRIM(o.seller_sku),'nan') LIMIT 1),
                dsa.sku_code)
            WHERE cm.sales_channel_id IS NOT NULL
              AND dp.product_id IS NOT NULL
        """)
        duplicate_grain = _scalar(conn, """
            WITH eligible AS (
                SELECT o.order_id, dp.product_id, cm.sales_channel_id
                FROM staging.stg_tiktok_tokopedia_orders o
                LEFT JOIN _tmp_channel_map cm ON cm.nama_toko = LOWER(TRIM(o.nama_toko))
                LEFT JOIN public.dim_sku_alias dsa ON dsa.sku_alias = NULLIF(TRIM(o.seller_sku),'nan')
                LEFT JOIN public.dim_product dp ON dp.sku_code = COALESCE(
                    (SELECT dp1.sku_code FROM public.dim_product dp1
                    WHERE dp1.sku_code = NULLIF(TRIM(o.seller_sku),'nan') LIMIT 1),
                    dsa.sku_code)
                WHERE cm.sales_channel_id IS NOT NULL
                  AND dp.product_id IS NOT NULL
            )
            SELECT COALESCE(SUM(cnt - 1), 0)
            FROM (
                SELECT COUNT(*) AS cnt
                FROM eligible
                GROUP BY order_id, product_id, sales_channel_id
                HAVING COUNT(*) > 1
            ) d
        """)

    elif marketplace == "lazada":
        total = _scalar(conn, "SELECT COUNT(*) FROM staging.stg_lazada_orders")
        null_order = _scalar(conn, """
            SELECT COUNT(*) FROM staging.stg_lazada_orders
            WHERE NULLIF(TRIM(order_number), 'nan') IS NULL
        """)
        unmapped_channel = _scalar(conn, """
            SELECT COUNT(*)
            FROM staging.stg_lazada_orders o
            LEFT JOIN _tmp_channel_map cm ON cm.nama_toko = LOWER(TRIM(o.nama_toko))
            WHERE cm.sales_channel_id IS NULL
        """)
        unmapped_product = _scalar(conn, """
            SELECT COUNT(*)
            FROM staging.stg_lazada_orders o
            LEFT JOIN _tmp_channel_map cm ON cm.nama_toko = LOWER(TRIM(o.nama_toko))
            LEFT JOIN public.dim_sku_alias dsa ON dsa.sku_alias = NULLIF(TRIM(o.seller_sku),'nan')
            LEFT JOIN public.dim_product dp ON dp.sku_code = COALESCE(
                (SELECT dp1.sku_code FROM public.dim_product dp1 WHERE dp1.sku_code = (
                    CASE WHEN NULLIF(TRIM(o.seller_sku),'nan') ~ '^P[0-9]'
                        THEN 'B'||SUBSTRING(NULLIF(TRIM(o.seller_sku),'nan'),2)
                        ELSE NULLIF(TRIM(o.seller_sku),'nan')
                    END) LIMIT 1),
                dsa.sku_code)
            WHERE cm.sales_channel_id IS NOT NULL
              AND NULLIF(TRIM(o.order_number), 'nan') IS NOT NULL
              AND dp.product_id IS NULL
        """)
        eligible = _scalar(conn, """
            SELECT COUNT(DISTINCT (o.order_number, dp.product_id, cm.sales_channel_id))
            FROM staging.stg_lazada_orders o
            LEFT JOIN _tmp_channel_map cm ON cm.nama_toko = LOWER(TRIM(o.nama_toko))
            LEFT JOIN public.dim_sku_alias dsa ON dsa.sku_alias = NULLIF(TRIM(o.seller_sku),'nan')
            LEFT JOIN public.dim_product dp ON dp.sku_code = COALESCE(
                (SELECT dp1.sku_code FROM public.dim_product dp1 WHERE dp1.sku_code = (
                    CASE WHEN NULLIF(TRIM(o.seller_sku),'nan') ~ '^P[0-9]'
                        THEN 'B'||SUBSTRING(NULLIF(TRIM(o.seller_sku),'nan'),2)
                        ELSE NULLIF(TRIM(o.seller_sku),'nan')
                    END) LIMIT 1),
                dsa.sku_code)
            WHERE cm.sales_channel_id IS NOT NULL
              AND dp.product_id IS NOT NULL
        """)
        duplicate_grain = _scalar(conn, """
            WITH eligible AS (
                SELECT o.order_number, dp.product_id, cm.sales_channel_id
                FROM staging.stg_lazada_orders o
                LEFT JOIN _tmp_channel_map cm ON cm.nama_toko = LOWER(TRIM(o.nama_toko))
                LEFT JOIN public.dim_sku_alias dsa ON dsa.sku_alias = NULLIF(TRIM(o.seller_sku),'nan')
                LEFT JOIN public.dim_product dp ON dp.sku_code = COALESCE(
                    (SELECT dp1.sku_code FROM public.dim_product dp1 WHERE dp1.sku_code = (
                        CASE WHEN NULLIF(TRIM(o.seller_sku),'nan') ~ '^P[0-9]'
                            THEN 'B'||SUBSTRING(NULLIF(TRIM(o.seller_sku),'nan'),2)
                            ELSE NULLIF(TRIM(o.seller_sku),'nan')
                        END) LIMIT 1),
                    dsa.sku_code)
                WHERE cm.sales_channel_id IS NOT NULL
                  AND dp.product_id IS NOT NULL
            )
            SELECT COALESCE(SUM(cnt - 1), 0)
            FROM (
                SELECT COUNT(*) AS cnt
                FROM eligible
                GROUP BY order_number, product_id, sales_channel_id
                HAVING COUNT(*) > 1
            ) d
        """)
    else:
        logger.warning(f"Marketplace '{marketplace}' tidak dikenal untuk pre-audit {module_name}.")
        return

    _audit_count(conn, module_name, marketplace, "staging_total_rows", total, "Total baris staging.")
    _audit_count(conn, module_name, marketplace, "null_order_id", null_order, "Baris tanpa order ID.", _severity_for_skipped(null_order))
    _audit_count(conn, module_name, marketplace, "unmapped_channel", unmapped_channel, "Baris dengan nama toko/channel tidak termapping.", _severity_for_skipped(unmapped_channel))
    _audit_count(conn, module_name, marketplace, "unmapped_product", unmapped_product, "Baris eligible channel tetapi SKU tidak termapping ke product.", _severity_for_skipped(unmapped_product))
    _audit_count(conn, module_name, marketplace, "eligible_grains", eligible, "Estimasi grain unik yang eligible masuk/update public.", _severity_for_zero_eligible(total, eligible))
    _audit_count(conn, module_name, marketplace, "duplicate_staging_grain", duplicate_grain, "Baris ekstra dengan grain staging yang sama.", _severity_for_skipped(duplicate_grain))


def pre_audit_fact_settlement(conn, marketplace):
    module_name = "fact_settlement"

    if marketplace == "shopee":
        total = _scalar(conn, "SELECT COUNT(*) FROM staging.stg_shopee_income_main")
        null_order = _scalar(conn, """
            SELECT COUNT(*) FROM staging.stg_shopee_income_main
            WHERE NULLIF(TRIM(no_pesanan), 'nan') IS NULL
        """)
        unmapped_channel = _scalar(conn, """
            SELECT COUNT(*)
            FROM staging.stg_shopee_income_main o
            LEFT JOIN _tmp_channel_map cm ON cm.nama_toko = LOWER(TRIM(o.nama_toko))
            WHERE cm.sales_channel_id IS NULL
        """)
        eligible = _scalar(conn, """
            SELECT COUNT(DISTINCT (o.no_pesanan, cm.sales_channel_id))
            FROM staging.stg_shopee_income_main o
            LEFT JOIN _tmp_channel_map cm ON cm.nama_toko = LOWER(TRIM(o.nama_toko))
            WHERE cm.sales_channel_id IS NOT NULL
              AND NULLIF(TRIM(o.no_pesanan), 'nan') IS NOT NULL
        """)
        duplicate_grain = _scalar(conn, """
            SELECT COALESCE(SUM(cnt - 1), 0)
            FROM (
                SELECT COUNT(*) AS cnt
                FROM staging.stg_shopee_income_main o
                LEFT JOIN _tmp_channel_map cm ON cm.nama_toko = LOWER(TRIM(o.nama_toko))
                WHERE cm.sales_channel_id IS NOT NULL
                  AND NULLIF(TRIM(o.no_pesanan), 'nan') IS NOT NULL
                GROUP BY o.no_pesanan, cm.sales_channel_id
                HAVING COUNT(*) > 1
            ) d
        """)

    elif marketplace == "tiktok_tokopedia":
        total = _scalar(conn, "SELECT COUNT(*) FROM staging.stg_tiktok_tokopedia_income")
        null_order = _scalar(conn, """
            SELECT COUNT(*) FROM staging.stg_tiktok_tokopedia_income
            WHERE NULLIF(TRIM(order_adjustment_id), 'nan') IS NULL
        """)
        unmapped_channel = _scalar(conn, """
            SELECT COUNT(*)
            FROM staging.stg_tiktok_tokopedia_income o
            LEFT JOIN _tmp_channel_map cm ON cm.nama_toko = LOWER(TRIM(o.nama_toko))
            WHERE cm.sales_channel_id IS NULL
        """)
        eligible = _scalar(conn, """
            SELECT COUNT(DISTINCT (o.order_adjustment_id, cm.sales_channel_id))
            FROM staging.stg_tiktok_tokopedia_income o
            LEFT JOIN _tmp_channel_map cm ON cm.nama_toko = LOWER(TRIM(o.nama_toko))
            WHERE cm.sales_channel_id IS NOT NULL
              AND NULLIF(TRIM(o.order_adjustment_id), 'nan') IS NOT NULL
              AND o.type = 'Order'
        """)
        duplicate_grain = _scalar(conn, """
            SELECT COALESCE(SUM(cnt - 1), 0)
            FROM (
                SELECT COUNT(*) AS cnt
                FROM staging.stg_tiktok_tokopedia_income o
                LEFT JOIN _tmp_channel_map cm ON cm.nama_toko = LOWER(TRIM(o.nama_toko))
                WHERE cm.sales_channel_id IS NOT NULL
                  AND NULLIF(TRIM(o.order_adjustment_id), 'nan') IS NOT NULL
                  AND o.type = 'Order'
                GROUP BY o.order_adjustment_id, cm.sales_channel_id
                HAVING COUNT(*) > 1
            ) d
        """)

    elif marketplace == "lazada":
        total = _scalar(conn, "SELECT COUNT(*) FROM staging.stg_lazada_income")
        null_order = _scalar(conn, """
            SELECT COUNT(*) FROM staging.stg_lazada_income
            WHERE COALESCE(NULLIF(TRIM(nomor_pesanan), 'nan'), NULLIF(TRIM(id_pesanan), 'nan')) IS NULL
        """)
        unmapped_channel = _scalar(conn, """
            SELECT COUNT(*)
            FROM staging.stg_lazada_income o
            LEFT JOIN _tmp_channel_map cm ON cm.nama_toko = LOWER(TRIM(o.nama_toko))
            WHERE cm.sales_channel_id IS NULL
        """)
        eligible = _scalar(conn, """
            SELECT COUNT(DISTINCT (
                COALESCE(NULLIF(TRIM(o.nomor_pesanan),'nan'), NULLIF(TRIM(o.id_pesanan),'nan')),
                cm.sales_channel_id
            ))
            FROM staging.stg_lazada_income o
            LEFT JOIN _tmp_channel_map cm ON cm.nama_toko = LOWER(TRIM(o.nama_toko))
            WHERE cm.sales_channel_id IS NOT NULL
              AND COALESCE(NULLIF(TRIM(o.nomor_pesanan),'nan'), NULLIF(TRIM(o.id_pesanan),'nan')) IS NOT NULL
              AND NULLIF(REPLACE(TRIM(o.jumlah_termasuk_pajak),',',''),'nan') IS NOT NULL
        """)
        duplicate_grain = _scalar(conn, """
            SELECT COALESCE(SUM(cnt - 1), 0)
            FROM (
                SELECT COUNT(*) AS cnt
                FROM staging.stg_lazada_income o
                LEFT JOIN _tmp_channel_map cm ON cm.nama_toko = LOWER(TRIM(o.nama_toko))
                WHERE cm.sales_channel_id IS NOT NULL
                  AND COALESCE(NULLIF(TRIM(o.nomor_pesanan),'nan'), NULLIF(TRIM(o.id_pesanan),'nan')) IS NOT NULL
                  AND NULLIF(REPLACE(TRIM(o.jumlah_termasuk_pajak),',',''),'nan') IS NOT NULL
                GROUP BY COALESCE(NULLIF(TRIM(o.nomor_pesanan),'nan'), NULLIF(TRIM(o.id_pesanan),'nan')), cm.sales_channel_id
                HAVING COUNT(*) > 1
            ) d
        """)
    else:
        logger.warning(f"Marketplace '{marketplace}' tidak dikenal untuk pre-audit {module_name}.")
        return

    _audit_count(conn, module_name, marketplace, "staging_total_rows", total, "Total baris staging.")
    _audit_count(conn, module_name, marketplace, "null_order_id", null_order, "Baris tanpa order ID.", _severity_for_skipped(null_order))
    _audit_count(conn, module_name, marketplace, "unmapped_channel", unmapped_channel, "Baris dengan nama toko/channel tidak termapping.", _severity_for_skipped(unmapped_channel))
    _audit_count(conn, module_name, marketplace, "eligible_grains", eligible, "Estimasi grain unik yang eligible masuk/update public.", _severity_for_zero_eligible(total, eligible))
    _audit_count(conn, module_name, marketplace, "duplicate_staging_grain", duplicate_grain, "Baris ekstra dengan grain staging yang sama.", _severity_for_skipped(duplicate_grain))


def _values_sql(mapping):
    return ",\n".join(
        f"({fee_type_id}, NULLIF(NULLIF(TRIM(o.{column_name}), 'nan'), '')::NUMERIC)"
        for column_name, fee_type_id in mapping.items()
    )


def _shopee_service_fee_values_sql():
    return """
        (102, NULLIF(NULLIF(TRIM(o.biaya_pembayaran),'nan'),'')::NUMERIC),
        (106, COALESCE(NULLIF(NULLIF(TRIM(o.biaya_layanan_gratis_ongkir_xtra),'nan'),'')::NUMERIC,0)
            + COALESCE(NULLIF(NULLIF(TRIM(o.biaya_layanan_gratis_ongkir_xtra_2),'nan'),'')::NUMERIC,0)),
        (107, NULLIF(NULLIF(TRIM(o.biaya_layanan_promo_xtra),'nan'),'')::NUMERIC),
        (108, COALESCE(NULLIF(NULLIF(TRIM(o.biaya_layanan_cashback_xtra),'nan'),'')::NUMERIC,0)
            + COALESCE(NULLIF(NULLIF(TRIM(o.biaya_layanan_cashbackxtra),'nan'),'')::NUMERIC,0)),
        (109, NULLIF(NULLIF(TRIM(o.biaya_program_shopee_live_xtra),'nan'),'')::NUMERIC),
        (110, COALESCE(NULLIF(NULLIF(TRIM(o.biaya_campaign_1_1),'nan'),'')::NUMERIC,0)
            + COALESCE(NULLIF(NULLIF(TRIM(o.biaya_campaign_2_2),'nan'),'')::NUMERIC,0)
            + COALESCE(NULLIF(NULLIF(TRIM(o.biaya_campaign_3_3),'nan'),'')::NUMERIC,0)
            + COALESCE(NULLIF(NULLIF(TRIM(o.biaya_campaign_4_4),'nan'),'')::NUMERIC,0)
            + COALESCE(NULLIF(NULLIF(TRIM(o.biaya_campaign_5_5),'nan'),'')::NUMERIC,0)
            + COALESCE(NULLIF(NULLIF(TRIM(o.biaya_campaign_6_6),'nan'),'')::NUMERIC,0)
            + COALESCE(NULLIF(NULLIF(TRIM(o.biaya_campaign_7_7),'nan'),'')::NUMERIC,0)
            + COALESCE(NULLIF(NULLIF(TRIM(o.biaya_campaign_8_8),'nan'),'')::NUMERIC,0)
            + COALESCE(NULLIF(NULLIF(TRIM(o.biaya_campaign_9_9),'nan'),'')::NUMERIC,0)
            + COALESCE(NULLIF(NULLIF(TRIM(o.biaya_campaign_10_10),'nan'),'')::NUMERIC,0)
            + COALESCE(NULLIF(NULLIF(TRIM(o.biaya_campaign_11_11),'nan'),'')::NUMERIC,0)
            + COALESCE(NULLIF(NULLIF(TRIM(o.biaya_campaign_12_12),'nan'),'')::NUMERIC,0))
    """


def pre_audit_fact_order_fees(conn, marketplace):
    module_name = "fact_order_fees"

    if marketplace == "tiktok_tokopedia":
        fee_values = _values_sql(TIKTOK_INCOME_FEE_COLS)
        total = _scalar(conn, "SELECT COUNT(*) FROM staging.stg_tiktok_tokopedia_income")
        null_order = _scalar(conn, """
            SELECT COUNT(*) FROM staging.stg_tiktok_tokopedia_income
            WHERE NULLIF(TRIM(order_adjustment_id), 'nan') IS NULL
        """)
        unmapped_channel = _scalar(conn, """
            SELECT COUNT(*)
            FROM staging.stg_tiktok_tokopedia_income o
            LEFT JOIN _tmp_channel_map cm ON cm.nama_toko = LOWER(TRIM(o.nama_toko))
            WHERE cm.sales_channel_id IS NULL
        """)
        eligible = _scalar(conn, f"""
            SELECT COUNT(DISTINCT (o.order_adjustment_id, u.fee_type_id, cm.sales_channel_id))
            FROM staging.stg_tiktok_tokopedia_income o
            LEFT JOIN _tmp_channel_map cm ON cm.nama_toko = LOWER(TRIM(o.nama_toko))
            CROSS JOIN LATERAL (VALUES {fee_values}) AS u(fee_type_id, fee_value)
            WHERE cm.sales_channel_id IS NOT NULL
              AND o.type = 'Order'
              AND NULLIF(TRIM(o.order_adjustment_id),'nan') IS NOT NULL
              AND u.fee_value IS NOT NULL AND u.fee_value <> 0
        """)
        duplicate_grain = _scalar(conn, f"""
            SELECT COALESCE(SUM(cnt - 1), 0)
            FROM (
                SELECT COUNT(*) AS cnt
                FROM staging.stg_tiktok_tokopedia_income o
                LEFT JOIN _tmp_channel_map cm ON cm.nama_toko = LOWER(TRIM(o.nama_toko))
                CROSS JOIN LATERAL (VALUES {fee_values}) AS u(fee_type_id, fee_value)
                WHERE cm.sales_channel_id IS NOT NULL
                  AND o.type = 'Order'
                  AND NULLIF(TRIM(o.order_adjustment_id),'nan') IS NOT NULL
                  AND u.fee_value IS NOT NULL AND u.fee_value <> 0
                GROUP BY o.order_adjustment_id, u.fee_type_id, cm.sales_channel_id
                HAVING COUNT(*) > 1
            ) d
        """)
        unmapped_fee = 0

    elif marketplace == "shopee":
        main_fee_values = _values_sql(SHOPEE_INCOME_MAIN_FEE_COLS)
        service_fee_values = _shopee_service_fee_values_sql()
        total = _scalar(conn, """
            SELECT
                (SELECT COUNT(*) FROM staging.stg_shopee_income_main)
              + (SELECT COUNT(*) FROM staging.stg_shopee_income_service_fee)
              + (SELECT COUNT(*) FROM staging.stg_shopee_income_adjustment)
        """)
        null_order = _scalar(conn, """
            SELECT
                (SELECT COUNT(*) FROM staging.stg_shopee_income_main
                 WHERE NULLIF(TRIM(no_pesanan), 'nan') IS NULL)
              + (SELECT COUNT(*) FROM staging.stg_shopee_income_service_fee
                 WHERE NULLIF(TRIM(no_pesanan), 'nan') IS NULL)
              + (SELECT COUNT(*) FROM staging.stg_shopee_income_adjustment
                 WHERE NULLIF(TRIM(no_pesanan_terhubung), 'nan') IS NULL)
        """)
        unmapped_channel = _scalar(conn, """
            SELECT
                (SELECT COUNT(*) FROM staging.stg_shopee_income_main o
                 LEFT JOIN _tmp_channel_map cm ON cm.nama_toko = LOWER(TRIM(o.nama_toko))
                 WHERE cm.sales_channel_id IS NULL)
              + (SELECT COUNT(*) FROM staging.stg_shopee_income_service_fee o
                 LEFT JOIN _tmp_channel_map cm ON cm.nama_toko = LOWER(TRIM(o.nama_toko))
                 WHERE cm.sales_channel_id IS NULL)
              + (SELECT COUNT(*) FROM staging.stg_shopee_income_adjustment o
                 LEFT JOIN _tmp_channel_map cm ON cm.nama_toko = LOWER(TRIM(o.nama_toko))
                 WHERE cm.sales_channel_id IS NULL)
        """)
        eligible_main = _scalar(conn, f"""
            SELECT COUNT(DISTINCT (o.no_pesanan, u.fee_type_id, cm.sales_channel_id))
            FROM staging.stg_shopee_income_main o
            LEFT JOIN _tmp_channel_map cm ON cm.nama_toko = LOWER(TRIM(o.nama_toko))
            CROSS JOIN LATERAL (VALUES {main_fee_values}) AS u(fee_type_id, fee_value)
            WHERE cm.sales_channel_id IS NOT NULL
              AND NULLIF(TRIM(o.no_pesanan),'nan') IS NOT NULL
              AND u.fee_value IS NOT NULL AND u.fee_value <> 0
        """)
        eligible_sf = _scalar(conn, f"""
            SELECT COUNT(DISTINCT (o.no_pesanan, u.fee_type_id, cm.sales_channel_id))
            FROM staging.stg_shopee_income_service_fee o
            LEFT JOIN _tmp_channel_map cm ON cm.nama_toko = LOWER(TRIM(o.nama_toko))
            CROSS JOIN LATERAL (VALUES {service_fee_values}) AS u(fee_type_id, fee_value)
            WHERE cm.sales_channel_id IS NOT NULL
              AND NULLIF(TRIM(o.no_pesanan),'nan') IS NOT NULL
              AND u.fee_value IS NOT NULL AND u.fee_value <> 0
        """)
        eligible_adj = _scalar(conn, """
            SELECT COUNT(DISTINCT (NULLIF(TRIM(o.no_pesanan_terhubung),'nan'), ft.fee_type_id, cm.sales_channel_id))
            FROM staging.stg_shopee_income_adjustment o
            LEFT JOIN _tmp_channel_map cm ON cm.nama_toko = LOWER(TRIM(o.nama_toko))
            JOIN public.dim_fee_type ft
                ON ft.fee_name = TRIM(o.tipe_penyesuaian_deskripsi)
               AND ft.marketplace_name = 'Shopee'
            WHERE cm.sales_channel_id IS NOT NULL
              AND NULLIF(TRIM(o.no_pesanan_terhubung),'nan') IS NOT NULL
              AND NULLIF(NULLIF(TRIM(o.biaya_penyesuaian),'nan'),'') IS NOT NULL
              AND NULLIF(NULLIF(TRIM(o.biaya_penyesuaian),'nan'),'')::NUMERIC <> 0
        """)
        eligible = eligible_main + eligible_sf + eligible_adj
        duplicate_grain = _scalar(conn, f"""
            WITH emitted AS (
                SELECT o.no_pesanan AS order_id, u.fee_type_id, cm.sales_channel_id
                FROM staging.stg_shopee_income_main o
                LEFT JOIN _tmp_channel_map cm ON cm.nama_toko = LOWER(TRIM(o.nama_toko))
                CROSS JOIN LATERAL (VALUES {main_fee_values}) AS u(fee_type_id, fee_value)
                WHERE cm.sales_channel_id IS NOT NULL
                  AND NULLIF(TRIM(o.no_pesanan),'nan') IS NOT NULL
                  AND u.fee_value IS NOT NULL AND u.fee_value <> 0
                UNION ALL
                SELECT o.no_pesanan AS order_id, u.fee_type_id, cm.sales_channel_id
                FROM staging.stg_shopee_income_service_fee o
                LEFT JOIN _tmp_channel_map cm ON cm.nama_toko = LOWER(TRIM(o.nama_toko))
                CROSS JOIN LATERAL (VALUES {service_fee_values}) AS u(fee_type_id, fee_value)
                WHERE cm.sales_channel_id IS NOT NULL
                  AND NULLIF(TRIM(o.no_pesanan),'nan') IS NOT NULL
                  AND u.fee_value IS NOT NULL AND u.fee_value <> 0
                UNION ALL
                SELECT NULLIF(TRIM(o.no_pesanan_terhubung),'nan') AS order_id, ft.fee_type_id, cm.sales_channel_id
                FROM staging.stg_shopee_income_adjustment o
                LEFT JOIN _tmp_channel_map cm ON cm.nama_toko = LOWER(TRIM(o.nama_toko))
                JOIN public.dim_fee_type ft
                    ON ft.fee_name = TRIM(o.tipe_penyesuaian_deskripsi)
                   AND ft.marketplace_name = 'Shopee'
                WHERE cm.sales_channel_id IS NOT NULL
                  AND NULLIF(TRIM(o.no_pesanan_terhubung),'nan') IS NOT NULL
                  AND NULLIF(NULLIF(TRIM(o.biaya_penyesuaian),'nan'),'') IS NOT NULL
                  AND NULLIF(NULLIF(TRIM(o.biaya_penyesuaian),'nan'),'')::NUMERIC <> 0
            )
            SELECT COALESCE(SUM(cnt - 1), 0)
            FROM (
                SELECT COUNT(*) AS cnt
                FROM emitted
                GROUP BY order_id, fee_type_id, sales_channel_id
                HAVING COUNT(*) > 1
            ) d
        """)
        unmapped_fee = _scalar(conn, """
            SELECT COUNT(*)
            FROM staging.stg_shopee_income_adjustment o
            LEFT JOIN public.dim_fee_type ft
                ON ft.fee_name = TRIM(o.tipe_penyesuaian_deskripsi)
               AND ft.marketplace_name = 'Shopee'
            WHERE ft.fee_type_id IS NULL
              AND NULLIF(NULLIF(TRIM(o.biaya_penyesuaian),'nan'),'') IS NOT NULL
              AND NULLIF(NULLIF(TRIM(o.biaya_penyesuaian),'nan'),'')::NUMERIC <> 0
        """)

    elif marketplace == "lazada":
        total = _scalar(conn, "SELECT COUNT(*) FROM staging.stg_lazada_income")
        null_order = _scalar(conn, """
            SELECT COUNT(*) FROM staging.stg_lazada_income
            WHERE COALESCE(NULLIF(TRIM(nomor_pesanan), 'nan'), NULLIF(TRIM(id_pesanan), 'nan')) IS NULL
        """)
        unmapped_channel = _scalar(conn, """
            SELECT COUNT(*)
            FROM staging.stg_lazada_income o
            LEFT JOIN _tmp_channel_map cm ON cm.nama_toko = LOWER(TRIM(o.nama_toko))
            WHERE cm.sales_channel_id IS NULL
        """)
        unmapped_fee = _scalar(conn, """
            SELECT COUNT(*)
            FROM staging.stg_lazada_income o
            LEFT JOIN public.dim_fee_type ft
                ON ft.fee_name = TRIM(o.nama_biaya) AND ft.marketplace_name = 'Lazada'
            WHERE ft.fee_type_id IS NULL
              AND NULLIF(REPLACE(TRIM(o.jumlah_termasuk_pajak),',',''),'nan') IS NOT NULL
              AND NULLIF(REPLACE(TRIM(o.jumlah_termasuk_pajak),',',''),'nan')::NUMERIC <> 0
        """)
        eligible = _scalar(conn, """
            SELECT COUNT(DISTINCT (
                COALESCE(NULLIF(TRIM(o.nomor_pesanan),'nan'), NULLIF(TRIM(o.id_pesanan),'nan')),
                ft.fee_type_id,
                cm.sales_channel_id
            ))
            FROM staging.stg_lazada_income o
            LEFT JOIN _tmp_channel_map cm ON cm.nama_toko = LOWER(TRIM(o.nama_toko))
            JOIN public.dim_fee_type ft
                ON ft.fee_name = TRIM(o.nama_biaya) AND ft.marketplace_name = 'Lazada'
            WHERE cm.sales_channel_id IS NOT NULL
              AND COALESCE(NULLIF(TRIM(o.nomor_pesanan),'nan'), NULLIF(TRIM(o.id_pesanan),'nan')) IS NOT NULL
              AND NULLIF(REPLACE(TRIM(o.jumlah_termasuk_pajak),',',''),'nan') IS NOT NULL
              AND NULLIF(REPLACE(TRIM(o.jumlah_termasuk_pajak),',',''),'nan')::NUMERIC <> 0
        """)
        duplicate_grain = _scalar(conn, """
            WITH emitted AS (
                SELECT
                    COALESCE(NULLIF(TRIM(o.nomor_pesanan),'nan'), NULLIF(TRIM(o.id_pesanan),'nan')) AS order_id,
                    ft.fee_type_id,
                    cm.sales_channel_id
                FROM staging.stg_lazada_income o
                LEFT JOIN _tmp_channel_map cm ON cm.nama_toko = LOWER(TRIM(o.nama_toko))
                JOIN public.dim_fee_type ft
                    ON ft.fee_name = TRIM(o.nama_biaya) AND ft.marketplace_name = 'Lazada'
                WHERE cm.sales_channel_id IS NOT NULL
                  AND COALESCE(NULLIF(TRIM(o.nomor_pesanan),'nan'), NULLIF(TRIM(o.id_pesanan),'nan')) IS NOT NULL
                  AND NULLIF(REPLACE(TRIM(o.jumlah_termasuk_pajak),',',''),'nan') IS NOT NULL
                  AND NULLIF(REPLACE(TRIM(o.jumlah_termasuk_pajak),',',''),'nan')::NUMERIC <> 0
            )
            SELECT COALESCE(SUM(cnt - 1), 0)
            FROM (
                SELECT COUNT(*) AS cnt
                FROM emitted
                GROUP BY order_id, fee_type_id, sales_channel_id
                HAVING COUNT(*) > 1
            ) d
        """)
    else:
        logger.warning(f"Marketplace '{marketplace}' tidak dikenal untuk pre-audit {module_name}.")
        return

    _audit_count(conn, module_name, marketplace, "staging_total_rows", total, "Total baris staging.")
    _audit_count(conn, module_name, marketplace, "null_order_id", null_order, "Baris tanpa order ID.", _severity_for_skipped(null_order))
    _audit_count(conn, module_name, marketplace, "unmapped_channel", unmapped_channel, "Baris dengan nama toko/channel tidak termapping.", _severity_for_skipped(unmapped_channel))
    _audit_count(conn, module_name, marketplace, "unmapped_fee_type", unmapped_fee, "Baris dengan fee type tidak termapping.", _severity_for_skipped(unmapped_fee))
    _audit_count(conn, module_name, marketplace, "eligible_grains", eligible, "Estimasi grain unik yang eligible masuk/update public.", _severity_for_zero_eligible(total, eligible))
    _audit_count(conn, module_name, marketplace, "duplicate_staging_grain", duplicate_grain, "Baris ekstra dengan grain staging yang sama.", _severity_for_skipped(duplicate_grain))


def _audit_common_grain(
    conn,
    module_name,
    marketplace,
    total_sql,
    null_order_sql,
    unmapped_channel_sql,
    eligible_sql,
    duplicate_sql,
    extra_checks=None,
):
    total = _scalar(conn, total_sql)
    null_order = _scalar(conn, null_order_sql)
    unmapped_channel = _scalar(conn, unmapped_channel_sql)
    eligible = _scalar(conn, eligible_sql)
    duplicate_grain = _scalar(conn, duplicate_sql)

    _audit_count(conn, module_name, marketplace, "staging_total_rows", total, "Total baris staging.")
    _audit_count(conn, module_name, marketplace, "null_order_id", null_order, "Baris tanpa order ID.", _severity_for_skipped(null_order))
    _audit_count(conn, module_name, marketplace, "unmapped_channel", unmapped_channel, "Baris dengan nama toko/channel tidak termapping.", _severity_for_skipped(unmapped_channel))

    for check_name, row_count, message in extra_checks or []:
        _audit_count(conn, module_name, marketplace, check_name, row_count, message, _severity_for_skipped(row_count))

    _audit_count(conn, module_name, marketplace, "eligible_grains", eligible, "Estimasi grain unik yang eligible masuk/update public.", _severity_for_zero_eligible(total, eligible))
    _audit_count(conn, module_name, marketplace, "duplicate_staging_grain", duplicate_grain, "Baris ekstra dengan grain staging yang sama.", _severity_for_skipped(duplicate_grain))


def pre_audit_fact_fulfillment_logistics(conn, marketplace):
    module_name = "fact_fulfillment_logistics"

    if marketplace == "shopee":
        unmapped_shipping = _scalar(conn, """
            SELECT COUNT(*)
            FROM staging.stg_shopee_orders o
            LEFT JOIN _tmp_channel_map cm ON cm.nama_toko = LOWER(TRIM(o.nama_toko))
            LEFT JOIN _tmp_shipping_map sm ON sm.provider = CASE
                WHEN o.opsi_pengiriman LIKE '%-%'
                THEN TRIM(SUBSTRING(o.opsi_pengiriman FROM STRPOS(o.opsi_pengiriman, '-') + 1))
                ELSE TRIM(o.opsi_pengiriman)
            END
            WHERE cm.sales_channel_id IS NOT NULL
              AND sm.service_id IS NULL
              AND NULLIF(TRIM(o.opsi_pengiriman), 'nan') IS NOT NULL
        """)
        unmapped_warehouse = _scalar(conn, """
            SELECT COUNT(*)
            FROM staging.stg_shopee_orders o
            LEFT JOIN _tmp_channel_map cm ON cm.nama_toko = LOWER(TRIM(o.nama_toko))
            LEFT JOIN _tmp_warehouse_map wm ON wm.raw_name = LOWER(TRIM(o.nama_gudang))
            WHERE cm.sales_channel_id IS NOT NULL
              AND wm.warehouse_id IS NULL
              AND NULLIF(TRIM(o.nama_gudang), 'nan') IS NOT NULL
        """)
        _audit_common_grain(
            conn,
            module_name,
            marketplace,
            "SELECT COUNT(*) FROM staging.stg_shopee_orders",
            """
                SELECT COUNT(*) FROM staging.stg_shopee_orders
                WHERE NULLIF(TRIM(no_pesanan), 'nan') IS NULL
            """,
            """
                SELECT COUNT(*)
                FROM staging.stg_shopee_orders o
                LEFT JOIN _tmp_channel_map cm ON cm.nama_toko = LOWER(TRIM(o.nama_toko))
                WHERE cm.sales_channel_id IS NULL
            """,
            """
                SELECT COUNT(DISTINCT (o.no_pesanan, cm.sales_channel_id))
                FROM staging.stg_shopee_orders o
                LEFT JOIN _tmp_channel_map cm ON cm.nama_toko = LOWER(TRIM(o.nama_toko))
                WHERE cm.sales_channel_id IS NOT NULL
                  AND NULLIF(TRIM(o.no_pesanan), 'nan') IS NOT NULL
            """,
            """
                SELECT COALESCE(SUM(cnt - 1), 0)
                FROM (
                    SELECT COUNT(*) AS cnt
                    FROM staging.stg_shopee_orders o
                    LEFT JOIN _tmp_channel_map cm ON cm.nama_toko = LOWER(TRIM(o.nama_toko))
                    WHERE cm.sales_channel_id IS NOT NULL
                      AND NULLIF(TRIM(o.no_pesanan), 'nan') IS NOT NULL
                    GROUP BY o.no_pesanan, cm.sales_channel_id
                    HAVING COUNT(*) > 1
                ) d
            """,
            [
                ("unmapped_shipping_service", unmapped_shipping, "Baris dengan jasa kirim tidak termapping."),
                ("unmapped_warehouse", unmapped_warehouse, "Baris dengan warehouse tidak termapping."),
            ],
        )

    elif marketplace == "tiktok_tokopedia":
        unmapped_shipping = _scalar(conn, """
            SELECT COUNT(*)
            FROM staging.stg_tiktok_tokopedia_orders o
            LEFT JOIN _tmp_channel_map cm ON cm.nama_toko = LOWER(TRIM(o.nama_toko))
            LEFT JOIN _tmp_shipping_map sm_exact
                ON sm_exact.provider = TRIM(o.shipping_provider_name)
               AND sm_exact.delivery_option = TRIM(o.delivery_option)
            LEFT JOIN _tmp_shipping_map sm_wild
                ON sm_wild.provider = TRIM(o.shipping_provider_name)
               AND sm_wild.delivery_option = '_'
            WHERE cm.sales_channel_id IS NOT NULL
              AND COALESCE(sm_exact.service_id, sm_wild.service_id) IS NULL
              AND NULLIF(TRIM(o.shipping_provider_name), 'nan') IS NOT NULL
        """)
        unmapped_warehouse = _scalar(conn, """
            SELECT COUNT(*)
            FROM staging.stg_tiktok_tokopedia_orders o
            LEFT JOIN _tmp_channel_map cm ON cm.nama_toko = LOWER(TRIM(o.nama_toko))
            LEFT JOIN _tmp_warehouse_map wm ON wm.raw_name = LOWER(TRIM(o.warehouse_name))
            WHERE cm.sales_channel_id IS NOT NULL
              AND wm.warehouse_id IS NULL
              AND NULLIF(TRIM(o.warehouse_name), 'nan') IS NOT NULL
        """)
        _audit_common_grain(
            conn,
            module_name,
            marketplace,
            "SELECT COUNT(*) FROM staging.stg_tiktok_tokopedia_orders",
            """
                SELECT COUNT(*) FROM staging.stg_tiktok_tokopedia_orders
                WHERE NULLIF(TRIM(order_id), 'nan') IS NULL
            """,
            """
                SELECT COUNT(*)
                FROM staging.stg_tiktok_tokopedia_orders o
                LEFT JOIN _tmp_channel_map cm ON cm.nama_toko = LOWER(TRIM(o.nama_toko))
                WHERE cm.sales_channel_id IS NULL
            """,
            """
                SELECT COUNT(DISTINCT (o.order_id, cm.sales_channel_id))
                FROM staging.stg_tiktok_tokopedia_orders o
                LEFT JOIN _tmp_channel_map cm ON cm.nama_toko = LOWER(TRIM(o.nama_toko))
                WHERE cm.sales_channel_id IS NOT NULL
                  AND NULLIF(TRIM(o.order_id), 'nan') IS NOT NULL
            """,
            """
                SELECT COALESCE(SUM(cnt - 1), 0)
                FROM (
                    SELECT COUNT(*) AS cnt
                    FROM staging.stg_tiktok_tokopedia_orders o
                    LEFT JOIN _tmp_channel_map cm ON cm.nama_toko = LOWER(TRIM(o.nama_toko))
                    WHERE cm.sales_channel_id IS NOT NULL
                      AND NULLIF(TRIM(o.order_id), 'nan') IS NOT NULL
                    GROUP BY o.order_id, cm.sales_channel_id
                    HAVING COUNT(*) > 1
                ) d
            """,
            [
                ("unmapped_shipping_service", unmapped_shipping, "Baris dengan jasa kirim tidak termapping."),
                ("unmapped_warehouse", unmapped_warehouse, "Baris dengan warehouse tidak termapping."),
            ],
        )

    elif marketplace == "lazada":
        unmapped_shipping = _scalar(conn, """
            SELECT COUNT(*)
            FROM staging.stg_lazada_orders o
            LEFT JOIN _tmp_channel_map cm ON cm.nama_toko = LOWER(TRIM(o.nama_toko))
            LEFT JOIN _tmp_shipping_map sm ON sm.provider = TRIM(o.shipping_provider)
            WHERE cm.sales_channel_id IS NOT NULL
              AND sm.service_id IS NULL
              AND NULLIF(TRIM(o.shipping_provider), 'nan') IS NOT NULL
        """)
        unmapped_warehouse = _scalar(conn, """
            SELECT COUNT(*)
            FROM staging.stg_lazada_orders o
            LEFT JOIN _tmp_channel_map cm ON cm.nama_toko = LOWER(TRIM(o.nama_toko))
            LEFT JOIN _tmp_warehouse_map wm ON wm.raw_name = LOWER(TRIM(o.warehouse))
            WHERE cm.sales_channel_id IS NOT NULL
              AND wm.warehouse_id IS NULL
              AND NULLIF(TRIM(o.warehouse), 'nan') IS NOT NULL
        """)
        _audit_common_grain(
            conn,
            module_name,
            marketplace,
            "SELECT COUNT(*) FROM staging.stg_lazada_orders",
            """
                SELECT COUNT(*) FROM staging.stg_lazada_orders
                WHERE NULLIF(TRIM(order_number), 'nan') IS NULL
            """,
            """
                SELECT COUNT(*)
                FROM staging.stg_lazada_orders o
                LEFT JOIN _tmp_channel_map cm ON cm.nama_toko = LOWER(TRIM(o.nama_toko))
                WHERE cm.sales_channel_id IS NULL
            """,
            """
                SELECT COUNT(DISTINCT (o.order_number, cm.sales_channel_id))
                FROM staging.stg_lazada_orders o
                LEFT JOIN _tmp_channel_map cm ON cm.nama_toko = LOWER(TRIM(o.nama_toko))
                WHERE cm.sales_channel_id IS NOT NULL
                  AND NULLIF(TRIM(o.order_number), 'nan') IS NOT NULL
            """,
            """
                SELECT COALESCE(SUM(cnt - 1), 0)
                FROM (
                    SELECT COUNT(*) AS cnt
                    FROM staging.stg_lazada_orders o
                    LEFT JOIN _tmp_channel_map cm ON cm.nama_toko = LOWER(TRIM(o.nama_toko))
                    WHERE cm.sales_channel_id IS NOT NULL
                      AND NULLIF(TRIM(o.order_number), 'nan') IS NOT NULL
                    GROUP BY o.order_number, cm.sales_channel_id
                    HAVING COUNT(*) > 1
                ) d
            """,
            [
                ("unmapped_shipping_service", unmapped_shipping, "Baris dengan jasa kirim tidak termapping."),
                ("unmapped_warehouse", unmapped_warehouse, "Baris dengan warehouse tidak termapping."),
            ],
        )

    else:
        logger.warning(f"Marketplace '{marketplace}' tidak dikenal untuk pre-audit {module_name}.")


def pre_audit_fact_balance_transaction(conn, marketplace):
    module_name = "fact_balance_transaction"

    if marketplace == "shopee":
        invalid_date = _scalar(conn, """
            SELECT COUNT(*) FROM staging.stg_shopee_report
            WHERE TRIM(tanggal_transaksi) !~ '^\\d{4}-\\d{2}-\\d{2}'
        """)
        null_amount = _scalar(conn, """
            SELECT COUNT(*) FROM staging.stg_shopee_report
            WHERE NULLIF(TRIM(jumlah), 'nan') IS NULL
        """)
        _audit_common_grain(
            conn,
            module_name,
            marketplace,
            "SELECT COUNT(*) FROM staging.stg_shopee_report",
            """
                SELECT COUNT(*) FROM staging.stg_shopee_report
                WHERE NULLIF(TRIM(no_pesanan), 'nan') IS NULL OR TRIM(no_pesanan) = '-'
            """,
            """
                SELECT COUNT(*)
                FROM staging.stg_shopee_report r
                LEFT JOIN _tmp_channel_map cm ON cm.nama_toko = LOWER(TRIM(r.nama_toko))
                WHERE cm.sales_channel_id IS NULL
            """,
            """
                SELECT COUNT(DISTINCT (
                        CASE WHEN TRIM(r.tipe_transaksi) = 'Penghasilan dari Pesanan'
                                  AND NULLIF(TRIM(r.no_pesanan), 'nan') IS NOT NULL
                                  AND TRIM(r.no_pesanan) != '-'
                             THEN TRIM(r.no_pesanan)
                             ELSE CONCAT_WS('|', TRIM(r.tanggal_transaksi), TRIM(r.tipe_transaksi), TRIM(r.jumlah), TRIM(r.deskripsi))
                        END,
                        cm.sales_channel_id
                ))
                FROM staging.stg_shopee_report r
                LEFT JOIN _tmp_channel_map cm ON cm.nama_toko = LOWER(TRIM(r.nama_toko))
                WHERE cm.sales_channel_id IS NOT NULL
                  AND NULLIF(TRIM(r.jumlah), 'nan') IS NOT NULL
                  AND TRIM(r.tanggal_transaksi) ~ '^\\d{4}-\\d{2}-\\d{2}'
            """,
            """
                SELECT COALESCE(SUM(cnt - 1), 0)
                FROM (
                    SELECT COUNT(*) AS cnt
                    FROM staging.stg_shopee_report r
                    LEFT JOIN _tmp_channel_map cm ON cm.nama_toko = LOWER(TRIM(r.nama_toko))
                    WHERE cm.sales_channel_id IS NOT NULL
                      AND NULLIF(TRIM(r.jumlah), 'nan') IS NOT NULL
                      AND TRIM(r.tanggal_transaksi) ~ '^\\d{4}-\\d{2}-\\d{2}'
                    GROUP BY
                        CASE WHEN TRIM(r.tipe_transaksi) = 'Penghasilan dari Pesanan'
                                  AND NULLIF(TRIM(r.no_pesanan), 'nan') IS NOT NULL
                                  AND TRIM(r.no_pesanan) != '-'
                             THEN TRIM(r.no_pesanan)
                             ELSE CONCAT_WS('|', TRIM(r.tanggal_transaksi), TRIM(r.tipe_transaksi), TRIM(r.jumlah), TRIM(r.deskripsi))
                        END,
                        cm.sales_channel_id
                    HAVING COUNT(*) > 1
                ) d
            """,
            [
                ("invalid_transaction_date", invalid_date, "Baris dengan format tanggal transaksi tidak valid."),
                ("null_amount", null_amount, "Baris tanpa nilai amount/jumlah."),
            ],
        )

    elif marketplace == "tiktok_tokopedia":
        invalid_date = _scalar(conn, """
            SELECT COUNT(*) FROM staging.stg_tiktok_tokopedia_report
            WHERE REPLACE(TRIM(success_time), '/', '-') !~ '^\\d{4}-\\d{2}-\\d{2}'
        """)
        null_amount = _scalar(conn, """
            SELECT COUNT(*) FROM staging.stg_tiktok_tokopedia_report
            WHERE NULLIF(TRIM(amount), 'nan') IS NULL
        """)
        _audit_common_grain(
            conn,
            module_name,
            marketplace,
            "SELECT COUNT(*) FROM staging.stg_tiktok_tokopedia_report",
            """
                SELECT COUNT(*) FROM staging.stg_tiktok_tokopedia_report
                WHERE NULLIF(TRIM(reference_id), 'nan') IS NULL
            """,
            """
                SELECT COUNT(*)
                FROM staging.stg_tiktok_tokopedia_report r
                LEFT JOIN _tmp_channel_map cm ON cm.nama_toko = LOWER(TRIM(r.nama_toko))
                WHERE cm.sales_channel_id IS NULL
            """,
            """
                SELECT COUNT(DISTINCT (
                    TRIM(r.reference_id),
                    CASE WHEN TRIM(r.type) = 'Withdrawal' THEN 0 ELSE cm.sales_channel_id END
                ))
                FROM staging.stg_tiktok_tokopedia_report r
                LEFT JOIN _tmp_channel_map cm ON cm.nama_toko = LOWER(TRIM(r.nama_toko))
                WHERE cm.sales_channel_id IS NOT NULL
                  AND REPLACE(TRIM(r.success_time), '/', '-') ~ '^\\d{4}-\\d{2}-\\d{2}'
                  AND NULLIF(TRIM(r.reference_id), 'nan') IS NOT NULL
            """,
            """
                SELECT COALESCE(SUM(cnt - 1), 0)
                FROM (
                    SELECT COUNT(*) AS cnt
                    FROM staging.stg_tiktok_tokopedia_report r
                    LEFT JOIN _tmp_channel_map cm ON cm.nama_toko = LOWER(TRIM(r.nama_toko))
                    WHERE cm.sales_channel_id IS NOT NULL
                      AND REPLACE(TRIM(r.success_time), '/', '-') ~ '^\\d{4}-\\d{2}-\\d{2}'
                      AND NULLIF(TRIM(r.reference_id), 'nan') IS NOT NULL
                    GROUP BY TRIM(r.reference_id), CASE WHEN TRIM(r.type) = 'Withdrawal' THEN 0 ELSE cm.sales_channel_id END
                    HAVING COUNT(*) > 1
                ) d
            """,
            [
                ("invalid_transaction_date", invalid_date, "Baris dengan format tanggal transaksi tidak valid."),
                ("null_amount", null_amount, "Baris tanpa nilai amount/jumlah."),
            ],
        )

    elif marketplace == "lazada":
        invalid_date = _scalar(conn, """
            SELECT COUNT(*) FROM staging.stg_lazada_report
            WHERE TRIM(transaction_time) !~ '^\\d{2} [A-Za-z]{3} \\d{4}'
        """)
        null_amount = _scalar(conn, """
            SELECT COUNT(*) FROM staging.stg_lazada_report
            WHERE NULLIF(REPLACE(TRIM(amount), ',', ''), 'nan') IS NULL
        """)
        _audit_common_grain(
            conn,
            module_name,
            marketplace,
            "SELECT COUNT(*) FROM staging.stg_lazada_report",
            """
                SELECT COUNT(*) FROM staging.stg_lazada_report
                WHERE NULLIF(TRIM(transaction_number), 'nan') IS NULL
            """,
            """
                SELECT COUNT(*)
                FROM staging.stg_lazada_report r
                LEFT JOIN _tmp_channel_map cm ON cm.nama_toko = LOWER(TRIM(r.nama_toko))
                WHERE cm.sales_channel_id IS NULL
            """,
            """
                SELECT COUNT(DISTINCT (TRIM(r.transaction_number), cm.sales_channel_id))
                FROM staging.stg_lazada_report r
                LEFT JOIN _tmp_channel_map cm ON cm.nama_toko = LOWER(TRIM(r.nama_toko))
                WHERE cm.sales_channel_id IS NOT NULL
                  AND TRIM(r.transaction_time) ~ '^\\d{2} [A-Za-z]{3} \\d{4}'
                  AND NULLIF(TRIM(r.transaction_number), 'nan') IS NOT NULL
            """,
            """
                SELECT COALESCE(SUM(cnt - 1), 0)
                FROM (
                    SELECT COUNT(*) AS cnt
                    FROM staging.stg_lazada_report r
                    LEFT JOIN _tmp_channel_map cm ON cm.nama_toko = LOWER(TRIM(r.nama_toko))
                    WHERE cm.sales_channel_id IS NOT NULL
                      AND TRIM(r.transaction_time) ~ '^\\d{2} [A-Za-z]{3} \\d{4}'
                      AND NULLIF(TRIM(r.transaction_number), 'nan') IS NOT NULL
                    GROUP BY TRIM(r.transaction_number), cm.sales_channel_id
                    HAVING COUNT(*) > 1
                ) d
            """,
            [
                ("invalid_transaction_date", invalid_date, "Baris dengan format tanggal transaksi tidak valid."),
                ("null_amount", null_amount, "Baris tanpa nilai amount/jumlah."),
            ],
        )

    else:
        logger.warning(f"Marketplace '{marketplace}' tidak dikenal untuk pre-audit {module_name}.")


def pre_audit_fact_returns_online(conn, marketplace):
    module_name = "fact_returns_online"

    if marketplace == "shopee":
        return_filter = """
            (
                (NULLIF(TRIM(o.returned_quantity), '0') IS NOT NULL
                 AND NULLIF(TRIM(o.returned_quantity), 'nan') IS NOT NULL)
                OR o.status_pembatalan_pengembalian IS NOT NULL
            )
        """
        table_sql = "staging.stg_shopee_orders"
        order_col = "o.no_pesanan"
        sku_expr = "COALESCE(NULLIF(TRIM(o.nomor_referensi_sku),'nan'), NULLIF(TRIM(o.sku_induk),'nan'))"
        product_join = f"""
            LEFT JOIN public.dim_sku_alias dsa ON dsa.sku_alias = {sku_expr}
            LEFT JOIN public.dim_product dp ON dp.sku_code = COALESCE(
                (SELECT dp1.sku_code FROM public.dim_product dp1 WHERE dp1.sku_code = (
                    CASE WHEN {sku_expr} ~ '^P[0-9]' THEN 'B'||SUBSTRING({sku_expr},2) ELSE {sku_expr} END
                ) LIMIT 1),
                dsa.sku_code)
        """

    elif marketplace == "tiktok_tokopedia":
        return_filter = "NULLIF(TRIM(o.cancelation_return_type), 'nan') IS NOT NULL"
        table_sql = "staging.stg_tiktok_tokopedia_orders"
        order_col = "o.order_id"
        product_join = """
            LEFT JOIN public.dim_sku_alias dsa ON dsa.sku_alias = NULLIF(TRIM(o.seller_sku), 'nan')
            LEFT JOIN public.dim_product dp ON dp.sku_code = COALESCE(
                (SELECT dp1.sku_code FROM public.dim_product dp1
                 WHERE dp1.sku_code = NULLIF(TRIM(o.seller_sku), 'nan') LIMIT 1),
                dsa.sku_code)
        """

    elif marketplace == "lazada":
        return_filter = """
            (
                TRIM(o.status) IN ('canceled','returned','Package Returned',
                                    'In Transit: Returning to seller',
                                    'Lost by 3PL','Damaged by 3PL','Package scrapped')
                OR o.buyer_failed_delivery_return_initiator LIKE 'only_refund%'
            )
        """
        table_sql = "staging.stg_lazada_orders"
        order_col = "o.order_number"
        product_join = """
            LEFT JOIN public.dim_sku_alias dsa ON dsa.sku_alias = NULLIF(TRIM(o.seller_sku), 'nan')
            LEFT JOIN public.dim_product dp ON dp.sku_code = COALESCE(
                (SELECT dp1.sku_code FROM public.dim_product dp1
                 WHERE dp1.sku_code = NULLIF(TRIM(o.seller_sku), 'nan') LIMIT 1),
                dsa.sku_code)
        """

    else:
        logger.warning(f"Marketplace '{marketplace}' tidak dikenal untuk pre-audit {module_name}.")
        return

    total = _scalar(conn, f"SELECT COUNT(*) FROM {table_sql}")
    candidate_returns = _scalar(conn, f"SELECT COUNT(*) FROM {table_sql} o WHERE {return_filter}")
    null_order = _scalar(conn, f"""
        SELECT COUNT(*) FROM {table_sql} o
        WHERE {return_filter}
          AND NULLIF(TRIM({order_col}), 'nan') IS NULL
    """)
    unmapped_channel = _scalar(conn, f"""
        SELECT COUNT(*)
        FROM {table_sql} o
        LEFT JOIN _tmp_channel_map cm ON cm.nama_toko = LOWER(TRIM(o.nama_toko))
        WHERE {return_filter}
          AND cm.sales_channel_id IS NULL
    """)
    unmapped_product = _scalar(conn, f"""
        SELECT COUNT(*)
        FROM {table_sql} o
        LEFT JOIN _tmp_channel_map cm ON cm.nama_toko = LOWER(TRIM(o.nama_toko))
        {product_join}
        WHERE {return_filter}
          AND cm.sales_channel_id IS NOT NULL
          AND NULLIF(TRIM({order_col}), 'nan') IS NOT NULL
          AND dp.product_id IS NULL
    """)
    eligible = _scalar(conn, f"""
        SELECT COUNT(DISTINCT ({order_col}, dp.product_id, cm.sales_channel_id))
        FROM {table_sql} o
        LEFT JOIN _tmp_channel_map cm ON cm.nama_toko = LOWER(TRIM(o.nama_toko))
        {product_join}
        WHERE {return_filter}
          AND cm.sales_channel_id IS NOT NULL
          AND dp.product_id IS NOT NULL
    """)
    duplicate_grain = _scalar(conn, f"""
        WITH eligible AS (
            SELECT {order_col} AS order_id, dp.product_id, cm.sales_channel_id
            FROM {table_sql} o
            LEFT JOIN _tmp_channel_map cm ON cm.nama_toko = LOWER(TRIM(o.nama_toko))
            {product_join}
            WHERE {return_filter}
              AND cm.sales_channel_id IS NOT NULL
              AND dp.product_id IS NOT NULL
        )
        SELECT COALESCE(SUM(cnt - 1), 0)
        FROM (
            SELECT COUNT(*) AS cnt
            FROM eligible
            GROUP BY order_id, product_id, sales_channel_id
            HAVING COUNT(*) > 1
        ) d
    """)

    _audit_count(conn, module_name, marketplace, "staging_total_rows", total, "Total baris staging.")
    _audit_count(conn, module_name, marketplace, "candidate_return_rows", candidate_returns, "Baris staging yang memenuhi filter retur/cancel.")
    _audit_count(conn, module_name, marketplace, "null_order_id", null_order, "Baris retur/cancel tanpa order ID.", _severity_for_skipped(null_order))
    _audit_count(conn, module_name, marketplace, "unmapped_channel", unmapped_channel, "Baris retur/cancel dengan nama toko/channel tidak termapping.", _severity_for_skipped(unmapped_channel))
    _audit_count(conn, module_name, marketplace, "unmapped_product", unmapped_product, "Baris retur/cancel eligible channel tetapi SKU tidak termapping ke product.", _severity_for_skipped(unmapped_product))
    _audit_count(conn, module_name, marketplace, "eligible_grains", eligible, "Estimasi grain unik retur/cancel yang eligible masuk/update public.", _severity_for_zero_eligible(candidate_returns, eligible))
    _audit_count(conn, module_name, marketplace, "duplicate_staging_grain", duplicate_grain, "Baris ekstra dengan grain staging retur/cancel yang sama.", _severity_for_skipped(duplicate_grain))
