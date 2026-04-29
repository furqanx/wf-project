# src/transform/runner.py
"""
Entry point untuk menjalankan seluruh pipeline TRANSFORM.
Urutan eksekusi penting — ada dependensi antar tabel.
"""

from src.db_config import get_engine, logger
from src.transform import (
    fact_fulfillment_logistics,
    fact_balance_transaction,
    fact_returns_online,
    fact_sales_online,
    fact_settlement,
    fact_order_fees,
)


VALID_MARKETPLACES = {'shopee', 'lazada', 'tiktok_tokopedia'}


def run(marketplace: str, engine=None):
    if marketplace not in VALID_MARKETPLACES:
        raise ValueError(f"Marketplace tidak valid: '{marketplace}'. Pilihan: {VALID_MARKETPLACES}")

    if engine is None:
        engine = get_engine()

    logger.info(f"🔄 Memulai TRANSFORM untuk marketplace: {marketplace.upper()}")

    fact_fulfillment_logistics.run(engine, marketplace)
    fact_balance_transaction.run(engine, marketplace)
    fact_returns_online.run(engine, marketplace)
    fact_sales_online.run(engine, marketplace)
    fact_settlement.run(engine, marketplace)
    fact_order_fees.run(engine, marketplace)

    logger.info(f"✅ TRANSFORM selesai untuk {marketplace.upper()}")


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Transform pipeline Wellfarm')
    parser.add_argument('--marketplace', required=True, choices=list(VALID_MARKETPLACES))
    args = parser.parse_args()
    run(args.marketplace)
