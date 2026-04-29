# src/crewdible/fact_order_product.py

from sqlalchemy import text
from src.db_config import logger


def run(engine):
    logger.info("[TRANSFORM] fact_fulfillment_order_product ← stg_crewdible")
    try:
        with engine.begin() as conn:
            result = conn.execute(text("""
                INSERT INTO public.fact_fulfillment_order_product (
                    order_id, sku_code, product_name,
                    quantity_sold, declared_unit_price, declared_total_product_value,
                    source_filename
                )
                SELECT DISTINCT ON (s.no_transaksi, s.no_sku)
                    s.no_transaksi,
                    s.no_sku,
                    NULLIF(TRIM(s.nama_produk), ''),
                    NULLIF(NULLIF(TRIM(s.qty_produk),''),'nan')::NUMERIC,
                    NULLIF(NULLIF(TRIM(s.harga_produk),''),'nan')::NUMERIC,
                    NULLIF(NULLIF(TRIM(s.total_harga_produk),''),'nan')::NUMERIC,
                    s.source_filename
                FROM staging.stg_crewdible s
                WHERE s.no_transaksi IS NOT NULL
                  AND s.no_sku IS NOT NULL
                  AND NOT EXISTS (
                      SELECT 1 FROM public.fact_fulfillment_order_product f
                      WHERE f.order_id = s.no_transaksi AND f.sku_code = s.no_sku
                  )
                ORDER BY s.no_transaksi, s.no_sku
            """))
            logger.info(f"✅ fact_fulfillment_order_product: {result.rowcount} baris")
    except Exception as e:
        logger.error(f"❌ fact_fulfillment_order_product: {e}")
        raise
