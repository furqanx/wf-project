# src/main.py
import os
import argparse
import time
from src.db_config import get_engine, logger
from src.extract_loader import process_order_file, process_income_file, process_report_file, process_crewdible_file
from src.transform_loader import run_transform, run_transform_crewdible, load_dim_b2b_partner
# from src.raw_material_loader import load_raw_material_purchase
# from src.production_loader import load_production_data
# from src.stock_out_loader import load_stock_out
# from src.distribution_target_loader import load_distribution_target
# from src.production_target_loader import load_production_target
# from src.product_price_loader import load_product_price
# from src.delivery_order_loader import load_delivery_order

def run_crawler(root_dir, target_phase, marketplace, engine):
    """
    Menelusuri folder dan mengeksekusi file yang sesuai dengan fase (ORDER/INCOME/REPORT).
    Sekarang menerima nama marketplace langsung dari parameter terminal.
    """
    logger.info(f"🚀 Memulai pencarian untuk fase: {target_phase.upper()} di direktori: {root_dir}")
    logger.info(f"🎯 Target Marketplace disetel secara manual: {marketplace.upper() if marketplace else 'N/A (CREWDIBLE)'}")
    
    file_count = 0
    start_time = time.time()

    # os.walk akan merayapi folder utama dan semua subfoldernya
    for dirpath, _, filenames in os.walk(root_dir):
        for filename in filenames:
            # 1. Abaikan file tersembunyi atau file temporary excel yang sedang terbuka (berawalan ~$)
            if filename.startswith('~$') or filename.startswith('.'):
                continue
                
            # 2. Hanya ambil file Excel atau CSV
            if not (filename.endswith('.xlsx') or filename.endswith('.xls') or filename.endswith('.csv')):
                continue

            file_path = os.path.join(dirpath, filename)
            
            # 3. Eksekusi berdasarkan Fase dan Marketplace (yang disuntik dari terminal)
            if target_phase.upper() == 'ORDER':
                process_order_file(file_path, marketplace, engine)
                file_count += 1
            elif target_phase.upper() == 'INCOME':
                process_income_file(file_path, marketplace, engine)
                file_count += 1
            elif target_phase.upper() == 'REPORT':
                process_report_file(file_path, marketplace, engine)
                file_count += 1
            elif target_phase.upper() == 'CREWDIBLE':
                process_crewdible_file(file_path, engine)
                file_count += 1

    elapsed_time = round(time.time() - start_time, 2)
    mp_label = marketplace.upper() if marketplace else 'CREWDIBLE'
    logger.info(f"✅ Selesai! Memproses total {file_count} file {target_phase.upper()} untuk {mp_label} dalam {elapsed_time} detik.")


if __name__ == "__main__":
    # Setup argument parser untuk menerima perintah dari terminal Ubuntu
    parser = argparse.ArgumentParser(description="ETL Pipeline E-commerce ke PostgreSQL")
    
    parser.add_argument('--fase', type=str, required=True, choices=['ORDER', 'INCOME', 'REPORT', 'TRANSFORM', 'CREWDIBLE', 'TRANSFORM_CREWDIBLE', 'LOAD_B2B_PARTNER', 'LOAD_RAW_MATERIAL', 'LOAD_PRODUCTION', 'LOAD_STOCK_OUT', 'LOAD_DISTRIBUTION_TARGET', 'LOAD_PRODUCTION_TARGET', 'LOAD_PRODUCT_PRICE', 'LOAD_DO'],
                        help="Pilih fase eksekusi: ORDER, INCOME, REPORT, TRANSFORM, CREWDIBLE, TRANSFORM_CREWDIBLE, LOAD_B2B_PARTNER, LOAD_RAW_MATERIAL, LOAD_PRODUCTION, LOAD_STOCK_OUT, LOAD_DISTRIBUTION_TARGET, LOAD_PRODUCTION_TARGET, LOAD_PRODUCT_PRICE, atau LOAD_DO")
    
    parser.add_argument('--dir', type=str, required=False,
                        help="Jalur (path) direktori utama tempat file mentah disimpan (tidak diperlukan untuk fase TRANSFORM)")
    
    # --- TAMBAHAN BARU: Parameter --marketplace ---
    # type=str.lower memastikan input user dari terminal selalu diubah jadi huruf kecil (misal: SHOPEE -> shopee)
    parser.add_argument('--marketplace', type=str.lower, required=False,
                        choices=['shopee', 'lazada', 'tiktok_tokopedia'],
                        default=None,
                        help="Tentukan asal marketplace file ini (shopee/lazada/tiktok_tokopedia). Tidak diperlukan untuk fase CREWDIBLE dan TRANSFORM.")

    parser.add_argument('--file', type=str, required=False,
                        default=None,
                        help="Jalur file sumber (CSV). Diperlukan untuk fase LOAD_B2B_PARTNER.")

    parser.add_argument('--date', type=str, required=False,
                        default=None,
                        help="Tanggal berlaku harga (YYYY-MM-DD). Digunakan untuk fase LOAD_PRODUCT_PRICE.")
    
    args = parser.parse_args()
    
    # 1. Inisialisasi koneksi database
    try:
        db_engine = get_engine()
    except Exception as e:
        logger.critical("Koneksi database gagal. Program dihentikan.")
        exit(1)
        
    # 2. Jalankan fase yang dipilih
    if args.fase.upper() == 'TRANSFORM':
        run_transform(engine=db_engine, marketplace=args.marketplace)
    elif args.fase.upper() == 'TRANSFORM_CREWDIBLE':
        run_transform_crewdible(engine=db_engine)
    elif args.fase.upper() == 'LOAD_B2B_PARTNER':
        if not args.file:
            logger.critical("--file wajib diisi untuk fase LOAD_B2B_PARTNER.")
            exit(1)
        load_dim_b2b_partner(csv_path=args.file, engine=db_engine)
    elif args.fase.upper() == 'LOAD_RAW_MATERIAL':
        if not args.file:
            logger.critical("--file wajib diisi untuk fase LOAD_RAW_MATERIAL.")
            exit(1)
        load_raw_material_purchase(csv_path=args.file, engine=db_engine)
    elif args.fase.upper() == 'LOAD_PRODUCTION':
        if not args.file:
            logger.critical("--file wajib diisi untuk fase LOAD_PRODUCTION.")
            exit(1)
        load_production_data(csv_path=args.file, engine=db_engine)
    elif args.fase.upper() == 'LOAD_STOCK_OUT':
        if not args.file:
            logger.critical("--file wajib diisi untuk fase LOAD_STOCK_OUT.")
            exit(1)
        load_stock_out(csv_path=args.file, engine=db_engine)
    elif args.fase.upper() == 'LOAD_DISTRIBUTION_TARGET':
        if not args.file:
            logger.critical("--file wajib diisi untuk fase LOAD_DISTRIBUTION_TARGET.")
            exit(1)
        load_distribution_target(csv_path=args.file, engine=db_engine)
    elif args.fase.upper() == 'LOAD_PRODUCTION_TARGET':
        if not args.file:
            logger.critical("--file wajib diisi untuk fase LOAD_PRODUCTION_TARGET.")
            exit(1)
        load_production_target(csv_path=args.file, engine=db_engine)
    elif args.fase.upper() == 'LOAD_PRODUCT_PRICE':
        if not args.file:
            logger.critical("--file wajib diisi untuk fase LOAD_PRODUCT_PRICE.")
            exit(1)
        load_product_price(csv_path=args.file, engine=db_engine, effective_date=args.date)
    elif args.fase.upper() == 'LOAD_DO':
        if not args.file:
            logger.critical("--file wajib diisi untuk fase LOAD_DO.")
            exit(1)
        load_delivery_order(csv_path=args.file, engine=db_engine)
    elif args.fase.upper() == 'CREWDIBLE':
        if not args.dir:
            logger.critical("--dir wajib diisi untuk fase CREWDIBLE.")
            exit(1)
        run_crawler(root_dir=args.dir, target_phase=args.fase, marketplace=None, engine=db_engine)
    else:
        if not args.dir:
            logger.critical("--dir wajib diisi untuk fase ORDER, INCOME, dan REPORT.")
            exit(1)
        if not args.marketplace:
            logger.critical("--marketplace wajib diisi untuk fase ORDER, INCOME, dan REPORT.")
            exit(1)
        run_crawler(root_dir=args.dir, target_phase=args.fase, marketplace=args.marketplace, engine=db_engine)