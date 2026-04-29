# src/transform/fact_returns_online.py

from sqlalchemy import text
from src.db_config import logger
from src.transform._helpers import setup_maps
from src.transform._checks import check_fact_returns_online


def run(engine, marketplace):
    logger.info(f"[TRANSFORM] fact_returns_online ← {marketplace}")
    try:
        with engine.begin() as conn:
            setup_maps(conn, marketplace)

            if marketplace == 'shopee':
                result = conn.execute(text("""
                    INSERT INTO public.fact_returns_online (
                        order_id, product_id, sales_channel_id,
                        cancel_return_reason_id, initiator_id, return_status_id,
                        warehouse_id, qty_returned,
                        source_marketplace, source_filename
                    )
                    SELECT
                        o.no_pesanan,
                        dp.product_id,
                        cm.sales_channel_id,
                        NULL,
                        NULL,
                        CASE TRIM(o.status_pembatalan_pengembalian)
                            WHEN 'Permintaan Disetujui'  THEN 1
                            WHEN 'Permintaan Dibatalkan' THEN 2
                            WHEN 'Pengembalian Diproses' THEN 3
                            ELSE 5
                        END,
                        wm.warehouse_id,
                        CASE WHEN NULLIF(TRIM(o.returned_quantity), 'nan') IS NOT NULL
                             THEN TRIM(o.returned_quantity)::INT ELSE NULL END,
                        'shopee',
                        o.source_filename
                    FROM staging.stg_shopee_orders o
                    LEFT JOIN _tmp_channel_map cm   ON cm.nama_toko = o.nama_toko
                    LEFT JOIN _tmp_warehouse_map wm  ON wm.raw_name = LOWER(TRIM(o.nama_gudang))
                    LEFT JOIN public.dim_sku_alias dsa ON dsa.sku_alias = COALESCE(
                        NULLIF(TRIM(o.nomor_referensi_sku), 'nan'),
                        NULLIF(TRIM(o.sku_induk), 'nan'))
                    LEFT JOIN public.dim_product dp ON dp.sku_code = COALESCE(
                        (SELECT dp1.sku_code FROM public.dim_product dp1 WHERE dp1.sku_code = (
                            CASE WHEN COALESCE(NULLIF(TRIM(o.nomor_referensi_sku),'nan'),NULLIF(TRIM(o.sku_induk),'nan')) ~ '^P[0-9]'
                                 THEN 'B'||SUBSTRING(COALESCE(NULLIF(TRIM(o.nomor_referensi_sku),'nan'),NULLIF(TRIM(o.sku_induk),'nan')),2)
                                 ELSE COALESCE(NULLIF(TRIM(o.nomor_referensi_sku),'nan'),NULLIF(TRIM(o.sku_induk),'nan'))
                            END) LIMIT 1),
                        dsa.sku_code)
                    WHERE cm.sales_channel_id IS NOT NULL
                      AND dp.product_id IS NOT NULL
                      AND (
                          (NULLIF(TRIM(o.returned_quantity), '0') IS NOT NULL
                           AND NULLIF(TRIM(o.returned_quantity), 'nan') IS NOT NULL)
                          OR o.status_pembatalan_pengembalian IS NOT NULL
                      )
                    ON CONFLICT (order_id, product_id, sales_channel_id)
                        WHERE product_id IS NOT NULL
                    DO NOTHING
                """))
                logger.info(f"✅ fact_returns_online (shopee): {result.rowcount} baris")

            elif marketplace == 'tiktok_tokopedia':
                result = conn.execute(text("""
                    INSERT INTO public.fact_returns_online (
                        order_id, product_id, sales_channel_id,
                        cancel_return_reason_id, initiator_id, return_status_id,
                        warehouse_id, qty_returned, amt_refunded, return_event_date_id,
                        source_marketplace, source_filename
                    )
                    SELECT
                        o.order_id,
                        dp.product_id,
                        cm.sales_channel_id,
                        cr.cancel_return_reason_id,
                        CASE TRIM(o.cancel_by)
                            WHEN 'User'     THEN 1
                            WHEN 'Seller'   THEN 2
                            WHEN 'System'   THEN 3
                            WHEN 'Operator' THEN 4
                        END,
                        CASE
                            WHEN TRIM(o.cancelation_return_type) = 'Return/Refund' THEN 1
                            WHEN TRIM(o.cancelation_return_type) = 'Cancel'
                             AND TRIM(o.order_status) = 'Dibatalkan'               THEN 5
                            WHEN TRIM(o.cancelation_return_type) = 'Cancel'
                             AND TRIM(o.order_status) = 'Selesai'                  THEN 8
                        END,
                        wm.warehouse_id,
                        CASE WHEN NULLIF(TRIM(o.sku_quantity_of_return), 'nan') IS NOT NULL
                             THEN TRIM(o.sku_quantity_of_return)::INT ELSE NULL END,
                        CASE WHEN NULLIF(TRIM(o.order_refund_amount), '0') IS NOT NULL
                              AND NULLIF(TRIM(o.order_refund_amount), 'nan') IS NOT NULL
                             THEN TRIM(o.order_refund_amount)::NUMERIC ELSE NULL END,
                        CASE WHEN NULLIF(NULLIF(TRIM(o.cancelled_time), 'nan'), '') IS NOT NULL
                             THEN CAST(TO_CHAR(TO_TIMESTAMP(TRIM(o.cancelled_time), 'DD/MM/YYYY HH24:MI:SS')::DATE, 'YYYYMMDD') AS INT) END,
                        'tiktok_tokopedia',
                        o.source_filename
                    FROM staging.stg_tiktok_tokopedia_orders o
                    LEFT JOIN _tmp_channel_map cm ON cm.nama_toko = o.nama_toko
                    LEFT JOIN _tmp_warehouse_map wm ON wm.raw_name = LOWER(TRIM(o.warehouse_name))
                    LEFT JOIN public.dim_sku_alias dsa ON dsa.sku_alias = NULLIF(TRIM(o.seller_sku), 'nan')
                    LEFT JOIN public.dim_product dp ON dp.sku_code = COALESCE(
                        (SELECT dp1.sku_code FROM public.dim_product dp1
                         WHERE dp1.sku_code = NULLIF(TRIM(o.seller_sku), 'nan') LIMIT 1),
                        dsa.sku_code)
                    LEFT JOIN public.dim_cancel_return_reason cr
                        ON cr.reason_text_original = TRIM(o.cancel_reason)
                    WHERE cm.sales_channel_id IS NOT NULL
                      AND dp.product_id IS NOT NULL
                      AND NULLIF(TRIM(o.cancelation_return_type), 'nan') IS NOT NULL
                    ON CONFLICT (order_id, product_id, sales_channel_id)
                        WHERE product_id IS NOT NULL
                    DO NOTHING
                """))
                logger.info(f"✅ fact_returns_online (tiktok_tokopedia): {result.rowcount} baris")

            elif marketplace == 'lazada':
                result = conn.execute(text("""
                    INSERT INTO public.fact_returns_online (
                        order_id, product_id, sales_channel_id,
                        cancel_return_reason_id, initiator_id, return_status_id,
                        warehouse_id, exception_type, qty_returned, amt_refunded,
                        return_event_date_id, source_marketplace, source_filename
                    )
                    SELECT
                        o.order_number,
                        dp.product_id,
                        cm.sales_channel_id,
                        cr.cancel_return_reason_id,
                        CASE SPLIT_PART(o.buyer_failed_delivery_return_initiator, '-', 1)
                            WHEN 'cancel' THEN
                                CASE SPLIT_PART(o.buyer_failed_delivery_return_initiator, '-', 2)
                                    WHEN 'buyer'  THEN 1
                                    WHEN 'seller' THEN 2
                                    WHEN 'system' THEN 3
                                END
                            WHEN 'return'      THEN 1
                            WHEN 'only_refund' THEN 1
                        END,
                        CASE TRIM(o.status)
                            WHEN 'canceled'                        THEN 5
                            WHEN 'returned'                        THEN 4
                            WHEN 'Package Returned'                THEN 4
                            WHEN 'In Transit: Returning to seller' THEN 3
                            WHEN 'Lost by 3PL'                     THEN 7
                            WHEN 'Damaged by 3PL'                  THEN 7
                            WHEN 'Package scrapped'                THEN 7
                            ELSE CASE WHEN o.buyer_failed_delivery_return_initiator LIKE 'only_refund%' THEN 6 END
                        END,
                        wm.warehouse_id,
                        CASE WHEN TRIM(o.status) IN ('Lost by 3PL','Damaged by 3PL','Package scrapped')
                             THEN TRIM(o.status) ELSE NULL END,
                        1,
                        CASE WHEN NULLIF(TRIM(o.refund_amount), 'nan') IS NOT NULL
                              AND NULLIF(TRIM(o.refund_amount), '0') IS NOT NULL
                             THEN TRIM(o.refund_amount)::NUMERIC ELSE NULL END,
                        CASE WHEN NULLIF(NULLIF(TRIM(o.update_time), 'nan'), '') IS NOT NULL
                             THEN CAST(TO_CHAR(TO_TIMESTAMP(TRIM(o.update_time), 'DD Mon YYYY HH24:MI')::DATE, 'YYYYMMDD') AS INT) END,
                        'lazada',
                        o.source_filename
                    FROM staging.stg_lazada_orders o
                    LEFT JOIN _tmp_channel_map cm   ON cm.nama_toko = o.nama_toko
                    LEFT JOIN _tmp_warehouse_map wm  ON wm.raw_name = LOWER(TRIM(o.warehouse))
                    LEFT JOIN public.dim_sku_alias dsa ON dsa.sku_alias = NULLIF(TRIM(o.seller_sku), 'nan')
                    LEFT JOIN public.dim_product dp ON dp.sku_code = COALESCE(
                        (SELECT dp1.sku_code FROM public.dim_product dp1
                         WHERE dp1.sku_code = NULLIF(TRIM(o.seller_sku), 'nan') LIMIT 1),
                        dsa.sku_code)
                    LEFT JOIN public.dim_cancel_return_reason cr
                        ON cr.reason_text_original = TRIM(REGEXP_REPLACE(
                            o.buyer_failed_delivery_reason, '[\r\n]+', '', 'g'))
                    WHERE cm.sales_channel_id IS NOT NULL
                      AND dp.product_id IS NOT NULL
                      AND (
                          TRIM(o.status) IN ('canceled','returned','Package Returned',
                                             'In Transit: Returning to seller',
                                             'Lost by 3PL','Damaged by 3PL','Package scrapped')
                          OR o.buyer_failed_delivery_return_initiator LIKE 'only_refund%'
                      )
                    ON CONFLICT (order_id, product_id, sales_channel_id)
                        WHERE product_id IS NOT NULL
                    DO NOTHING
                """))
                logger.info(f"✅ fact_returns_online (lazada): {result.rowcount} baris")

            else:
                logger.warning(f"Marketplace '{marketplace}' tidak dikenal.")
                return

            check_fact_returns_online(conn, marketplace, engine)

    except Exception as e:
        logger.error(f"❌ fact_returns_online ({marketplace}): {e}")
        raise
