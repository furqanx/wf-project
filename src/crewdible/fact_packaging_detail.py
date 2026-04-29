# src/crewdible/fact_packaging_detail.py

from sqlalchemy import text
from src.db_config import logger


def run(engine):
    logger.info("[TRANSFORM] fact_fulfillment_packaging_detail ← stg_crewdible")
    try:
        with engine.begin() as conn:
            result = conn.execute(text("""
                INSERT INTO public.fact_fulfillment_packaging_detail (
                    order_id, material_name,
                    unit_price, quantity, total_price,
                    source_filename
                )
                SELECT DISTINCT ON (s.no_transaksi, s.material_packaging)
                    s.no_transaksi,
                    s.material_packaging,
                    NULLIF(NULLIF(TRIM(s.harga_material_packaging),''),'nan')::NUMERIC,
                    NULLIF(NULLIF(TRIM(s.qty_material_packaging),''),'nan')::NUMERIC,
                    NULLIF(NULLIF(TRIM(s.total_harga_material_packaging),''),'nan')::NUMERIC,
                    s.source_filename
                FROM staging.stg_crewdible s
                WHERE s.no_transaksi IS NOT NULL
                  AND s.material_packaging IS NOT NULL
                  AND NOT EXISTS (
                      SELECT 1 FROM public.fact_fulfillment_packaging_detail f
                      WHERE f.order_id = s.no_transaksi AND f.material_name = s.material_packaging
                  )
                ORDER BY s.no_transaksi, s.material_packaging
            """))
            logger.info(f"✅ fact_fulfillment_packaging_detail: {result.rowcount} baris")
    except Exception as e:
        logger.error(f"❌ fact_fulfillment_packaging_detail: {e}")
        raise
