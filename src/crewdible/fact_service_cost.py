# src/crewdible/fact_service_cost.py

from sqlalchemy import text
from src.db_config import logger
from src.crewdible._helpers import setup_maps


def run(engine):
    logger.info("[TRANSFORM] fact_fulfillment_service_cost ← stg_crewdible")
    try:
        with engine.begin() as conn:
            setup_maps(conn)
            result = conn.execute(text("""
                INSERT INTO public.fact_fulfillment_service_cost (
                    order_id,
                    store_id, marketplace_id,
                    fulfillment_date_id, warehouse_id,
                    sender_name, sender_phone,
                    recipient_name, recipient_phone, recipient_address,
                    fulfillment_status, logistics_provider, booking_code, airway_bill_number,
                    order_value_declared,
                    transaction_fee, transaction_fee_tax,
                    packaging_cost, packaging_cost_tax,
                    quality_control_cost, quality_control_cost_tax,
                    shipping_label_cost, shipping_label_cost_tax,
                    logistics_cost, total_fulfillment_cost,
                    source_filename
                )
                SELECT DISTINCT ON (s.no_transaksi)
                    s.no_transaksi,
                    sm.store_id,
                    mm.marketplace_id,
                    CASE
                        WHEN NULLIF(TRIM(s.tanggal_transaksi), '') IS NOT NULL
                         AND TRIM(s.tanggal_transaksi) ~ E'^\\d{4}-\\d{2}-\\d{2}'
                        THEN CAST(TO_CHAR(CAST(TRIM(s.tanggal_transaksi) AS DATE), 'YYYYMMDD') AS INT)
                    END,
                    wm.warehouse_id,
                    NULLIF(TRIM(s.pengirim), ''),
                    NULLIF(TRIM(s.no_hp_pengirim), ''),
                    NULLIF(TRIM(s.penerima), ''),
                    NULLIF(TRIM(s.no_hp_penerima), ''),
                    NULLIF(TRIM(s.alamat_penerima), ''),
                    NULLIF(TRIM(s.status), ''),
                    NULLIF(TRIM(s.logistik), ''),
                    NULLIF(TRIM(s.kode_booking), ''),
                    NULLIF(TRIM(s.no_awb), ''),
                    NULLIF(NULLIF(TRIM(s.total_nilai_transaksi),''),'nan')::NUMERIC,
                    NULLIF(NULLIF(TRIM(s.biaya_transaksi),''),'nan')::NUMERIC,
                    NULLIF(NULLIF(TRIM(s.ppn_biaya_transaksi),''),'nan')::NUMERIC,
                    NULLIF(NULLIF(TRIM(s.total_biaya_packaging),''),'nan')::NUMERIC,
                    NULLIF(NULLIF(TRIM(s.ppn_total_biaya_packaging),''),'nan')::NUMERIC,
                    NULLIF(NULLIF(TRIM(s.total_biaya_qc),''),'nan')::NUMERIC,
                    NULLIF(NULLIF(TRIM(s.ppn_total_biaya_qc),''),'nan')::NUMERIC,
                    NULLIF(NULLIF(TRIM(s.total_biaya_shipping_label),''),'nan')::NUMERIC,
                    NULLIF(NULLIF(TRIM(s.ppn_total_biaya_shipping_label),''),'nan')::NUMERIC,
                    NULLIF(NULLIF(TRIM(s.biaya_logistik),''),'nan')::NUMERIC,
                    NULLIF(NULLIF(TRIM(s.total_biaya_transaksi),''),'nan')::NUMERIC,
                    s.source_filename
                FROM staging.stg_crewdible s
                LEFT JOIN _tmp_crewdible_store_map       sm ON sm.raw_name = LOWER(TRIM(s.nama_toko))
                LEFT JOIN _tmp_crewdible_marketplace_map mm ON mm.raw_name = LOWER(TRIM(s.nama_marketplace))
                LEFT JOIN _tmp_crewdible_warehouse_map   wm ON wm.raw_name = LOWER(TRIM(s.gudang))
                WHERE s.no_transaksi IS NOT NULL
                  AND NOT EXISTS (
                      SELECT 1 FROM public.fact_fulfillment_service_cost f
                      WHERE f.order_id = s.no_transaksi
                  )
                ORDER BY s.no_transaksi
            """))
            logger.info(f"✅ fact_fulfillment_service_cost: {result.rowcount} baris")
    except Exception as e:
        logger.error(f"❌ fact_fulfillment_service_cost: {e}")
        raise
