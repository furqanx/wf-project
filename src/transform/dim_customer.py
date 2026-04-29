# src/transform/dim_customer.py

from sqlalchemy import text
from src.db_config import logger


def run(engine, marketplace):
    logger.info(f"[TRANSFORM] dim_customer ← {marketplace}")
    try:
        with engine.begin() as conn:
            if marketplace == 'shopee':
                sql = text("""
                    INSERT INTO public.dim_customer (marketplace_id, username, nama_penerima, no_telepon, provinsi, kota_kabupaten)
                    SELECT DISTINCT ON (o.username_pembeli)
                        1,
                        o.username_pembeli,
                        o.nama_penerima,
                        o.no_telepon,
                        o.provinsi,
                        o.kota_kabupaten
                    FROM staging.stg_shopee_orders o
                    WHERE o.username_pembeli IS NOT NULL
                      AND TRIM(o.username_pembeli) NOT IN ('nan', '')
                    ORDER BY o.username_pembeli, o.waktu_pesanan_dibuat DESC NULLS LAST
                    ON CONFLICT (marketplace_id, username) DO UPDATE SET
                        nama_penerima  = EXCLUDED.nama_penerima,
                        no_telepon     = EXCLUDED.no_telepon,
                        provinsi       = EXCLUDED.provinsi,
                        kota_kabupaten = EXCLUDED.kota_kabupaten
                """)

            elif marketplace == 'tiktok_tokopedia':
                sql = text("""
                    INSERT INTO public.dim_customer (marketplace_id, username, nama_penerima, no_telepon, provinsi, kota_kabupaten, kecamatan)
                    SELECT DISTINCT ON (o.buyer_username)
                        5,
                        o.buyer_username,
                        o.recipient,
                        o.phone_number,
                        o.province,
                        o.regency_and_city,
                        o.districts
                    FROM staging.stg_tiktok_tokopedia_orders o
                    WHERE o.buyer_username IS NOT NULL
                      AND TRIM(o.buyer_username) NOT IN ('nan', '')
                    ORDER BY o.buyer_username, o.created_time DESC NULLS LAST
                    ON CONFLICT (marketplace_id, username) DO UPDATE SET
                        nama_penerima  = EXCLUDED.nama_penerima,
                        no_telepon     = EXCLUDED.no_telepon,
                        provinsi       = EXCLUDED.provinsi,
                        kota_kabupaten = EXCLUDED.kota_kabupaten,
                        kecamatan      = EXCLUDED.kecamatan
                """)

            elif marketplace == 'lazada':
                sql = text("""
                    INSERT INTO public.dim_customer (marketplace_id, username, nama_penerima, email, no_telepon, provinsi, kota_kabupaten, kode_pos)
                    SELECT DISTINCT ON (o.customer_name)
                        4,
                        o.customer_name,
                        o.shipping_name,
                        NULLIF(TRIM(o.customer_email), 'nan'),
                        o.shipping_phone,
                        o.shipping_region,
                        o.shipping_city,
                        NULLIF(TRIM(o.shipping_post_code), 'nan')
                    FROM staging.stg_lazada_orders o
                    WHERE o.customer_name IS NOT NULL
                      AND TRIM(o.customer_name) NOT IN ('nan', '')
                    ORDER BY o.customer_name, o.create_time DESC NULLS LAST
                    ON CONFLICT (marketplace_id, username) DO UPDATE SET
                        nama_penerima  = EXCLUDED.nama_penerima,
                        email          = EXCLUDED.email,
                        no_telepon     = EXCLUDED.no_telepon,
                        provinsi       = EXCLUDED.provinsi,
                        kota_kabupaten = EXCLUDED.kota_kabupaten,
                        kode_pos       = EXCLUDED.kode_pos
                """)

            else:
                logger.warning(f"Marketplace '{marketplace}' tidak dikenal untuk dim_customer.")
                return

            result = conn.execute(sql)
            logger.info(f"✅ dim_customer ({marketplace}): {result.rowcount} baris diproses")

    except Exception as e:
        logger.error(f"❌ dim_customer ({marketplace}): {e}")
        raise
