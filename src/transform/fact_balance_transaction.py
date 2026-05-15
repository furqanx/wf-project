# src/transform/fact_balance_transaction.py

from sqlalchemy import text
from src.db_config import logger
from src.transform._helpers import setup_maps
from src.transform._checks import check_fact_balance_transaction


def run(engine, marketplace):
    logger.info(f"[TRANSFORM] fact_balance_transaction ← {marketplace}")
    try:
        with engine.begin() as conn:
            setup_maps(conn, marketplace)

            if marketplace == 'shopee':
                conn.execute(text("DELETE FROM public.fact_balance_transaction WHERE source_marketplace = 'shopee'"))

                # r1: Penghasilan dari Pesanan — gunakan no_pesanan sebagai kunci unik
                r1 = conn.execute(text("""
                    INSERT INTO public.fact_balance_transaction (
                        sales_channel_id, transaction_date, type, sub_type,
                        direction, amount, payout_batch_id, remarks,
                        source_marketplace, source_filename, transaction_date_id
                    )
                    SELECT DISTINCT ON (TRIM(r.no_pesanan), cm.sales_channel_id)
                        cm.sales_channel_id,
                        TRIM(r.tanggal_transaksi)::TIMESTAMP::DATE,
                        TRIM(r.tipe_transaksi),
                        NULL,
                        'inflow',
                        ABS(NULLIF(TRIM(r.jumlah), 'nan')::NUMERIC),
                        NULL,
                        NULLIF(TRIM(r.deskripsi), 'nan'),
                        'shopee',
                        r.source_filename,
                        CAST(TO_CHAR(TRIM(r.tanggal_transaksi)::TIMESTAMP::DATE, 'YYYYMMDD') AS INT)
                    FROM staging.stg_shopee_report r
                    LEFT JOIN _tmp_channel_map cm ON cm.nama_toko = r.nama_toko
                    WHERE cm.sales_channel_id IS NOT NULL
                      AND NULLIF(TRIM(r.jumlah), 'nan') IS NOT NULL
                      AND TRIM(r.tanggal_transaksi) ~ '^\\d{4}-\\d{2}-\\d{2}'
                      AND TRIM(r.tipe_transaksi) = 'Penghasilan dari Pesanan'
                      AND NULLIF(TRIM(r.no_pesanan), 'nan') IS NOT NULL
                      AND TRIM(r.no_pesanan) != '-'
                    ORDER BY TRIM(r.no_pesanan), cm.sales_channel_id
                """))

                # r2: Tipe lainnya — gunakan kombinasi semua kolom sebagai kunci
                r2 = conn.execute(text("""
                    INSERT INTO public.fact_balance_transaction (
                        sales_channel_id, transaction_date, type, sub_type,
                        direction, amount, payout_batch_id, remarks,
                        source_marketplace, source_filename, transaction_date_id
                    )
                    SELECT DISTINCT ON (
                        TRIM(r.tanggal_transaksi), TRIM(r.tipe_transaksi),
                        TRIM(r.jumlah), TRIM(r.deskripsi), cm.sales_channel_id
                    )
                        cm.sales_channel_id,
                        TRIM(r.tanggal_transaksi)::TIMESTAMP::DATE,
                        TRIM(r.tipe_transaksi),
                        NULL,
                        CASE TRIM(r.tipe_transaksi)
                            WHEN 'Pembayaran dengan Saldo Penjual' THEN 'outflow'
                            WHEN 'Penarikan Dana'                  THEN 'outflow'
                            WHEN 'Penyesuaian'                     THEN 'adjustment'
                            WHEN 'Pengembalian Dana atas Pesanan'  THEN 'outflow'
                            ELSE 'adjustment'
                        END,
                        ABS(NULLIF(TRIM(r.jumlah), 'nan')::NUMERIC),
                        NULL,
                        NULLIF(TRIM(r.deskripsi), 'nan'),
                        'shopee',
                        r.source_filename,
                        CAST(TO_CHAR(TRIM(r.tanggal_transaksi)::TIMESTAMP::DATE, 'YYYYMMDD') AS INT)
                    FROM staging.stg_shopee_report r
                    LEFT JOIN _tmp_channel_map cm ON cm.nama_toko = r.nama_toko
                    WHERE cm.sales_channel_id IS NOT NULL
                      AND NULLIF(TRIM(r.jumlah), 'nan') IS NOT NULL
                      AND TRIM(r.tanggal_transaksi) ~ '^\\d{4}-\\d{2}-\\d{2}'
                      AND (
                          TRIM(r.tipe_transaksi) != 'Penghasilan dari Pesanan'
                          OR NULLIF(TRIM(r.no_pesanan), 'nan') IS NULL
                          OR TRIM(r.no_pesanan) = '-'
                      )
                    ORDER BY
                        TRIM(r.tanggal_transaksi), TRIM(r.tipe_transaksi),
                        TRIM(r.jumlah), TRIM(r.deskripsi), cm.sales_channel_id
                """))

                logger.info(f"✅ fact_balance_transaction (shopee): {r1.rowcount + r2.rowcount} baris")

            elif marketplace == 'tiktok_tokopedia':
                conn.execute(text("DELETE FROM public.fact_balance_transaction WHERE source_marketplace = 'tiktok_tokopedia'"))
                r1 = conn.execute(text("""
                    INSERT INTO public.fact_balance_transaction (
                        sales_channel_id, 
                        transaction_date, 
                        type, 
                        sub_type,
                        direction, 
                        amount, 
                        payout_batch_id, 
                        remarks,
                        source_marketplace, 
                        source_filename, 
                        transaction_date_id
                    )
                        SELECT DISTINCT ON (TRIM(r.reference_id))
                            cm.sales_channel_id,
                            TO_DATE(REPLACE(TRIM(r.success_time), '/', '-'), 'YYYY-MM-DD'),
                            TRIM(r.type),
                            NULL,
                            'outflow',
                            ABS(NULLIF(TRIM(r.amount), 'nan')::NUMERIC),
                            TRIM(r.reference_id),
                            NULL,
                            'tiktok_tokopedia',
                            r.source_filename,
                            CAST(TO_CHAR(TO_DATE(REPLACE(TRIM(r.success_time), '/', '-'), 'YYYY-MM-DD'), 'YYYYMMDD') AS INT)
                        FROM staging.stg_tiktok_tokopedia_report r
                        LEFT JOIN _tmp_channel_map cm ON cm.nama_toko = r.nama_toko
                        WHERE cm.sales_channel_id IS NOT NULL
                            AND REPLACE(TRIM(r.success_time), '/', '-') ~ '^\\d{4}-\\d{2}-\\d{2}'
                            AND TRIM(r.type) = 'Withdrawal'
                            AND NULLIF(TRIM(r.reference_id), 'nan') IS NOT NULL
                        ORDER BY TRIM(r.reference_id)
                """))
                r2 = conn.execute(text("""
                    INSERT INTO public.fact_balance_transaction (
                        sales_channel_id, transaction_date, type, sub_type,
                        direction, amount, payout_batch_id, remarks,
                        source_marketplace, source_filename, transaction_date_id
                    )
                        SELECT DISTINCT ON (TRIM(r.reference_id), cm.sales_channel_id)
                            cm.sales_channel_id,
                            TO_DATE(REPLACE(TRIM(r.success_time), '/', '-'), 'YYYY-MM-DD'),
                            TRIM(r.type),
                            NULL,
                            CASE TRIM(r.type)
                                WHEN 'Earnings'          THEN 'inflow'
                                WHEN 'GMV Pay Deduction' THEN 'outflow'
                                ELSE 'adjustment'
                            END,
                            ABS(NULLIF(TRIM(r.amount), 'nan')::NUMERIC),
                            NULL,
                            NULL,
                            'tiktok_tokopedia',
                            r.source_filename,
                            CAST(TO_CHAR(TO_DATE(REPLACE(TRIM(r.success_time), '/', '-'), 'YYYY-MM-DD'), 'YYYYMMDD') AS INT)
                        FROM staging.stg_tiktok_tokopedia_report r
                        LEFT JOIN _tmp_channel_map cm ON cm.nama_toko = r.nama_toko
                        WHERE cm.sales_channel_id IS NOT NULL
                        AND REPLACE(TRIM(r.success_time), '/', '-') ~ '^\\d{4}-\\d{2}-\\d{2}'
                        AND TRIM(r.type) != 'Withdrawal'
                        AND NULLIF(TRIM(r.reference_id), 'nan') IS NOT NULL
                        ORDER BY TRIM(r.reference_id), cm.sales_channel_id
                """))
                logger.info(f"✅ fact_balance_transaction (tiktok_tokopedia): {r1.rowcount + r2.rowcount} baris")

            elif marketplace == 'lazada':
                conn.execute(text("DELETE FROM public.fact_balance_transaction WHERE source_marketplace = 'lazada'"))
                r1 = conn.execute(text("""
                    INSERT INTO public.fact_balance_transaction (
                        sales_channel_id, transaction_date, type, sub_type,
                        direction, amount, payout_batch_id, remarks,
                        source_marketplace, source_filename, transaction_date_id
                    )
                    SELECT DISTINCT ON (TRIM(r.transaction_number), cm.sales_channel_id)
                        cm.sales_channel_id,
                        TO_TIMESTAMP(TRIM(r.transaction_time), 'DD Mon YYYY HH24:MI:SS')::DATE,
                        TRIM(r.type),
                        NULLIF(TRIM(r.sub_type), 'nan'),
                        'outflow',
                        ABS(NULLIF(REPLACE(TRIM(r.amount), ',', ''), 'nan')::NUMERIC),
                        TRIM(r.transaction_number),
                        NULLIF(TRIM(r.remarks), 'nan'),
                        'lazada',
                        r.source_filename,
                        CAST(TO_CHAR(TO_TIMESTAMP(TRIM(r.transaction_time), 'DD Mon YYYY HH24:MI:SS')::DATE, 'YYYYMMDD') AS INT)
                    FROM staging.stg_lazada_report r
                    LEFT JOIN _tmp_channel_map cm ON cm.nama_toko = r.nama_toko
                    WHERE cm.sales_channel_id IS NOT NULL
                      AND TRIM(r.transaction_time) ~ '^\\d{2} [A-Za-z]{3} \\d{4}'
                      AND TRIM(r.type) = 'Withdrawal'
                      AND NULLIF(TRIM(r.transaction_number), 'nan') IS NOT NULL
                    ORDER BY TRIM(r.transaction_number), cm.sales_channel_id
                """))
                r2 = conn.execute(text("""
                    INSERT INTO public.fact_balance_transaction (
                        sales_channel_id, transaction_date, type, sub_type,
                        direction, amount, payout_batch_id, remarks,
                        source_marketplace, source_filename, transaction_date_id
                    )
                    SELECT DISTINCT ON (TRIM(r.transaction_number), cm.sales_channel_id)
                        cm.sales_channel_id,
                        TO_TIMESTAMP(TRIM(r.transaction_time), 'DD Mon YYYY HH24:MI:SS')::DATE,
                        TRIM(r.type),
                        NULLIF(TRIM(r.sub_type), 'nan'),
                        CASE
                            WHEN TRIM(r.type) = 'Deposit' AND TRIM(r.sub_type) = 'Settlement'     THEN 'inflow'
                            WHEN TRIM(r.type) = 'Deposit' AND TRIM(r.sub_type) = 'Failed Payment' THEN 'adjustment'
                            WHEN TRIM(r.type) = 'Payment'                                          THEN 'outflow'
                            WHEN TRIM(r.type) = 'Penalty'                                          THEN 'outflow'
                            ELSE 'adjustment'
                        END,
                        ABS(NULLIF(REPLACE(TRIM(r.amount), ',', ''), 'nan')::NUMERIC),
                        NULL,
                        NULLIF(TRIM(r.remarks), 'nan'),
                        'lazada',
                        r.source_filename,
                        CAST(TO_CHAR(TO_TIMESTAMP(TRIM(r.transaction_time), 'DD Mon YYYY HH24:MI:SS')::DATE, 'YYYYMMDD') AS INT)
                    FROM staging.stg_lazada_report r
                    LEFT JOIN _tmp_channel_map cm ON cm.nama_toko = r.nama_toko
                    WHERE cm.sales_channel_id IS NOT NULL
                      AND TRIM(r.transaction_time) ~ '^\\d{2} [A-Za-z]{3} \\d{4}'
                      AND TRIM(r.type) != 'Withdrawal'
                      AND NULLIF(TRIM(r.transaction_number), 'nan') IS NOT NULL
                    ORDER BY TRIM(r.transaction_number), cm.sales_channel_id
                """))
                logger.info(f"✅ fact_balance_transaction (lazada): {r1.rowcount + r2.rowcount} baris")

            else:
                logger.warning(f"Marketplace '{marketplace}' tidak dikenal.")
                return

            check_fact_balance_transaction(conn, marketplace, engine)

    except Exception as e:
        logger.error(f"❌ fact_balance_transaction ({marketplace}): {e}")
        raise
