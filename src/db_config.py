from sqlalchemy import create_engine
import logging

# Konfigurasi Logging agar kita bisa melihat proses di terminal
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Konfigurasi Database PostgreSQL Anda
DB_USER     = 'postgres'
DB_PASSWORD = 'password'
DB_HOST     = 'localhost'
DB_PORT     = '5432'
DB_NAME     = 'wellfarm'

def get_engine():
    """Membuat dan mengembalikan koneksi engine SQLAlchemy."""
    try:
        engine = create_engine(
            f'postgresql+psycopg2://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}',
            connect_args={"options": "-csearch_path=staging,public"}
        )
        logger.info("Berhasil membuat engine koneksi ke PostgreSQL.")
        return engine
    except Exception as e:
        logger.error(f"Gagal koneksi ke database: {e}")
        raise