# TikTok-Tokopedia Income STTM

## Scope

- Target table: `stg_tiktok_tokopedia_income`
- Marketplace: `tiktok_tokopedia`
- Phase: `Income`
- Source mapping constant: `TIKTOK_INCOME_COLUMN_MAP`
- Schema guard constant: `VALID_TIKTOK_INCOME_COLS`

## File Reading Rules

- File dibaca dengan `pd.ExcelFile(..., engine="openpyxl")`.
- Loader saat ini memilih sheet `Order details` jika ada; jika tidak ada, memilih sheet pertama.
- `nama_toko` diekstrak dari nama file; `source_filename` diisi dari nama file.
- Jika tabel fisik memiliki `uploaded_at`, kolom tersebut diasumsikan diisi oleh database/default load process, bukan kolom source file.

## Source Signature Summary

| Sheet / Role | Signature | Count | Years | Months | Language | Column Count | Example |
|---|---:|---:|---|---|---|---:|---|
| Order details | `2289c7e7bb` | 12 | 2026 | april | english | 68 | `etc/fixed data/tiktok-tokopedia/income/2026/april/4. Income Tiktok Basecamp organik 2026.xlsx || etc/fixed data/tiktok-tokopedia/income/2026/april/4. Income Tiktok Beras organik ID 2026.xlsx || etc/fixed data/tiktok-tokopedia/income/2026/april/4. Income Tiktok Beras sehat 2026.xlsx || etc/fixed data/tiktok-tokopedia/income/2026/april/4. Income Tiktok Bogor healthy 2026.xlsx || etc/fixed data/tiktok-tokopedia/income/2026/april/4. Income Tiktok Bromo organik 2026.xlsx` |
| Order details | `4f514c5a2a` | 39 | 2023|2024|2025|2026 | februari|maret | english | 65 | `etc/fixed data/tiktok-tokopedia/income/2023/Income Tiktok Wellfarm ID 2023.xlsx || etc/fixed data/tiktok-tokopedia/income/2024/Income Tiktok Porice 2024.xlsx || etc/fixed data/tiktok-tokopedia/income/2024/Income Tiktok Wellfarm ID 2024.xlsx || etc/fixed data/tiktok-tokopedia/income/2024/Income Tiktok Wellfarm Store 2024.xlsx || etc/fixed data/tiktok-tokopedia/income/2025/Income Beras Sehat 2025.xlsx` |
| Order details | `f8b7d0610b` | 11 | 2026 | januari | english | 64 | `etc/fixed data/tiktok-tokopedia/income/2026/januari/income_20260311211409(UTC+7) wellfarm id.xlsx || etc/fixed data/tiktok-tokopedia/income/2026/januari/income_20260311211441(UTC+7) wellfarm store.xlsx || etc/fixed data/tiktok-tokopedia/income/2026/januari/income_20260311211514(UTC+7) pundi.xlsx || etc/fixed data/tiktok-tokopedia/income/2026/januari/income_20260311211544(UTC+7) organik id.xlsx || etc/fixed data/tiktok-tokopedia/income/2026/januari/income_20260311211620(UTC+7) porice.xlsx` |
| Order details | `71f1521b65` | 12 | 2026 | juni | indonesian | 79 | `etc/fixed data/tiktok-tokopedia/income/2026/juni/Income Tiktok Beras sehat.xlsx || etc/fixed data/tiktok-tokopedia/income/2026/juni/Income Tiktok Bromo organik.xlsx || etc/fixed data/tiktok-tokopedia/income/2026/juni/Income Tiktok Porice.xlsx || etc/fixed data/tiktok-tokopedia/income/2026/juni/Income Tiktok basecamp organik.xlsx || etc/fixed data/tiktok-tokopedia/income/2026/juni/Income Tiktok beras organik ID.xlsx` |
| Order details | `83ac6b8e17` | 12 | 2026 | mei | indonesian | 76 | `etc/fixed data/tiktok-tokopedia/income/2026/mei/Income Tiktok Basecamp organik mei 2026.xlsx || etc/fixed data/tiktok-tokopedia/income/2026/mei/Income Tiktok Beras organik ID mei 2026.xlsx || etc/fixed data/tiktok-tokopedia/income/2026/mei/Income Tiktok Beras sehat mei 2026.xlsx || etc/fixed data/tiktok-tokopedia/income/2026/mei/Income Tiktok Bogor healthy mei 2026.xlsx || etc/fixed data/tiktok-tokopedia/income/2026/mei/Income Tiktok Bromo organik mei 2026.xlsx` |

## Source To Target Mapping

| No | Target Column | Source Column | Required | Transform / Rule | Notes |
|---:|---|---|---|---|---|
| 1 | `order_adjustment_id` | `Order/adjustment ID` | Review | Rename / normalize column name |  |
| 2 | `type` | `Type` | Review | Rename / normalize column name |  |
| 3 | `order_created_time` | `Order created time` | Review | Rename / normalize column name |  |
| 4 | `order_settled_time` | `Order settled time` | Review | Rename / normalize column name |  |
| 5 | `currency` | `Currency` | Review | Rename / normalize column name |  |
| 6 | `total_settlement_amount` | `Total settlement amount` | Review | Rename / normalize column name |  |
| 7 | `total_revenue` | `Total Revenue` | Review | Rename / normalize column name |  |
| 8 | `subtotal_after_seller_discounts` | `Subtotal after seller discounts` | Review | Rename / normalize column name |  |
| 9 | `subtotal_before_discounts` | `Subtotal before discounts` | Review | Rename / normalize column name |  |
| 10 | `seller_discounts` | `Seller discounts` | Review | Rename / normalize column name |  |
| 11 | `distance_item_fee_from_horizon_plus_program` | `Distance item fee from Horizon+ Program` | Review | Rename / normalize column name |  |
| 12 | `refund_subtotal_after_seller_discounts` | `Refund subtotal after seller discounts` | Review | Rename / normalize column name |  |
| 13 | `refund_subtotal_before_seller_discounts` | `Refund subtotal before seller discounts` | Review | Rename / normalize column name |  |
| 14 | `refund_of_seller_discounts` | `Refund of seller discounts` | Review | Rename / normalize column name |  |
| 15 | `total_fees` | `Total Fees` | Review | Rename / normalize column name |  |
| 16 | `platform_commission_fee` | `Platform commission fee` | Review | Rename / normalize column name |  |
| 17 | `pre_order_service_fee` | `Pre-order service fee` | Review | Rename / normalize column name |  |
| 18 | `mall_service_fee` | `Mall service fee` | Review | Rename / normalize column name |  |
| 19 | `payment_fee` | `Payment Fee` | Review | Rename / normalize column name |  |
| 20 | `shipping_cost` | `Shipping cost` | Review | Rename / normalize column name |  |
| 21 | `shipping_costs_passed_on_to_the_logistics_provider` | `Shipping costs passed on to the logistics provider` | Review | Rename / normalize column name |  |
| 22 | `replacement_shipping_fee_passed_on_to_the_customer` | `Replacement shipping fee (passed on to the customer)` | Review | Rename / normalize column name |  |
| 23 | `exchange_shipping_fee_passed_on_to_the_customer` | `Exchange shipping fee (passed on to the customer)` | Review | Rename / normalize column name |  |
| 24 | `shipping_cost_borne_by_the_platform` | `Shipping cost borne by the platform` | Review | Rename / normalize column name |  |
| 25 | `shipping_cost_paid_by_the_customer` | `Shipping cost paid by the customer` | Review | Rename / normalize column name |  |
| 26 | `refunded_shipping_cost_paid_by_the_customer` | `Refunded shipping cost paid by the customer` | Review | Rename / normalize column name |  |
| 27 | `return_shipping_costs_passed_on_to_the_customer` | `Return shipping costs (passed on to the customer)` | Review | Rename / normalize column name |  |
| 28 | `shipping_cost_subsidy` | `Shipping cost subsidy` | Review | Rename / normalize column name |  |
| 29 | `distance_shipping_fee_from_horizon_plus_program` | `Distance shipping fee from Horizon+ Program` | Review | Rename / normalize column name |  |
| 30 | `affiliate_commission` | `Affiliate Commission` | Review | Rename / normalize column name |  |
| 31 | `affiliate_partner_commission` | `Affiliate partner commission` | Review | Rename / normalize column name |  |
| 32 | `affiliate_shop_ads_commission` | `Affiliate Shop Ads commission` | Review | Rename / normalize column name |  |
| 33 | `affiliate_partner_shop_ads_commission` | `Affiliate Partner shop ads commission` | Review | Rename / normalize column name |  |
| 34 | `shipping_fee_program_service_fee` | `Shipping Fee Program service fee` | Review | Rename / normalize column name |  |
| 35 | `dynamic_commission` | `Dynamic commission` | Review | Rename / normalize column name |  |
| 36 | `bonus_cashback_service_fee` | `Bonus cashback service fee` | Review | Rename / normalize column name |  |
| 37 | `live_specials_service_fee` | `LIVE Specials service fee` | Review | Rename / normalize column name |  |
| 38 | `voucher_xtra_service_fee` | `Voucher Xtra service fee` | Review | Rename / normalize column name |  |
| 39 | `order_processing_fee` | `Order processing fee` | Review | Rename / normalize column name |  |
| 40 | `eams_program_service_fee` | `EAMS Program service fee` | Review | Rename / normalize column name |  |
| 41 | `brands_crazy_deals_flash_sale_service_fee` | `Brands Crazy Deals/Flash Sale service fee` | Review | Rename / normalize column name |  |
| 42 | `dilayani_tokopedia_fee` | `Dilayani Tokopedia fee` | Review | Rename / normalize column name |  |
| 43 | `dilayani_tokopedia_handling_fee` | `Dilayani Tokopedia handling fee` | Review | Rename / normalize column name |  |
| 44 | `paylater_program_fee` | `PayLater program fee` | Review | Rename / normalize column name |  |
| 45 | `campaign_resource_fee` | `Campaign resource fee` | Review | Rename / normalize column name |  |
| 46 | `installation_service_fee` | `Installation service fee` | Review | Rename / normalize column name |  |
| 47 | `article_22_income_tax_withheld` | `Article 22 Income Tax withheld` | Review | Rename / normalize column name |  |
| 48 | `platform_special_service_fee` | `Platform special service fee` | Review | Rename / normalize column name |  |
| 49 | `gmv_max_ad_fee` | `GMV Max ad fee` | Review | Rename / normalize column name |  |
| 50 | `gmv_max_coupon` | `GMV Max Coupon`<br>`GMV Max coupon` | Review | Rename / normalize column name | Memiliki beberapa alias source. |
| 51 | `gmv_max_coupon_sales_tax` | `GMV Max coupon sales tax` | Review | Rename / normalize column name |  |
| 52 | `managed_service_plan_sales_tax` | `Managed service plan (Sales tax)` | Review | Rename / normalize column name |  |
| 53 | `managed_service_plan_per_order_fee` | `Managed service plan (Per order fee)` | Review | Rename / normalize column name |  |
| 54 | `logistics_service_fee` | `Logistics service fee` | Review | Rename / normalize column name |  |
| 55 | `ajustment_amount` | `Ajustment amount` | Review | Rename / normalize column name |  |
| 56 | `related_order_id` | `Related order ID` | Review | Rename / normalize column name |  |
| 57 | `shipping_fee_adjustment` | `Shipping fee adjustment` | Review | Rename / normalize column name |  |
| 58 | `shipping_fee_compensation` | `Shipping fee compensation` | Review | Rename / normalize column name |  |
| 59 | `chargeback` | `Chargeback` | Review | Rename / normalize column name |  |
| 60 | `customer_service_compensation` | `Customer service compensation` | Review | Rename / normalize column name |  |
| 61 | `promotion_adjustment` | `Promotion adjustment` | Review | Rename / normalize column name |  |
| 62 | `platform_compensation` | `Platform compensation` | Review | Rename / normalize column name |  |
| 63 | `platform_penalty` | `Platform penalty` | Review | Rename / normalize column name |  |
| 64 | `sample_shipping_fee` | `Sample shipping fee` | Review | Rename / normalize column name |  |
| 65 | `logistics_reimbursement` | `Logistics reimbursement` | Review | Rename / normalize column name |  |
| 66 | `platform_reimbursement` | `Platform reimbursement` | Review | Rename / normalize column name |  |
| 67 | `deductions_incurred_by_seller` | `Deductions incurred by seller` | Review | Rename / normalize column name |  |
| 68 | `shipping_fee_rebate` | `Shipping fee rebate` | Review | Rename / normalize column name |  |
| 69 | `warehouse_service_fee` | `Warehouse service fee` | Review | Rename / normalize column name |  |
| 70 | `platform_commission_adjustment` | `Platform commission adjustment` | Review | Rename / normalize column name |  |
| 71 | `platform_commission_compensation` | `Platform commission compensation` | Review | Rename / normalize column name |  |
| 72 | `transaction_fee_adjustment` | `Transaction fee adjustment` | Review | Rename / normalize column name |  |
| 73 | `top_up_for_ads_from_settled_balances` | `Top up for ads from settled balances` | Review | Rename / normalize column name |  |
| 74 | `campaign_package` | `Campaign Package` | Review | Rename / normalize column name |  |
| 75 | `additional_campaign_package` | `Additional Campaign Package` | Review | Rename / normalize column name |  |
| 76 | `gmv_payment_for_tiktok_ads` | `GMV Payment for TikTok Ads` | Review | Rename / normalize column name |  |
| 77 | `gmv_payment_for_promote` | `GMV Payment for Promote` | Review | Rename / normalize column name |  |
| 78 | `shipping_insurance_compensation` | `Shipping insurance compensation` | Review | Rename / normalize column name |  |
| 79 | `other_adjustment` | `Other adjustment` | Review | Rename / normalize column name |  |
| 80 | `customer_payment` | `Customer payment` | Review | Rename / normalize column name |  |
| 81 | `customer_refund` | `Customer refund` | Review | Rename / normalize column name |  |
| 82 | `seller_co_funded_voucher_discount` | `Seller co-funded voucher discount` | Review | Rename / normalize column name |  |
| 83 | `refund_of_seller_co_funded_voucher_discount` | `Refund of seller co-funded voucher discount` | Review | Rename / normalize column name |  |
| 84 | `platform_discounts` | `Platform discounts` | Review | Rename / normalize column name |  |
| 85 | `refund_of_platform_discounts` | `Refund of platform discounts` | Review | Rename / normalize column name |  |
| 86 | `platform_co_funded_voucher_discounts` | `Platform co-funded voucher discounts` | Review | Rename / normalize column name |  |
| 87 | `refund_of_platform_co_funded_voucher_discounts` | `Refund of platform co-funded voucher discounts` | Review | Rename / normalize column name |  |
| 88 | `seller_shipping_cost_discount` | `Seller shipping cost discount` | Review | Rename / normalize column name |  |
| 89 | `estimated_package_weight` | `Estimated package weight (g)` | Review | Rename / normalize column name |  |
| 90 | `actual_package_weight` | `Actual package weight (g)` | Review | Rename / normalize column name |  |
| 91 | `order_source` | `Order Source` | Review | Rename / normalize column name |  |
| 92 | `shopping_center_items` | `Shopping center items` | Review | Rename / normalize column name |  |
| 93 | `nama_toko` | Injected from filename / override | Review | Injected metadata | Bukan kolom asli file sumber. |
| 94 | `source_filename` | Injected from file basename | Review | Injected metadata | Bukan kolom asli file sumber. |

## Indonesian Sheet Aliases

| Indonesian Sheet | English / Existing Role | Loader Role |
|---|---|---|
| `Detail pesanan` | `Order details` | Income order details |
| `Laporan` | `Reports` | Summary/report sheet, biasanya tidak dimuat ke staging income utama |
| `Riwayat penarikan` | `Withdrawal records` | Withdrawal/report-like data; kandidat sumber `stg_tiktok_tokopedia_report` |
| `Penjelasan tentang biaya` | `Fees explanation` | Fee explanation sheet, bukan sumber staging income utama saat ini |

## Indonesian Source Column Aliases

| No | Target Column | Indonesian Source Column | English Equivalent / Notes | Status |
|---:|---|---|---|---|
| 1 | `order_adjustment_id` | `ID Pesanan/Penyesuaian` | `Order/adjustment ID` | Ready alias |
| 2 | `type` | `Jenis transaksi` | `Type` | Ready alias |
| 3 | `order_created_time` | `Waktu pemesanan` | `Order created time` | Ready alias |
| 4 | `order_settled_time` | `Waktu pembayaran pesanan` | `Order settled time` | Ready alias |
| 5 | `currency` | `Mata uang` | `Currency` | Ready alias |
| 6 | `total_settlement_amount` | `Jumlah penyelesaian pembayaran` | `Total settlement amount` | Ready alias |
| 7 | `total_revenue` | `Total Pendapatan` | `Total Revenue` | Ready alias |
| 8 | `subtotal_after_seller_discounts` | `Subtotal setelah diskon penjual` | `Subtotal after seller discounts` | Ready alias |
| 9 | `subtotal_before_discounts` | `Subtotal sebelum diskon` | `Subtotal before discounts` | Ready alias |
| 10 | `seller_discounts` | `Diskon penjual` | `Seller discounts` | Ready alias |
| 11 | `distance_item_fee_from_horizon_plus_program` | `Biaya produk sesuai jarak dari Program Horison+` | `Distance item fee from Horizon+ Program` | Ready alias |
| 12 | `refund_subtotal_after_seller_discounts` | `Subtotal pengembalian dana setelah diskon penjual` | `Refund subtotal after seller discounts` | Ready alias |
| 13 | `refund_subtotal_before_seller_discounts` | `Subtotal pengembalian dana sebelum diskon penjual` | `Refund subtotal before seller discounts` | Ready alias |
| 14 | `refund_of_seller_discounts` | `Pengembalian dana diskon penjual` | `Refund of seller discounts` | Ready alias |
| 15 | `total_fees` | `Total Biaya` | `Total Fees` | Ready alias |
| 16 | `platform_commission_fee` | `Biaya komisi platform` | `Platform commission fee` | Ready alias |
| 17 | `pre_order_service_fee` | `Biaya layanan pre-order` | `Pre-order service fee` | Ready alias |
| 18 | `mall_service_fee` | `Biaya layanan Mall` | `Mall service fee` | Ready alias |
| 19 | `payment_fee` | `Biaya Pembayaran` | `Payment Fee` | Ready alias |
| 20 | `platform_commission_before_discount` | `Biaya komisi sebelum diskon` | Belum ada di `TIKTOK_INCOME_COLUMN_MAP` saat ini | New target needed |
| 21 | `ads_discount` | `Diskon (dari belanja iklan)` | Belum ada di `TIKTOK_INCOME_COLUMN_MAP` saat ini | New target needed |
| 22 | `other_commission_discount` | `Diskon komisi lainnya` | Belum ada di `TIKTOK_INCOME_COLUMN_MAP` saat ini | New target needed |
| 23 | `credit_card_installment_handling_fee` | `Credit card installment - Handling fee` | Belum ada di `TIKTOK_INCOME_COLUMN_MAP` saat ini | New target needed |
| 24 | `shipping_cost` | `Ongkir` | `Shipping cost` | Ready alias |
| 25 | `shipping_costs_passed_on_to_the_logistics_provider` | `Ongkir yang ditalangi penyedia jasa logistik` | `Shipping costs passed on to the logistics provider` | Ready alias |
| 26 | `replacement_shipping_fee_passed_on_to_the_customer` | `Ongkir penggantian (ditanggung pembeli)` | `Replacement shipping fee (passed on to the customer)` | Ready alias |
| 27 | `exchange_shipping_fee_passed_on_to_the_customer` | `Ongkir penukaran (ditanggung pembeli)` | `Exchange shipping fee (passed on to the customer)` | Ready alias |
| 28 | `shipping_cost_borne_by_the_platform` | `Ongkir yang ditanggung platform` | `Shipping cost borne by the platform` | Ready alias |
| 29 | `shipping_cost_paid_by_the_customer` | `Ongkir yang ditanggung pembeli` | `Shipping cost paid by the customer` | Ready alias |
| 30 | `refunded_shipping_cost_paid_by_the_customer` | `Pengembalian ongkir yang ditanggung pembeli` | `Refunded shipping cost paid by the customer` | Ready alias |
| 31 | `return_shipping_costs_passed_on_to_the_customer` | `Ongkir pengembalian barang (yang ditanggung pembeli)` | `Return shipping costs (passed on to the customer)` | Ready alias |
| 32 | `shipping_cost_subsidy` | `Subsidi ongkir` | `Shipping cost subsidy` | Ready alias |
| 33 | `distance_shipping_fee_from_horizon_plus_program` | `Biaya pengiriman sesuai jarak dari Program Horison+` | `Distance shipping fee from Horizon+ Program` | Ready alias |
| 34 | `logistics_service_fee` | `Biaya layanan logistik` | `Logistics service fee` | Ready alias |
| 35 | `shipping_insurance_compensation` | `Penggantian dana asuransi` | `Shipping insurance compensation` | Ready alias |
| 36 | `affiliate_commission` | `Komisi Afiliasi` | `Affiliate Commission` | Ready alias |
| 37 | `affiliate_partner_commission` | `Komisi mitra afiliasi` | `Affiliate partner commission` | Ready alias |
| 38 | `affiliate_shop_ads_commission` | `Komisi Iklan Toko afiliasi` | `Affiliate Shop Ads commission` | Ready alias |
| 39 | `affiliate_commission_deposit` | `Deposit komisi afiliasi` | Belum ada di `TIKTOK_INCOME_COLUMN_MAP` saat ini | New target needed |
| 40 | `affiliate_commission_refund` | `Pengembalian dana komisi afiliasi` | Belum ada di `TIKTOK_INCOME_COLUMN_MAP` saat ini | New target needed |
| 41 | `affiliate_partner_shop_ads_commission` | `Komisi iklan toko Mitra Afiliasi` | `Affiliate Partner shop ads commission` | Ready alias |
| 42 | `shipping_fee_program_service_fee` | `Biaya layanan Program Bebas Ongkir` | `Shipping Fee Program service fee` | Ready alias |
| 43 | `dynamic_commission` | `Komisi dinamis` | `Dynamic commission` | Ready alias |
| 44 | `bonus_cashback_service_fee` | `Biaya layanan cashback bonus` | `Bonus cashback service fee` | Ready alias |
| 45 | `live_specials_service_fee` | `Biaya layanan Khusus LIVE` | `LIVE Specials service fee` | Ready alias |
| 46 | `voucher_xtra_service_fee` | `Biaya akses keuntungan eksklusif` | Kemungkinan padanan `Voucher Xtra service fee`; muncul duplikat pada sebagian signature | Review |
| 47 | `order_processing_fee` | `Biaya pemrosesan pesanan` | `Order processing fee` | Ready alias |
| 48 | `eams_program_service_fee` | `Biaya layanan Program EAMS` | `EAMS Program service fee` | Ready alias |
| 49 | `brands_crazy_deals_flash_sale_service_fee` | `Biaya layanan Brands Crazy Deal/Flash Sale` | `Brands Crazy Deals/Flash Sale service fee` | Ready alias |
| 50 | `dilayani_tokopedia_fee` | `Biaya Dilayani Tokopedia` | `Dilayani Tokopedia fee` | Ready alias |
| 51 | `dilayani_tokopedia_handling_fee` | `Biaya penanganan Dilayani Tokopedia` | `Dilayani Tokopedia handling fee` | Ready alias |
| 52 | `paylater_program_fee` | `Biaya program PayLater` | `PayLater program fee` | Ready alias |
| 53 | `campaign_resource_fee` | `Biaya sumber daya campaign` | `Campaign resource fee` | Ready alias |
| 54 | `installation_service_fee` | `Biaya layanan penginstalan` | `Installation service fee` | Ready alias |
| 55 | `article_22_income_tax_withheld` | `PPh Pasal 22 dipungut` | `Article 22 Income Tax withheld` | Ready alias |
| 56 | `platform_special_service_fee` | `Biaya layanan khusus platform` | `Platform special service fee` | Ready alias |
| 57 | `gmv_max_ad_fee` | `Biaya iklan GMV Max` | `GMV Max ad fee` | Ready alias |
| 58 | `gmv_max_coupon` | `Voucher GMV Max` | `GMV Max Coupon` / `GMV Max coupon` | Ready alias |
| 59 | `gmv_max_coupon_sales_tax` | `Pajak penjualan atas voucher GMV Max` | `GMV Max coupon sales tax` | Ready alias |
| 60 | `managed_service_plan_sales_tax` | `Program layanan terkelola (Pajak penjualan)` | `Managed service plan (Sales tax)` | Ready alias |
| 61 | `managed_service_plan_per_order_fee` | `Program layanan terkelola (Biaya per pesanan)` | `Managed service plan (Per order fee)` | Ready alias |
| 62 | `failed_delivery_shipping_fee` | `Ongkir pesanan gagal kirim` | Belum ada di `TIKTOK_INCOME_COLUMN_MAP` saat ini | New target needed |
| 63 | `buyer_fault_return_shipping_fee` | `Ongkir pengembalian barang karena kesalahan pembeli` | Belum ada di `TIKTOK_INCOME_COLUMN_MAP` saat ini | New target needed |
| 64 | `insurance_fee` | `Biaya asuransi` | Belum ada di `TIKTOK_INCOME_COLUMN_MAP` saat ini | New target needed |
| 65 | `ajustment_amount` | `Jumlah penyesuaian` | `Ajustment amount` | Ready alias |
| 66 | `related_order_id` | `ID pesanan terkait` | `Related order ID` | Ready alias |
| 67 | `customer_payment` | `Pembayaran oleh pembeli` | `Customer payment` | Ready alias |
| 68 | `customer_refund` | `Pengembalian dana pembeli` | `Customer refund` | Ready alias |
| 69 | `seller_co_funded_voucher_discount` | `Diskon voucher yang ditanggung penjual` | `Seller co-funded voucher discount` | Ready alias |
| 70 | `refund_of_seller_co_funded_voucher_discount` | `Pengembalian dana diskon voucher yang ditanggung penjual` | `Refund of seller co-funded voucher discount` | Ready alias |
| 71 | `platform_discounts` | `Diskon platform` | `Platform discounts` | Ready alias |
| 72 | `refund_of_platform_discounts` | `Pengembalian dana diskon platform` | `Refund of platform discounts` | Ready alias |
| 73 | `platform_co_funded_voucher_discounts` | `Diskon voucher yang ditanggung platform` | `Platform co-funded voucher discounts` | Ready alias |
| 74 | `refund_of_platform_co_funded_voucher_discounts` | `Pengembalian dana diskon voucher yang ditanggung platform` | `Refund of platform co-funded voucher discounts` | Ready alias |
| 75 | `seller_shipping_cost_discount` | `Diskon ongkir dari penjual` | `Seller shipping cost discount` | Ready alias |
| 76 | `estimated_package_weight` | `Perkiraan berat paket` | `Estimated package weight (g)` | Ready alias |
| 77 | `actual_package_weight` | `Berat paket yang bisa dikenai biaya` | `Actual package weight (g)` | Ready alias |
| 78 | `shopping_center_items` | `Detail produk terjual` | Padanan terdekat dari field detail item; perlu review nama target | Review |
| 79 | `order_source` | `Sumber pesanan` | `Order Source` | Ready alias |

## Schema Drift Notes

- Audit menemukan perubahan bahasa pada 2026 Mei/Juni: sheet order details berbahasa Indonesia (`Detail pesanan`).
- Mapping saat ini dominan bahasa Inggris; kolom Indonesia perlu alias sebelum dijadikan strict.
- File income juga memuat sheet `Withdrawal records`/versi Indonesia yang secara konsep report-like.
- Ditemukan temporary lock file `.~...xlsx`; file seperti ini harus diabaikan.

## Review Status

- Status: draft, perlu review bisnis untuk menentukan kolom required dan nullable.
- Setelah review, isi dokumen ini bisa diturunkan ke `config/schema_contracts.yml`.
