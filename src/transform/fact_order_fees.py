# src/transform/fact_order_fees.py

from sqlalchemy import text
from src.db_config import logger
from src.transform._helpers import setup_maps
from src.transform._checks import check_fact_order_fees_narrow
from src.transform._maps import (
    TIKTOK_INCOME_FEE_COLS, TIKTOK_NON_FEE_COLS,
    SHOPEE_INCOME_MAIN_FEE_COLS, SHOPEE_MAIN_NON_FEE_COLS,
    SHOPEE_SF_MAPPED_FEE_COLS, SHOPEE_SF_NON_FEE_COLS,
)


def _warn_unmapped_wide_cols(conn, table_name, mapped_fee_cols, non_fee_cols, label):
    rows = conn.execute(text("""
        SELECT column_name FROM information_schema.columns
        WHERE table_schema = 'staging' AND table_name = :tname
        ORDER BY ordinal_position
    """), {'tname': table_name}).fetchall()

    excluded = set(mapped_fee_cols) | set(non_fee_cols)
    unmapped = [r[0] for r in rows if r[0] not in excluded]
    for col in unmapped:
        try:
            cnt = conn.execute(text(f"""
                SELECT COUNT(*) FROM staging."{table_name}"
                WHERE NULLIF(TRIM(CAST("{col}" AS TEXT)), '') IS NOT NULL
                  AND NULLIF(TRIM(CAST("{col}" AS TEXT)), '') <> 'nan'
                  AND TRIM(CAST("{col}" AS TEXT)) ~ '^-?[0-9]+(\\.[0-9]+)?$'
                  AND TRIM(CAST("{col}" AS TEXT))::NUMERIC <> 0
            """)).scalar() or 0
        except Exception:
            cnt = 0
        if cnt > 0:
            logger.warning(
                f"⚠️ LAPIS 2 [{label}]: kolom '{col}' di staging.{table_name} "
                f"tidak ada di mapping fee_type_id, tapi memiliki {cnt} baris bernilai ≠ 0."
            )


def _warn_unmapped_narrow_fees(conn, marketplace, label):
    if marketplace == 'shopee':
        sql = text("""
            SELECT TRIM(o.tipe_penyesuaian_deskripsi) AS fee_name, COUNT(*) AS cnt
            FROM staging.stg_shopee_income_adjustment o
            LEFT JOIN public.dim_fee_type ft
                ON ft.fee_name = TRIM(o.tipe_penyesuaian_deskripsi) AND ft.marketplace_name = 'Shopee'
            WHERE ft.fee_type_id IS NULL
              AND NULLIF(NULLIF(TRIM(o.biaya_penyesuaian),'nan'),'') IS NOT NULL
              AND NULLIF(NULLIF(TRIM(o.biaya_penyesuaian),'nan'),'')::NUMERIC <> 0
            GROUP BY 1 ORDER BY cnt DESC
        """)
    elif marketplace == 'lazada':
        sql = text("""
            SELECT TRIM(o.nama_biaya) AS fee_name, COUNT(*) AS cnt
            FROM staging.stg_lazada_income o
            LEFT JOIN public.dim_fee_type ft
                ON ft.fee_name = TRIM(o.nama_biaya) AND ft.marketplace_name = 'Lazada'
            WHERE ft.fee_type_id IS NULL
              AND NULLIF(REPLACE(TRIM(o.jumlah_termasuk_pajak),',',''),'nan') IS NOT NULL
              AND NULLIF(REPLACE(TRIM(o.jumlah_termasuk_pajak),',',''),'nan')::NUMERIC <> 0
            GROUP BY 1 ORDER BY cnt DESC
        """)
    else:
        return
    for row in conn.execute(sql).fetchall():
        logger.warning(
            f"⚠️ LAPIS 2 [{label}]: fee_name '{row[0]}' tidak ada di dim_fee_type "
            f"({row[1]} baris akan di-skip). Tambahkan ke dim_fee_type!"
        )


def _ensure_stg_fee_orphan(conn):
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS staging.stg_fee_orphan (
            orphan_id       BIGSERIAL    PRIMARY KEY,
            source          VARCHAR(50)  NOT NULL,
            fee_name        VARCHAR(255),
            fee_amount      NUMERIC(18,2),
            reason          VARCHAR(50)  NOT NULL
                CHECK (reason IN ('no_order_id', 'unmapped_fee_type')),
            raw_reference   VARCHAR(100),
            nama_toko       VARCHAR(255),
            source_filename VARCHAR(255),
            inserted_at     TIMESTAMPTZ  DEFAULT NOW(),
            CONSTRAINT uq_fee_orphan UNIQUE (source, raw_reference, source_filename)
        )
    """))


def _save_shopee_adj_orphans(conn):
    result = conn.execute(text("""
        INSERT INTO staging.stg_fee_orphan
            (source, fee_name, fee_amount, reason, raw_reference, nama_toko, source_filename)
        SELECT
            'shopee_adj',
            TRIM(o.tipe_penyesuaian_deskripsi),
            ABS(NULLIF(NULLIF(TRIM(o.biaya_penyesuaian),'nan'),'')::NUMERIC),
            'no_order_id',
            TRIM(o.no),
            TRIM(o.nama_toko),
            o.source_filename
        FROM staging.stg_shopee_income_adjustment o
        WHERE NULLIF(TRIM(o.no_pesanan_terhubung),'nan') IS NULL
          AND NULLIF(NULLIF(TRIM(o.biaya_penyesuaian),'nan'),'') IS NOT NULL
          AND NULLIF(NULLIF(TRIM(o.biaya_penyesuaian),'nan'),'')::NUMERIC <> 0
        ON CONFLICT (source, raw_reference, source_filename) DO NOTHING
    """))
    if result.rowcount > 0:
        logger.warning(
            f"⚠️ ORPHAN: {result.rowcount} baris Shopee Adj tanpa no_pesanan_terhubung "
            f"disimpan ke staging.stg_fee_orphan."
        )


def run(engine, marketplace):
    logger.info(f"[TRANSFORM] fact_order_fees ← {marketplace}")
    try:
        with engine.begin() as conn:
            setup_maps(conn, marketplace)

            if marketplace == 'tiktok_tokopedia':
                fee_values = ",\n                            ".join(
                    f"({fid}, NULLIF(NULLIF(TRIM(o.{col}), 'nan'), '')::NUMERIC)"
                    for col, fid in TIKTOK_INCOME_FEE_COLS.items()
                )
                result = conn.execute(text(f"""
                    INSERT INTO public.fact_order_fees (
                        order_id, fee_type_id, sales_channel_id,
                        fee_amount, source_marketplace, source_filename
                    )
                    SELECT sub.order_id, sub.fee_type_id, sub.sales_channel_id,
                           SUM(ABS(sub.fee_value)), sub.source_marketplace, MIN(sub.source_filename)
                    FROM (
                        SELECT
                            o.order_adjustment_id AS order_id,
                            cm.sales_channel_id,
                            u.fee_type_id,
                            u.fee_value,
                            'tiktok_tokopedia' AS source_marketplace,
                            o.source_filename
                        FROM staging.stg_tiktok_tokopedia_income o
                        LEFT JOIN _tmp_channel_map cm ON cm.nama_toko = LOWER(TRIM(o.nama_toko))
                        CROSS JOIN LATERAL (VALUES {fee_values}) AS u(fee_type_id, fee_value)
                        WHERE cm.sales_channel_id IS NOT NULL
                          AND o.type = 'Order'
                          AND NULLIF(TRIM(o.order_adjustment_id),'nan') IS NOT NULL
                          AND u.fee_value IS NOT NULL AND u.fee_value <> 0
                    ) sub
                    GROUP BY sub.order_id, sub.fee_type_id, sub.sales_channel_id, sub.source_marketplace, sub.source_filename
                    ON CONFLICT (order_id, fee_type_id, sales_channel_id) DO NOTHING
                """))
                logger.info(f"✅ fact_order_fees (tiktok_tokopedia): {result.rowcount} baris")
                _warn_unmapped_wide_cols(conn, 'stg_tiktok_tokopedia_income',
                                         TIKTOK_INCOME_FEE_COLS, TIKTOK_NON_FEE_COLS, 'TikTok')

            elif marketplace == 'shopee':
                main_fee_values = ",\n                            ".join(
                    f"({fid}, NULLIF(NULLIF(TRIM(o.{col}), 'nan'), '')::NUMERIC)"
                    for col, fid in SHOPEE_INCOME_MAIN_FEE_COLS.items()
                )
                _ensure_stg_fee_orphan(conn)

                r1 = conn.execute(text(f"""
                    INSERT INTO public.fact_order_fees (
                        order_id, fee_type_id, sales_channel_id,
                        fee_amount, source_marketplace, source_filename
                    )
                    SELECT sub.order_id, sub.fee_type_id, sub.sales_channel_id,
                           SUM(ABS(sub.fee_value)), sub.source_marketplace, MIN(sub.source_filename)
                    FROM (
                        SELECT
                            o.no_pesanan AS order_id,
                            cm.sales_channel_id,
                            u.fee_type_id,
                            u.fee_value,
                            'shopee' AS source_marketplace,
                            o.source_filename
                        FROM staging.stg_shopee_income_main o
                        LEFT JOIN _tmp_channel_map cm ON cm.nama_toko = LOWER(TRIM(o.nama_toko))
                        CROSS JOIN LATERAL (VALUES {main_fee_values}) AS u(fee_type_id, fee_value)
                        WHERE cm.sales_channel_id IS NOT NULL
                          AND NULLIF(TRIM(o.no_pesanan),'nan') IS NOT NULL
                          AND u.fee_value IS NOT NULL AND u.fee_value <> 0
                    ) sub
                    GROUP BY sub.order_id, sub.fee_type_id, sub.sales_channel_id, sub.source_marketplace, sub.source_filename
                    ON CONFLICT (order_id, fee_type_id, sales_channel_id) DO NOTHING
                """))

                r2 = conn.execute(text("""
                    INSERT INTO public.fact_order_fees (
                        order_id, fee_type_id, sales_channel_id,
                        fee_amount, source_marketplace, source_filename
                    )
                    SELECT sub.order_id, sub.fee_type_id, sub.sales_channel_id,
                           SUM(ABS(sub.fee_value)), sub.source_marketplace, MIN(sub.source_filename)
                    FROM (
                        SELECT
                            o.no_pesanan AS order_id,
                            cm.sales_channel_id,
                            u.fee_type_id,
                            u.fee_value,
                            'shopee' AS source_marketplace,
                            o.source_filename
                        FROM staging.stg_shopee_income_service_fee o
                        LEFT JOIN _tmp_channel_map cm ON cm.nama_toko = LOWER(TRIM(o.nama_toko))
                        CROSS JOIN LATERAL (VALUES
                            (102, NULLIF(NULLIF(TRIM(o.biaya_pembayaran),'nan'),'')::NUMERIC),
                            (106,
                                COALESCE(NULLIF(NULLIF(TRIM(o.biaya_layanan_gratis_ongkir_xtra),'nan'),'')::NUMERIC,0)
                              + COALESCE(NULLIF(NULLIF(TRIM(o.biaya_layanan_gratis_ongkir_xtra_2),'nan'),'')::NUMERIC,0)),
                            (107, NULLIF(NULLIF(TRIM(o.biaya_layanan_promo_xtra),'nan'),'')::NUMERIC),
                            (108,
                                COALESCE(NULLIF(NULLIF(TRIM(o.biaya_layanan_cashback_xtra),'nan'),'')::NUMERIC,0)
                              + COALESCE(NULLIF(NULLIF(TRIM(o.biaya_layanan_cashbackxtra),'nan'),'')::NUMERIC,0)),
                            (109, NULLIF(NULLIF(TRIM(o.biaya_program_shopee_live_xtra),'nan'),'')::NUMERIC),
                            (110,
                                COALESCE(NULLIF(NULLIF(TRIM(o.biaya_campaign_1_1),'nan'),'')::NUMERIC,0)
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
                        ) AS u(fee_type_id, fee_value)
                        WHERE cm.sales_channel_id IS NOT NULL
                          AND NULLIF(TRIM(o.no_pesanan),'nan') IS NOT NULL
                          AND u.fee_value IS NOT NULL AND u.fee_value <> 0
                    ) sub
                    GROUP BY sub.order_id, sub.fee_type_id, sub.sales_channel_id, sub.source_marketplace, sub.source_filename
                    ON CONFLICT (order_id, fee_type_id, sales_channel_id) DO NOTHING
                """))

                r3 = conn.execute(text("""
                    INSERT INTO public.fact_order_fees (
                        order_id, fee_type_id, sales_channel_id,
                        fee_amount, source_marketplace, source_filename
                    )
                    SELECT
                        NULLIF(TRIM(o.no_pesanan_terhubung),'nan'),
                        ft.fee_type_id,
                        cm.sales_channel_id,
                        ABS(NULLIF(NULLIF(TRIM(o.biaya_penyesuaian),'nan'),'')::NUMERIC),
                        'shopee',
                        o.source_filename
                    FROM staging.stg_shopee_income_adjustment o
                    LEFT JOIN _tmp_channel_map cm ON cm.nama_toko = LOWER(TRIM(o.nama_toko))
                    JOIN public.dim_fee_type ft
                        ON ft.fee_name = TRIM(o.tipe_penyesuaian_deskripsi)
                       AND ft.marketplace_name = 'Shopee'
                    WHERE cm.sales_channel_id IS NOT NULL
                      AND NULLIF(TRIM(o.no_pesanan_terhubung),'nan') IS NOT NULL
                      AND NULLIF(NULLIF(TRIM(o.biaya_penyesuaian),'nan'),'') IS NOT NULL
                      AND NULLIF(NULLIF(TRIM(o.biaya_penyesuaian),'nan'),'')::NUMERIC <> 0
                    ON CONFLICT (order_id, fee_type_id, sales_channel_id) DO NOTHING
                """))

                logger.info(
                    f"✅ fact_order_fees (shopee): {r1.rowcount} (main) + "
                    f"{r2.rowcount} (sf) + {r3.rowcount} (adj) baris"
                )
                _warn_unmapped_wide_cols(conn, 'stg_shopee_income_main',
                                         SHOPEE_INCOME_MAIN_FEE_COLS, SHOPEE_MAIN_NON_FEE_COLS, 'Shopee Main')
                _warn_unmapped_wide_cols(conn, 'stg_shopee_income_service_fee',
                                         SHOPEE_SF_MAPPED_FEE_COLS, SHOPEE_SF_NON_FEE_COLS, 'Shopee SF')
                _warn_unmapped_narrow_fees(conn, 'shopee', 'Shopee Adj')
                _save_shopee_adj_orphans(conn)
                check_fact_order_fees_narrow(conn, 'shopee', engine)

            elif marketplace == 'lazada':
                result = conn.execute(text("""
                    INSERT INTO public.fact_order_fees (
                        order_id, fee_type_id, sales_channel_id,
                        fee_amount, source_marketplace, source_filename
                    )
                    SELECT sub.order_id, sub.fee_type_id, sub.sales_channel_id,
                           SUM(ABS(sub.fee_value)), 'lazada', MIN(sub.source_filename)
                    FROM (
                        SELECT
                            COALESCE(NULLIF(TRIM(o.nomor_pesanan),'nan'), NULLIF(TRIM(o.id_pesanan),'nan')) AS order_id,
                            cm.sales_channel_id,
                            ft.fee_type_id,
                            NULLIF(REPLACE(TRIM(o.jumlah_termasuk_pajak),',',''),'nan')::NUMERIC AS fee_value,
                            o.source_filename
                        FROM staging.stg_lazada_income o
                        LEFT JOIN _tmp_channel_map cm ON cm.nama_toko = LOWER(TRIM(o.nama_toko))
                        JOIN public.dim_fee_type ft
                            ON ft.fee_name = TRIM(o.nama_biaya) AND ft.marketplace_name = 'Lazada'
                        WHERE cm.sales_channel_id IS NOT NULL
                          AND COALESCE(NULLIF(TRIM(o.nomor_pesanan),'nan'), NULLIF(TRIM(o.id_pesanan),'nan')) IS NOT NULL
                          AND NULLIF(REPLACE(TRIM(o.jumlah_termasuk_pajak),',',''),'nan') IS NOT NULL
                          AND NULLIF(REPLACE(TRIM(o.jumlah_termasuk_pajak),',',''),'nan')::NUMERIC <> 0
                    ) sub
                    GROUP BY sub.order_id, sub.fee_type_id, sub.sales_channel_id, sub.source_filename
                    ON CONFLICT (order_id, fee_type_id, sales_channel_id) DO NOTHING
                """))
                logger.info(f"✅ fact_order_fees (lazada): {result.rowcount} baris")
                _warn_unmapped_narrow_fees(conn, 'lazada', 'Lazada')
                check_fact_order_fees_narrow(conn, 'lazada', engine)

            else:
                logger.warning(f"Marketplace '{marketplace}' tidak dikenal.")

    except Exception as e:
        logger.error(f"❌ fact_order_fees ({marketplace}): {e}")
        raise
