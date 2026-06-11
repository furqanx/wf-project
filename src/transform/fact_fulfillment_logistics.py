# src/transform/fact_fulfillment_logistics.py

from sqlalchemy import text
from src.db_config import logger
from src.transform._helpers import setup_maps
from src.transform._checks import check_fact_fulfillment_logistics
from src.transform._audit import pre_audit_fact_fulfillment_logistics


def run(engine, marketplace):
    logger.info(f"[TRANSFORM] fact_fulfillment_logistics ← {marketplace}")
    try:
        with engine.begin() as conn:
            setup_maps(conn, marketplace)
            pre_audit_fact_fulfillment_logistics(conn, marketplace)

            if marketplace == 'shopee':
                sql = text("""
                    INSERT INTO public.fact_fulfillment_logistics (
                        order_id, 
                        sales_channel_id, 
                        shipping_service_id, 
                        warehouse_id,
                        sla_status_id, 
                        tracking_id, 
                        weight_kg, 
                        handover_type, 
                        is_dropship,
                        time_created, 
                        time_paid, 
                        time_rts, 
                        time_delivered,
                        source_marketplace, source_filename
                    )
                        SELECT DISTINCT ON (o.no_pesanan, cm.sales_channel_id)
                            o.no_pesanan,
                            cm.sales_channel_id,
                            sm.service_id,
                            wm.warehouse_id,
                            5,
                            NULLIF(TRIM(o.no_resi), 'nan'),
                            CASE WHEN NULLIF(NULLIF(TRIM(o.total_berat), 'nan'), '') IS NOT NULL
                                AND NULLIF(REGEXP_REPLACE(TRIM(o.total_berat), '[^0-9.]', '', 'g'), '') IS NOT NULL
                                THEN CASE WHEN LOWER(TRIM(o.total_berat)) LIKE '%kg%'
                                        THEN REGEXP_REPLACE(TRIM(o.total_berat), '[^0-9.]', '', 'g')::NUMERIC
                                        ELSE REGEXP_REPLACE(TRIM(o.total_berat), '[^0-9.]', '', 'g')::NUMERIC / 1000
                                    END
                                ELSE NULL END,
                            CASE TRIM(o.antar_ke_counter_pickup)
                                WHEN 'Antar ke Counter' THEN 'Antar ke Counter'
                                ELSE 'Pickup'
                            END,
                            FALSE,
                            CASE WHEN NULLIF(NULLIF(NULLIF(TRIM(o.waktu_pesanan_dibuat), 'nan'), ''), '-') IS NOT NULL
                                THEN TO_TIMESTAMP(TRIM(o.waktu_pesanan_dibuat), 'YYYY-MM-DD HH24:MI') END,
                            CASE WHEN NULLIF(NULLIF(NULLIF(TRIM(o.waktu_pembayaran_dilakukan), 'nan'), ''), '-') IS NOT NULL
                                THEN TO_TIMESTAMP(TRIM(o.waktu_pembayaran_dilakukan), 'YYYY-MM-DD HH24:MI') END,
                            CASE WHEN NULLIF(NULLIF(NULLIF(TRIM(o.waktu_pengiriman_diatur), 'nan'), ''), '-') IS NOT NULL
                                THEN TO_TIMESTAMP(TRIM(o.waktu_pengiriman_diatur), 'YYYY-MM-DD HH24:MI') END,
                            CASE WHEN NULLIF(NULLIF(NULLIF(TRIM(o.waktu_pesanan_selesai), 'nan'), ''), '-') IS NOT NULL
                                THEN TO_TIMESTAMP(TRIM(o.waktu_pesanan_selesai), 'YYYY-MM-DD HH24:MI') END,
                            'shopee',
                            o.source_filename
                        FROM staging.stg_shopee_orders o
                        LEFT JOIN _tmp_channel_map cm  ON cm.nama_toko = o.nama_toko
                        LEFT JOIN _tmp_warehouse_map wm ON wm.raw_name = LOWER(TRIM(o.nama_gudang))
                        LEFT JOIN _tmp_shipping_map sm  ON sm.provider = CASE
                            WHEN o.opsi_pengiriman LIKE '%-%'
                            THEN TRIM(SUBSTRING(o.opsi_pengiriman FROM STRPOS(o.opsi_pengiriman, '-') + 1))
                            ELSE TRIM(o.opsi_pengiriman)
                        END
                        WHERE cm.sales_channel_id IS NOT NULL
                        ORDER BY o.no_pesanan, cm.sales_channel_id, o.uploaded_at DESC NULLS LAST
                    ON CONFLICT (order_id, sales_channel_id) DO UPDATE SET
                        shipping_service_id = COALESCE(EXCLUDED.shipping_service_id, fact_fulfillment_logistics.shipping_service_id),
                        warehouse_id        = COALESCE(EXCLUDED.warehouse_id,        fact_fulfillment_logistics.warehouse_id),
                        sla_status_id       = COALESCE(EXCLUDED.sla_status_id,       fact_fulfillment_logistics.sla_status_id),
                        tracking_id         = COALESCE(EXCLUDED.tracking_id,         fact_fulfillment_logistics.tracking_id),
                        weight_kg           = COALESCE(EXCLUDED.weight_kg,           fact_fulfillment_logistics.weight_kg),
                        time_rts            = COALESCE(EXCLUDED.time_rts,            fact_fulfillment_logistics.time_rts),
                        time_delivered      = COALESCE(EXCLUDED.time_delivered,      fact_fulfillment_logistics.time_delivered),
                        source_filename     = EXCLUDED.source_filename
                """)

            elif marketplace == 'tiktok_tokopedia':
                sql = text("""
                    INSERT INTO public.fact_fulfillment_logistics (
                        order_id, 
                        sales_channel_id, 
                        shipping_service_id, 
                        warehouse_id,
                        sla_status_id, 
                        tracking_id, 
                        package_id, 
                        weight_kg,
                        distance_fee, 
                        handover_type, 
                        is_dropship,
                        time_created, 
                        time_paid, 
                        time_rts, 
                        time_shipped, 
                        time_delivered,
                        source_marketplace, source_filename
                    )
                        SELECT DISTINCT ON (o.order_id, cm.sales_channel_id)
                            o.order_id,
                            cm.sales_channel_id,
                            COALESCE(sm_exact.service_id, sm_wild.service_id),
                            wm.warehouse_id,
                            CASE
                                WHEN NULLIF(NULLIF(TRIM(o.rts_time), 'nan'), '') IS NULL
                                OR NULLIF(NULLIF(TRIM(o.shipped_time), 'nan'), '') IS NULL THEN 5
                                WHEN TO_TIMESTAMP(TRIM(o.shipped_time), 'DD/MM/YYYY HH24:MI:SS')
                                < TO_TIMESTAMP(TRIM(o.rts_time), 'DD/MM/YYYY HH24:MI:SS') THEN 1
                                WHEN DATE(TO_TIMESTAMP(TRIM(o.shipped_time), 'DD/MM/YYYY HH24:MI:SS'))
                                = DATE(TO_TIMESTAMP(TRIM(o.rts_time), 'DD/MM/YYYY HH24:MI:SS')) THEN 2
                                WHEN TO_TIMESTAMP(TRIM(o.shipped_time), 'DD/MM/YYYY HH24:MI:SS')
                                - TO_TIMESTAMP(TRIM(o.rts_time), 'DD/MM/YYYY HH24:MI:SS')
                                <= INTERVAL '1 day' THEN 3
                                ELSE 4
                            END,
                            NULLIF(TRIM(o.tracking_id), 'nan'),
                            NULLIF(TRIM(o.package_id), 'nan'),
                            CASE WHEN NULLIF(TRIM(o.weight_kg), 'nan') IS NOT NULL
                                THEN NULLIF(TRIM(o.weight_kg), '')::NUMERIC ELSE NULL END,
                            (COALESCE(NULLIF(TRIM(o.distance_fee), '0')::NUMERIC, 0)
                        + COALESCE(NULLIF(TRIM(o.distance_shipping_fee), '0')::NUMERIC, 0)),
                            'Pickup',
                            FALSE,
                            CASE WHEN NULLIF(NULLIF(TRIM(o.created_time), 'nan'), '') IS NOT NULL
                                THEN TO_TIMESTAMP(TRIM(o.created_time), 'DD/MM/YYYY HH24:MI:SS') END,
                            CASE WHEN NULLIF(NULLIF(TRIM(o.paid_time), 'nan'), '') IS NOT NULL
                                THEN TO_TIMESTAMP(TRIM(o.paid_time), 'DD/MM/YYYY HH24:MI:SS') END,
                            CASE WHEN NULLIF(NULLIF(TRIM(o.rts_time), 'nan'), '') IS NOT NULL
                                THEN TO_TIMESTAMP(TRIM(o.rts_time), 'DD/MM/YYYY HH24:MI:SS') END,
                            CASE WHEN NULLIF(NULLIF(TRIM(o.shipped_time), 'nan'), '') IS NOT NULL
                                THEN TO_TIMESTAMP(TRIM(o.shipped_time), 'DD/MM/YYYY HH24:MI:SS') END,
                            CASE WHEN NULLIF(NULLIF(TRIM(o.delivered_time), 'nan'), '') IS NOT NULL
                                THEN TO_TIMESTAMP(TRIM(o.delivered_time), 'DD/MM/YYYY HH24:MI:SS') END,
                            'tiktok_tokopedia',
                            o.source_filename
                        FROM staging.stg_tiktok_tokopedia_orders o
                        LEFT JOIN _tmp_channel_map cm ON cm.nama_toko = o.nama_toko
                        LEFT JOIN _tmp_warehouse_map wm ON wm.raw_name = LOWER(TRIM(o.warehouse_name))
                        LEFT JOIN _tmp_shipping_map sm_exact
                            ON sm_exact.provider = TRIM(o.shipping_provider_name)
                            AND sm_exact.delivery_option = TRIM(o.delivery_option)
                        LEFT JOIN _tmp_shipping_map sm_wild
                            ON sm_wild.provider = TRIM(o.shipping_provider_name)
                            AND sm_wild.delivery_option = '_'
                        WHERE cm.sales_channel_id IS NOT NULL
                        ORDER BY o.order_id, cm.sales_channel_id, o.uploaded_at DESC NULLS LAST
                    ON CONFLICT (order_id, sales_channel_id) DO UPDATE SET
                        shipping_service_id = COALESCE(EXCLUDED.shipping_service_id, fact_fulfillment_logistics.shipping_service_id),
                        warehouse_id        = COALESCE(EXCLUDED.warehouse_id,        fact_fulfillment_logistics.warehouse_id),
                        sla_status_id       = COALESCE(EXCLUDED.sla_status_id,       fact_fulfillment_logistics.sla_status_id),
                        tracking_id         = COALESCE(EXCLUDED.tracking_id,         fact_fulfillment_logistics.tracking_id),
                        package_id          = COALESCE(EXCLUDED.package_id,          fact_fulfillment_logistics.package_id),
                        weight_kg           = COALESCE(EXCLUDED.weight_kg,           fact_fulfillment_logistics.weight_kg),
                        time_rts            = COALESCE(EXCLUDED.time_rts,            fact_fulfillment_logistics.time_rts),
                        time_shipped        = COALESCE(EXCLUDED.time_shipped,        fact_fulfillment_logistics.time_shipped),
                        time_delivered      = COALESCE(EXCLUDED.time_delivered,      fact_fulfillment_logistics.time_delivered),
                        source_filename     = EXCLUDED.source_filename
                """)

            elif marketplace == 'lazada':
                sql = text("""
                    INSERT INTO public.fact_fulfillment_logistics (
                        order_id, 
                        sales_channel_id, 
                        shipping_service_id, 
                        warehouse_id,
                        sla_status_id, 
                        tracking_id, 
                        handover_type, 
                        is_dropship,
                        time_created, 
                        target_shipped_time, 
                        time_delivered,
                        source_marketplace, source_filename
                    )
                        SELECT DISTINCT ON (o.order_number, cm.sales_channel_id)
                            o.order_number,
                            cm.sales_channel_id,
                            sm.service_id,
                            wm.warehouse_id,
                            5,
                            NULLIF(TRIM(o.tracking_code), 'nan'),
                            'Dropship',
                            TRUE,
                            CASE WHEN NULLIF(NULLIF(TRIM(o.create_time), 'nan'), '') IS NOT NULL
                                THEN TO_TIMESTAMP(TRIM(o.create_time), 'DD Mon YYYY HH24:MI') END,
                            CASE WHEN NULLIF(NULLIF(TRIM(o.rts_sla), 'nan'), '') IS NOT NULL
                                THEN TO_TIMESTAMP(TRIM(o.rts_sla), 'DD Mon YYYY HH24:MI') END,
                            CASE WHEN NULLIF(NULLIF(TRIM(o.delivered_date), 'nan'), '') IS NOT NULL
                                THEN TO_TIMESTAMP(TRIM(o.delivered_date), 'DD Mon YYYY HH24:MI') END,
                            'lazada',
                            o.source_filename
                        FROM staging.stg_lazada_orders o
                        LEFT JOIN _tmp_channel_map cm   ON cm.nama_toko = o.nama_toko
                        LEFT JOIN _tmp_warehouse_map wm ON wm.raw_name = LOWER(TRIM(o.warehouse))
                        LEFT JOIN _tmp_shipping_map sm  ON sm.provider = TRIM(o.shipping_provider)
                        WHERE cm.sales_channel_id IS NOT NULL
                        ORDER BY o.order_number, cm.sales_channel_id, o.uploaded_at DESC NULLS LAST
                    ON CONFLICT (order_id, sales_channel_id) DO UPDATE SET
                        shipping_service_id = COALESCE(EXCLUDED.shipping_service_id, fact_fulfillment_logistics.shipping_service_id),
                        warehouse_id        = COALESCE(EXCLUDED.warehouse_id,        fact_fulfillment_logistics.warehouse_id),
                        sla_status_id       = COALESCE(EXCLUDED.sla_status_id,       fact_fulfillment_logistics.sla_status_id),
                        tracking_id         = COALESCE(EXCLUDED.tracking_id,         fact_fulfillment_logistics.tracking_id),
                        target_shipped_time = COALESCE(EXCLUDED.target_shipped_time, fact_fulfillment_logistics.target_shipped_time),
                        time_delivered      = COALESCE(EXCLUDED.time_delivered,      fact_fulfillment_logistics.time_delivered),
                        source_filename     = EXCLUDED.source_filename
                """)

            else:
                logger.warning(f"Marketplace '{marketplace}' tidak dikenal.")
                return

            result = conn.execute(sql)
            logger.info(f"✅ fact_fulfillment_logistics ({marketplace}): {result.rowcount} baris")
            check_fact_fulfillment_logistics(conn, marketplace, engine)

    except Exception as e:
        logger.error(f"❌ fact_fulfillment_logistics ({marketplace}): {e}")
        raise
