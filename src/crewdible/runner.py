# src/crewdible/runner.py

from src.db_config import get_engine, logger
from src.crewdible import fact_service_cost, fact_order_product, fact_packaging_detail


def run(engine=None):
    if engine is None:
        engine = get_engine()

    logger.info("🔄 Memulai TRANSFORM_CREWDIBLE")
    fact_service_cost.run(engine)
    fact_order_product.run(engine)
    fact_packaging_detail.run(engine)
    logger.info("✅ TRANSFORM_CREWDIBLE selesai")


if __name__ == '__main__':
    run()
