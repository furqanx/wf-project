# TikTok-Tokopedia Orders STTM

## Scope

- Target table: `stg_tiktok_tokopedia_orders`
- Marketplace: `tiktok_tokopedia`
- Phase: `Order`
- Source mapping constant: `TIKTOK_ORDER_COLUMN_MAP`
- Schema guard constant: `VALID_TIKTOK_ORDER_COLS`

## File Reading Rules

- File TikTok/Tokopedia order dibaca dengan `openpyxl.load_workbook(..., data_only=True)` pada active sheet.
- Header berada pada row index 0; row index 1 adalah deskripsi kolom dan dilewati; data dimulai dari row index 2.
- `nama_toko` diekstrak dari nama file; `source_filename` diisi dari nama file.
- Jika tabel fisik memiliki `uploaded_at`, kolom tersebut diasumsikan diisi oleh database/default load process, bukan kolom source file.

## Source Signature Summary

| Sheet / Role | Signature | Count | Years | Months | Language | Column Count | Example |
|---|---:|---:|---|---|---|---:|---|
| Order-like | `5822a61ada` | 100 | 2023|2024|2025|2026 | april|februari|januari|juni|maret|mei | english | 63 | `etc/fixed data/tiktok-tokopedia/order/2023/Order TikTok Beras Sehat Shop 2023.xlsx || etc/fixed data/tiktok-tokopedia/order/2023/Order TikTok Bogor Healthy Store 2023.xlsx || etc/fixed data/tiktok-tokopedia/order/2023/Order TikTok Owellness 2023.xlsx || etc/fixed data/tiktok-tokopedia/order/2023/Order TikTok Porice Beras Porang 2023.xlsx || etc/fixed data/tiktok-tokopedia/order/2023/Order TikTok Wellfarm Shop 2023.xlsx` |

## Source To Target Mapping

| No | Target Column | Source Column | Required | Transform / Rule | Notes |
|---:|---|---|---|---|---|
| 1 | `order_id` | `Order ID` | Review | Rename / normalize column name |  |
| 2 | `order_status` | `Order Status` | Review | Rename / normalize column name |  |
| 3 | `order_substatus` | `Order Substatus` | Review | Rename / normalize column name |  |
| 4 | `cancelation_return_type` | `Cancelation/Return Type` | Review | Rename / normalize column name |  |
| 5 | `normal_or_pre_order` | `Normal or Pre-order` | Review | Rename / normalize column name |  |
| 6 | `sku_id` | `SKU ID` | Review | Rename / normalize column name |  |
| 7 | `seller_sku` | `Seller SKU` | Review | Rename / normalize column name |  |
| 8 | `product_name` | `Product Name` | Review | Rename / normalize column name |  |
| 9 | `variation` | `Variation` | Review | Rename / normalize column name |  |
| 10 | `quantity` | `Quantity` | Review | Rename / normalize column name |  |
| 11 | `sku_quantity_of_return` | `Sku Quantity of return` | Review | Rename / normalize column name |  |
| 12 | `sku_unit_original_price` | `SKU Unit Original Price` | Review | Rename / normalize column name |  |
| 13 | `sku_subtotal_before_discount` | `SKU Subtotal Before Discount` | Review | Rename / normalize column name |  |
| 14 | `sku_platform_discount` | `SKU Platform Discount` | Review | Rename / normalize column name |  |
| 15 | `sku_seller_discount` | `SKU Seller Discount` | Review | Rename / normalize column name |  |
| 16 | `sku_subtotal_after_discount` | `SKU Subtotal After Discount` | Review | Rename / normalize column name |  |
| 17 | `shipping_fee_after_discount` | `Shipping Fee After Discount` | Review | Rename / normalize column name |  |
| 18 | `original_shipping_fee` | `Original Shipping Fee` | Review | Rename / normalize column name |  |
| 19 | `shipping_fee_seller_discount` | `Shipping Fee Seller Discount` | Review | Rename / normalize column name |  |
| 20 | `shipping_fee_platform_discount` | `Shipping Fee Platform Discount` | Review | Rename / normalize column name |  |
| 21 | `distance_shipping_fee` | `Distance Shipping Fee` | Review | Rename / normalize column name |  |
| 22 | `distance_fee` | `Distance Fee` | Review | Rename / normalize column name |  |
| 23 | `order_refund_amount` | `Order Refund Amount` | Review | Rename / normalize column name |  |
| 24 | `payment_platform_discount` | `Payment platform discount` | Review | Rename / normalize column name |  |
| 25 | `buyer_service_fee` | `Buyer Service Fee` | Review | Rename / normalize column name |  |
| 26 | `handling_fee` | `Handling Fee` | Review | Rename / normalize column name |  |
| 27 | `shipping_insurance` | `Shipping Insurance` | Review | Rename / normalize column name |  |
| 28 | `item_insurance` | `Item Insurance` | Review | Rename / normalize column name |  |
| 29 | `order_amount` | `Order Amount` | Review | Rename / normalize column name |  |
| 30 | `created_time` | `Created Time` | Review | Rename / normalize column name |  |
| 31 | `paid_time` | `Paid Time` | Review | Rename / normalize column name |  |
| 32 | `rts_time` | `RTS Time` | Review | Rename / normalize column name |  |
| 33 | `shipped_time` | `Shipped Time` | Review | Rename / normalize column name |  |
| 34 | `delivered_time` | `Delivered Time` | Review | Rename / normalize column name |  |
| 35 | `cancelled_time` | `Cancelled Time` | Review | Rename / normalize column name |  |
| 36 | `cancel_by` | `Cancel By` | Review | Rename / normalize column name |  |
| 37 | `cancel_reason` | `Cancel Reason` | Review | Rename / normalize column name |  |
| 38 | `fulfillment_type` | `Fulfillment Type` | Review | Rename / normalize column name |  |
| 39 | `warehouse_name` | `Warehouse Name` | Review | Rename / normalize column name |  |
| 40 | `tracking_id` | `Tracking ID` | Review | Rename / normalize column name |  |
| 41 | `delivery_option` | `Delivery Option` | Review | Rename / normalize column name |  |
| 42 | `shipping_provider_name` | `Shipping Provider Name` | Review | Rename / normalize column name |  |
| 43 | `buyer_message` | `Buyer Message` | Review | Rename / normalize column name |  |
| 44 | `buyer_username` | `Buyer Username` | Review | Rename / normalize column name |  |
| 45 | `recipient` | `Recipient` | Review | Rename / normalize column name |  |
| 46 | `phone_number` | `Phone #` | Review | Rename / normalize column name |  |
| 47 | `zipcode` | `Zipcode` | Review | Rename / normalize column name |  |
| 48 | `country` | `Country` | Review | Rename / normalize column name |  |
| 49 | `province` | `Province` | Review | Rename / normalize column name |  |
| 50 | `regency_and_city` | `Regency and City` | Review | Rename / normalize column name |  |
| 51 | `districts` | `Districts` | Review | Rename / normalize column name |  |
| 52 | `villages` | `Villages` | Review | Rename / normalize column name |  |
| 53 | `detail_address` | `Detail Address` | Review | Rename / normalize column name |  |
| 54 | `additional_address_information` | `Additional address information` | Review | Rename / normalize column name |  |
| 55 | `payment_method` | `Payment Method` | Review | Rename / normalize column name |  |
| 56 | `weight_kg` | `Weight(kg)` | Review | Rename / normalize column name |  |
| 57 | `product_category` | `Product Category` | Review | Rename / normalize column name |  |
| 58 | `package_id` | `Package ID` | Review | Rename / normalize column name |  |
| 59 | `purchase_channel` | `Purchase Channel` | Review | Rename / normalize column name |  |
| 60 | `seller_note` | `Seller Note` | Review | Rename / normalize column name |  |
| 61 | `checked_status` | `Checked Status` | Review | Rename / normalize column name |  |
| 62 | `checked_marked_by` | `Checked Marked by` | Review | Rename / normalize column name |  |
| 63 | `tokopedia_invoice_number` | `Tokopedia Invoice Number` | Review | Rename / normalize column name |  |
| 64 | `nama_toko` | Injected from filename / override | Review | Injected metadata | Bukan kolom asli file sumber. |
| 65 | `source_filename` | Injected from file basename | Review | Injected metadata | Bukan kolom asli file sumber. |

## Indonesian Sheet / Column Aliases

- Audit `fixed data` saat ini belum menemukan file order TikTok-Tokopedia dengan sheet atau kolom berbahasa Indonesia.
- Signature order yang ditemukan masih stabil dalam bahasa Inggris: 1 signature, 63 kolom source.
- Karena belum ada contoh aktual, alias Indonesia untuk `TIKTOK_ORDER_COLUMN_MAP` belum direkomendasikan untuk ditambahkan.
- Jika nanti muncul file order berbahasa Indonesia, perlu audit ulang sebelum mapping ditambahkan agar tidak menebak nama kolom.

## Schema Drift Notes

- Audit menemukan signature order stabil dan berbahasa Inggris untuk semua file yang diaudit.

## Review Status

- Status: draft, perlu review bisnis untuk menentukan kolom required dan nullable.
- Setelah review, isi dokumen ini bisa diturunkan ke `config/schema_contracts.yml`.
