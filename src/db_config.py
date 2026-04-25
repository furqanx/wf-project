import os
from sqlalchemy import create_engine
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def get_engine():
    user     = os.getenv('DB_USER',     'postgres')
    password = os.getenv('DB_PASSWORD', 'password')
    host     = os.getenv('DB_HOST',     'localhost')
    port     = os.getenv('DB_PORT',     '5432')
    dbname   = os.getenv('DB_NAME',     'wellfarm')
    sslmode  = os.getenv('DB_SSLMODE',  'prefer')

    try:
        engine = create_engine(
            f'postgresql+psycopg2://{user}:{password}@{host}:{port}/{dbname}',
            connect_args={
                'options':  '-csearch_path=staging,public',
                'sslmode':  sslmode,
            }
        )
        logger.info('Berhasil membuat engine koneksi ke PostgreSQL.')
        return engine
    except Exception as e:
        logger.error(f'Gagal koneksi ke database: {e}')
        raise
