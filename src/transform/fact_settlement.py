# src/transform/fact_settlement.py

from sqlalchemy import text
from src.db_config import logger
from src.transform._helpers import setup_maps


def run(engine, marketplace):
    logger.info(f"[TRANSFORM] fact_settlement ← {marketplace}")
    try:
        with engine.begin() as conn:
            setup_maps(conn, marketplace)

            if marketplace == 'shopee':
                result = conn.execute(text("""
                    INSERT INTO public.fact_settlement (
                        order_id, sales_channel_id,
                        amt_settled, time_funds_released, settlement_date_id,
                        source_marketplace, source_filename
                    )
                    SELECT
                        o.no_pesanan,
                        cm.sales_channel_id,
                        NULLIF(NULLIF(TRIM(o.total_penghasilan),'nan'),'')::NUMERIC,
                        CASE WHEN NULLIF(NULLIF(NULLIF(TRIM(o.tanggal_dana_dilepaskan),'nan'),''),'-') IS NOT NULL
                             THEN TRIM(o.tanggal_dana_dilepaskan)::DATE::TIMESTAMP END,
                        CASE WHEN NULLIF(NULLIF(NULLIF(TRIM(o.tanggal_dana_dilepaskan),'nan'),''),'-') IS NOT NULL
                             THEN CAST(TO_CHAR(TRIM(o.tanggal_dana_dilepaskan)::DATE,'YYYYMMDD') AS INT) END,
                        'shopee',
                        o.source_filename
                    FROM staging.stg_shopee_income_main o
                    LEFT JOIN _tmp_channel_map cm ON cm.nama_toko = LOWER(TRIM(o.nama_toko))
                    WHERE cm.sales_channel_id IS NOT NULL
                      AND NULLIF(TRIM(o.no_pesanan),'nan') IS NOT NULL
                    ON CONFLICT (order_id, sales_channel_id) DO NOTHING
                """))
                logger.info(f"✅ fact_settlement (shopee): {result.rowcount} baris")

            elif marketplace == 'tiktok_tokopedia':
                result = conn.execute(text("""
                    INSERT INTO public.fact_settlement (
                        order_id, sales_channel_id,
                        amt_settled, time_funds_released, settlement_date_id,
                        source_marketplace, source_filename
                    )
                    SELECT
                        o.order_adjustment_id,
                        cm.sales_channel_id,
                        NULLIF(NULLIF(TRIM(o.total_settlement_amount),'nan'),'')::NUMERIC,
                        CASE WHEN NULLIF(NULLIF(TRIM(o.order_settled_time),'nan'),'') IS NOT NULL
                             THEN TRIM(o.order_settled_time)::DATE::TIMESTAMP END,
                        CASE WHEN NULLIF(NULLIF(TRIM(o.order_settled_time),'nan'),'') IS NOT NULL
                             THEN CAST(TO_CHAR(TRIM(o.order_settled_time)::DATE,'YYYYMMDD') AS INT) END,
                        'tiktok_tokopedia',
                        o.source_filename
                    FROM staging.stg_tiktok_tokopedia_income o
                    LEFT JOIN _tmp_channel_map cm ON cm.nama_toko = LOWER(TRIM(o.nama_toko))
                    WHERE cm.sales_channel_id IS NOT NULL
                      AND NULLIF(TRIM(o.order_adjustment_id),'nan') IS NOT NULL
                      AND o.type = 'Order'
                    ON CONFLICT (order_id, sales_channel_id) DO NOTHING
                """))
                logger.info(f"✅ fact_settlement (tiktok_tokopedia): {result.rowcount} baris")

            elif marketplace == 'lazada':
                result = conn.execute(text("""
                    INSERT INTO public.fact_settlement (
                        order_id, sales_channel_id,
                        amt_settled, time_funds_released, settlement_date_id,
                        source_marketplace, source_filename
                    )
                    SELECT
                        sub.order_id,
                        sub.sales_channel_id,
                        sub.amt_settled,
                        sub.time_funds_released,
                        CASE WHEN sub.time_funds_released IS NOT NULL
                             THEN CAST(TO_CHAR(sub.time_funds_released::DATE,'YYYYMMDD') AS INT) END,
                        'lazada',
                        sub.source_filename
                    FROM (
                        SELECT
                            COALESCE(
                                NULLIF(TRIM(o.nomor_pesanan),'nan'),
                                NULLIF(TRIM(o.id_pesanan),'nan')
                            ) AS order_id,
                            cm.sales_channel_id,
                            SUM(NULLIF(REPLACE(TRIM(o.jumlah_termasuk_pajak),',',''),'nan')::NUMERIC) AS amt_settled,
                            MAX(CASE WHEN NULLIF(NULLIF(TRIM(o.tanggal_dilepas),'nan'),'') IS NOT NULL
                                     THEN TO_TIMESTAMP(TRIM(o.tanggal_dilepas),'DD Mon YYYY HH24:MI') END) AS time_funds_released,
                            MIN(o.source_filename) AS source_filename
                        FROM staging.stg_lazada_income o
                        LEFT JOIN _tmp_channel_map cm ON cm.nama_toko = LOWER(TRIM(o.nama_toko))
                        WHERE cm.sales_channel_id IS NOT NULL
                          AND COALESCE(NULLIF(TRIM(o.nomor_pesanan),'nan'), NULLIF(TRIM(o.id_pesanan),'nan')) IS NOT NULL
                          AND NULLIF(REPLACE(TRIM(o.jumlah_termasuk_pajak),',',''),'nan') IS NOT NULL
                        GROUP BY 1, 2
                    ) sub
                    ON CONFLICT (order_id, sales_channel_id) DO NOTHING
                """))
                logger.info(f"✅ fact_settlement (lazada): {result.rowcount} baris")

            else:
                logger.warning(f"Marketplace '{marketplace}' tidak dikenal.")

    except Exception as e:
        logger.error(f"❌ fact_settlement ({marketplace}): {e}")
        raise
