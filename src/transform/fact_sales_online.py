# src/transform/fact_sales_online.py

from sqlalchemy import text
from src.db_config import logger
from src.transform._helpers import setup_maps
from src.transform._checks import check_fact_sales_online


def run(engine, marketplace):
    logger.info(f"[TRANSFORM] fact_sales_online ← {marketplace}")
    try:
        with engine.begin() as conn:
            setup_maps(conn, marketplace)

            if marketplace == 'shopee':
                result = conn.execute(text("""
                    INSERT INTO public.fact_sales_online (
                        order_id, product_id, customer_id, sales_channel_id,
                        store_id, marketplace_id, order_status_id, payment_method_id,
                        order_date, order_date_id, is_pre_order,
                        qty_sold, qty_returned,
                        price_original_unit, amt_product_discount, amt_gross_revenue,
                        source_marketplace, source_filename
                    )
                    SELECT
                        o.no_pesanan,
                        dp.product_id,
                        dc.customer_id,
                        cm.sales_channel_id,
                        dsc.store_id,
                        dsc.marketplace_id,
                        CASE
                            WHEN o.status_pesanan = 'Belum Bayar'      THEN 1
                            WHEN o.status_pesanan = 'Perlu Dikirim'    THEN 2
                            WHEN o.status_pesanan = 'Sedang Dikirim'   THEN 3
                            WHEN o.status_pesanan = 'Telah Dikirim'    THEN 4
                            WHEN o.status_pesanan = 'Pesanan Diterima' THEN 5
                            WHEN o.status_pesanan LIKE 'Pesanan diterima, namun Pembeli masih%' THEN 6
                            WHEN o.status_pesanan = 'Selesai'          THEN 7
                            WHEN o.status_pesanan = 'Pembatalan diajukan' THEN 8
                            WHEN o.status_pesanan = 'Batal'            THEN 9
                            ELSE NULL
                        END,
                        CASE o.metode_pembayaran
                            WHEN 'COD (Bayar di Tempat)'       THEN 1
                            WHEN 'ShopeePay'                   THEN 12
                            WHEN 'Saldo ShopeePay'             THEN 12
                            WHEN 'QRIS'                        THEN 18
                            WHEN 'Kartu Kredit/Debit'          THEN 19
                            WHEN 'Cicilan Kartu Kredit'        THEN 19
                            WHEN 'BCA OneKlik'                 THEN 20
                            WHEN 'BRI Direct Debit'            THEN 21
                            WHEN 'SeaBank Bayar Instan'        THEN 22
                            WHEN 'SPayLater'                   THEN 23
                            WHEN 'Alfamart/Alfamidi/Dan+Dan'   THEN 30
                            WHEN 'Indomaret/i.Saku'            THEN 31
                            WHEN 'Mitra Shopee'                THEN 32
                            WHEN 'Online Payment'              THEN 33
                            WHEN 'Pembayaran dibebaskan'       THEN 34
                            WHEN 'Bank Lainnya (Dicek Manual)' THEN 8
                            ELSE NULL
                        END,
                        CASE WHEN NULLIF(NULLIF(NULLIF(TRIM(o.waktu_pesanan_dibuat),'nan'),''),'-') IS NOT NULL
                             THEN TO_TIMESTAMP(TRIM(o.waktu_pesanan_dibuat),'YYYY-MM-DD HH24:MI')::DATE END,
                        CASE WHEN NULLIF(NULLIF(NULLIF(TRIM(o.waktu_pesanan_dibuat),'nan'),''),'-') IS NOT NULL
                             THEN CAST(TO_CHAR(TO_TIMESTAMP(TRIM(o.waktu_pesanan_dibuat),'YYYY-MM-DD HH24:MI')::DATE,'YYYYMMDD') AS INT) END,
                        FALSE,
                        NULLIF(NULLIF(TRIM(o.jumlah),'nan'),'')::INT,
                        CASE WHEN NULLIF(NULLIF(NULLIF(TRIM(o.returned_quantity),'nan'),''),'-') IS NOT NULL
                             THEN NULLIF(NULLIF(NULLIF(TRIM(o.returned_quantity),'nan'),''),'-')::INT
                             ELSE 0 END,
                        NULLIF(REPLACE(NULLIF(NULLIF(TRIM(o.harga_awal),'nan'),''),'.',''),'')::NUMERIC,
                        ABS(COALESCE(NULLIF(REPLACE(NULLIF(NULLIF(TRIM(o.total_diskon),'nan'),''),'.',''),'')::NUMERIC, 0)),
                        CASE WHEN NULLIF(NULLIF(TRIM(o.harga_awal),'nan'),'') IS NOT NULL
                              AND NULLIF(NULLIF(TRIM(o.jumlah),'nan'),'') IS NOT NULL
                             THEN NULLIF(REPLACE(NULLIF(NULLIF(TRIM(o.harga_awal),'nan'),''),'.',''),'')::NUMERIC
                                  * NULLIF(NULLIF(TRIM(o.jumlah),'nan'),'')::INT
                                  - ABS(COALESCE(NULLIF(REPLACE(NULLIF(NULLIF(TRIM(o.total_diskon),'nan'),''),'.',''),'')::NUMERIC, 0))
                             ELSE NULL END,
                        'shopee',
                        o.source_filename
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
                    LEFT JOIN public.dim_customer dc ON dc.marketplace_id = 1 AND dc.username = o.username_pembeli
                    LEFT JOIN public.dim_sales_channel dsc ON dsc.sales_channel_id = cm.sales_channel_id
                    WHERE cm.sales_channel_id IS NOT NULL
                      AND dp.product_id IS NOT NULL
                    ON CONFLICT (order_id, product_id, sales_channel_id)
                        WHERE product_id IS NOT NULL
                    DO NOTHING
                """))
                logger.info(f"✅ fact_sales_online (shopee): {result.rowcount} baris")

            elif marketplace == 'tiktok_tokopedia':
                result = conn.execute(text("""
                    INSERT INTO public.fact_sales_online (
                        order_id, product_id, customer_id, sales_channel_id,
                        store_id, marketplace_id, order_status_id, payment_method_id,
                        order_date, order_date_id, invoice_number, is_pre_order,
                        qty_sold, qty_returned,
                        price_original_unit, amt_product_discount, amt_gross_revenue,
                        source_marketplace, source_filename
                    )
                    SELECT
                        o.order_id,
                        dp.product_id,
                        dc.customer_id,
                        cm.sales_channel_id,
                        dsc.store_id,
                        dsc.marketplace_id,
                        CASE o.order_status
                            WHEN 'Belum dibayar' THEN 1
                            WHEN 'Perlu dikirim' THEN 2
                            WHEN 'Dikirim'       THEN 3
                            WHEN 'Selesai'       THEN 7
                            WHEN 'Dibatalkan'    THEN 9
                            ELSE NULL
                        END,
                        CASE o.payment_method
                            WHEN 'Bayar di tempat'           THEN 1
                            WHEN 'Cash'                      THEN 1
                            WHEN 'KlikBCA'                   THEN 2
                            WHEN 'BRImo'                     THEN 4
                            WHEN 'Transfer bank'             THEN 8
                            WHEN 'Bank Transfer (Manual VA)' THEN 8
                            WHEN 'GoPay'                     THEN 9
                            WHEN 'OVO'                       THEN 10
                            WHEN 'DANA'                      THEN 11
                            WHEN 'LinkAja'                   THEN 13
                            WHEN 'Jago / Jago Syariah'       THEN 14
                            WHEN 'JakOne Pay'                THEN 15
                            WHEN 'Jenius Pay'                THEN 16
                            WHEN 'OCTO Clicks'               THEN 17
                            WHEN 'QRIS'                      THEN 18
                            WHEN 'Kartu kredit/debit'        THEN 19
                            WHEN 'DirectDebit'               THEN 21
                            WHEN 'GoPay Later'               THEN 24
                            WHEN 'Kredivo'                   THEN 25
                            WHEN 'BRI Ceria'                 THEN 26
                            WHEN 'PayLater'                  THEN 27
                            WHEN 'TikTok Shop Balance'       THEN 28
                            WHEN 'Saldo'                     THEN 28
                            WHEN 'Tokopedia History Order'   THEN 35
                            ELSE NULL
                        END,
                        CASE WHEN NULLIF(NULLIF(TRIM(o.created_time),'nan'),'') IS NOT NULL
                             THEN TO_TIMESTAMP(TRIM(o.created_time),'DD/MM/YYYY HH24:MI:SS')::DATE END,
                        CASE WHEN NULLIF(NULLIF(TRIM(o.created_time),'nan'),'') IS NOT NULL
                             THEN CAST(TO_CHAR(TO_TIMESTAMP(TRIM(o.created_time),'DD/MM/YYYY HH24:MI:SS')::DATE,'YYYYMMDD') AS INT) END,
                        NULLIF(TRIM(o.tokopedia_invoice_number),'nan'),
                        CASE WHEN TRIM(o.normal_or_pre_order) ILIKE 'pre%' THEN TRUE ELSE FALSE END,
                        NULLIF(NULLIF(TRIM(o.quantity),'nan'),'')::INT,
                        COALESCE(NULLIF(NULLIF(TRIM(o.sku_quantity_of_return),'nan'),'')::INT, 0),
                        NULLIF(NULLIF(TRIM(o.sku_unit_original_price),'nan'),'')::NUMERIC,
                        ABS(COALESCE(NULLIF(NULLIF(TRIM(o.sku_seller_discount),'nan'),'')::NUMERIC, 0))
                            + ABS(COALESCE(NULLIF(NULLIF(TRIM(o.sku_platform_discount),'nan'),'')::NUMERIC, 0)),
                        NULLIF(NULLIF(TRIM(o.sku_subtotal_after_discount),'nan'),'')::NUMERIC,
                        'tiktok_tokopedia',
                        o.source_filename
                    FROM staging.stg_tiktok_tokopedia_orders o
                    LEFT JOIN _tmp_channel_map cm ON cm.nama_toko = LOWER(TRIM(o.nama_toko))
                    LEFT JOIN public.dim_sku_alias dsa ON dsa.sku_alias = NULLIF(TRIM(o.seller_sku),'nan')
                    LEFT JOIN public.dim_product dp ON dp.sku_code = COALESCE(
                        (SELECT dp1.sku_code FROM public.dim_product dp1
                         WHERE dp1.sku_code = NULLIF(TRIM(o.seller_sku),'nan') LIMIT 1),
                        dsa.sku_code)
                    LEFT JOIN public.dim_customer dc ON dc.marketplace_id = 5 AND dc.username = o.buyer_username
                    LEFT JOIN public.dim_sales_channel dsc ON dsc.sales_channel_id = cm.sales_channel_id
                    WHERE cm.sales_channel_id IS NOT NULL
                      AND dp.product_id IS NOT NULL
                    ON CONFLICT (order_id, product_id, sales_channel_id)
                        WHERE product_id IS NOT NULL
                    DO NOTHING
                """))
                logger.info(f"✅ fact_sales_online (tiktok_tokopedia): {result.rowcount} baris")

            elif marketplace == 'lazada':
                result = conn.execute(text("""
                    INSERT INTO public.fact_sales_online (
                        order_id, product_id, customer_id, sales_channel_id,
                        store_id, marketplace_id, order_status_id, payment_method_id,
                        order_date, order_date_id, invoice_number, is_pre_order,
                        qty_sold, qty_returned,
                        price_original_unit, amt_product_discount, amt_gross_revenue,
                        source_marketplace, source_filename
                    )
                    SELECT
                        o.order_number,
                        dp.product_id,
                        dc.customer_id,
                        cm.sales_channel_id,
                        dsc.store_id,
                        dsc.marketplace_id,
                        CASE o.status
                            WHEN 'ready_to_ship'                   THEN 2
                            WHEN 'shipped'                         THEN 3
                            WHEN 'confirmed'                       THEN 5
                            WHEN 'delivered'                       THEN 7
                            WHEN 'canceled'                        THEN 9
                            WHEN 'returned'                        THEN 10
                            WHEN 'Package Returned'                THEN 10
                            WHEN 'In Transit: Returning to seller' THEN 10
                            WHEN 'Lost by 3PL'                     THEN 11
                            WHEN 'Damaged by 3PL'                  THEN 11
                            WHEN 'Package scrapped'                THEN 11
                            ELSE NULL
                        END,
                        CASE o.pay_method
                            WHEN 'COD'               THEN 1
                            WHEN 'BCA_VA'            THEN 2
                            WHEN 'KLIKBCA_VA'        THEN 2
                            WHEN 'BNI_VA'            THEN 3
                            WHEN 'BRI_VA'            THEN 4
                            WHEN 'MANDIRIMANDIRI_VA' THEN 5
                            WHEN 'CIMB_VA'           THEN 6
                            WHEN 'PANIN_VA'          THEN 7
                            WHEN 'GOPAY_WALLET'      THEN 9
                            WHEN 'WALLET_OVO'        THEN 10
                            WHEN 'DANA_WALLET'       THEN 11
                            WHEN 'QRIS'              THEN 18
                            WHEN 'MIXEDCARD'         THEN 19
                            WHEN 'CREDITPAY_KREDIVO' THEN 25
                            WHEN 'PAY_LATER'         THEN 27
                            WHEN 'SALDO'             THEN 29
                            WHEN 'ALFAMART_OTC'      THEN 30
                            WHEN 'INDOMARET_OTC'     THEN 31
                            WHEN 'PURE_ZERO_PRICE'   THEN 34
                            ELSE NULL
                        END,
                        CASE WHEN NULLIF(NULLIF(TRIM(o.create_time),'nan'),'') IS NOT NULL
                             THEN TO_TIMESTAMP(TRIM(o.create_time),'DD Mon YYYY HH24:MI')::DATE END,
                        CASE WHEN NULLIF(NULLIF(TRIM(o.create_time),'nan'),'') IS NOT NULL
                             THEN CAST(TO_CHAR(TO_TIMESTAMP(TRIM(o.create_time),'DD Mon YYYY HH24:MI')::DATE,'YYYYMMDD') AS INT) END,
                        NULLIF(TRIM(o.invoice_number),'nan'),
                        FALSE,
                        1,
                        0,
                        NULLIF(NULLIF(TRIM(o.unit_price),'nan'),'')::NUMERIC,
                        ABS(COALESCE(NULLIF(NULLIF(TRIM(o.seller_discount_total),'nan'),'')::NUMERIC, 0)),
                        CASE WHEN NULLIF(NULLIF(TRIM(o.unit_price),'nan'),'') IS NOT NULL
                             THEN NULLIF(NULLIF(TRIM(o.unit_price),'nan'),'')::NUMERIC
                                  - ABS(COALESCE(NULLIF(NULLIF(TRIM(o.seller_discount_total),'nan'),'')::NUMERIC, 0))
                             ELSE NULL END,
                        'lazada',
                        o.source_filename
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
                    LEFT JOIN public.dim_customer dc ON dc.marketplace_id = 4 AND dc.username = o.customer_name
                    LEFT JOIN public.dim_sales_channel dsc ON dsc.sales_channel_id = cm.sales_channel_id
                    WHERE cm.sales_channel_id IS NOT NULL
                      AND dp.product_id IS NOT NULL
                    ON CONFLICT (order_id, product_id, sales_channel_id)
                        WHERE product_id IS NOT NULL
                    DO NOTHING
                """))
                logger.info(f"✅ fact_sales_online (lazada): {result.rowcount} baris")

            else:
                logger.warning(f"Marketplace '{marketplace}' tidak dikenal.")
                return

            check_fact_sales_online(conn, marketplace, engine)

    except Exception as e:
        logger.error(f"❌ fact_sales_online ({marketplace}): {e}")
        raise
