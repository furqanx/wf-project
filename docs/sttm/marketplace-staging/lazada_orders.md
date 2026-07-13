# Lazada Orders STTM

## Scope

- Target table: `stg_lazada_orders`
- Marketplace: `lazada`
- Phase: `Order`
- Source mapping constant: `LAZADA_ORDER_COLUMN_MAP`
- Schema guard constant: `VALID_LAZADA_ORDER_COLS`

## File Reading Rules

- File dibaca dengan `pd.read_excel(..., engine="openpyxl")` pada sheet pertama/default.
- Header berada pada baris pertama file.
- `nama_toko` diekstrak dari nama file; `source_filename` diisi dari nama file.
- Jika tabel fisik memiliki `uploaded_at`, kolom tersebut diasumsikan diisi oleh database/default load process, bukan kolom source file.

## Source Signature Summary

| Sheet / Role | Signature | Count | Years | Months | Language | Column Count | Example |
|---|---:|---:|---|---|---|---:|---|
| Order-like | `1656284506` | 9 | 2026 | april|juni|mei | english | 77 | `etc/fixed data/lazada/order/2026/april/4. Order Lazada Beras sehat 2026.xlsx || etc/fixed data/lazada/order/2026/april/4. Order Lazada Merapi 2026.xlsx || etc/fixed data/lazada/order/2026/april/4. Order Lazada Official 2026.xlsx || etc/fixed data/lazada/order/2026/juni/Order Lazada Merapi.xlsx || etc/fixed data/lazada/order/2026/juni/Order Lazada official.xlsx` |
| Order-like | `8e79deba6d` | 15 | 2024|2025|2026 | februari|januari|maret | english | 76 | `etc/fixed data/lazada/order/2024/Order Lazada Beras sehat 2024.xlsx || etc/fixed data/lazada/order/2024/Order Lazada Merapi 2024.xlsx || etc/fixed data/lazada/order/2024/Order Lazada Official 2024.xlsx || etc/fixed data/lazada/order/2025/Order Lazada Beras sehat 2025.xlsx || etc/fixed data/lazada/order/2025/Order Lazada Merapi 2025.xlsx` |

## Source To Target Mapping

| No | Target Column | Source Column | Required | Transform / Rule | Notes |
|---:|---|---|---|---|---|
| 1 | `order_item_id` | `orderItemId` | Review | Rename / normalize column name |  |
| 2 | `order_type` | `orderType` | Review | Rename / normalize column name |  |
| 3 | `guarantee` | `Guarantee` | Review | Rename / normalize column name |  |
| 4 | `delivery_type` | `deliveryType` | Review | Rename / normalize column name |  |
| 5 | `lazada_id` | `lazadaId` | Review | Rename / normalize column name |  |
| 6 | `seller_sku` | `sellerSku` | Review | Rename / normalize column name |  |
| 7 | `lazada_sku` | `lazadaSku` | Review | Rename / normalize column name |  |
| 8 | `warehouse` | `wareHouse` | Review | Rename / normalize column name |  |
| 9 | `create_time` | `createTime` | Review | Rename / normalize column name |  |
| 10 | `update_time` | `updateTime` | Review | Rename / normalize column name |  |
| 11 | `rts_sla` | `rtsSla` | Review | Rename / normalize column name |  |
| 12 | `tts_sla` | `ttsSla` | Review | Rename / normalize column name |  |
| 13 | `order_number` | `orderNumber` | Review | Rename / normalize column name |  |
| 14 | `invoice_required` | `invoiceRequired` | Review | Rename / normalize column name |  |
| 15 | `invoice_number` | `invoiceNumber` | Review | Rename / normalize column name |  |
| 16 | `delivered_date` | `deliveredDate` | Review | Rename / normalize column name |  |
| 17 | `customer_name` | `customerName` | Review | Rename / normalize column name |  |
| 18 | `customer_email` | `customerEmail` | Review | Rename / normalize column name |  |
| 19 | `national_registration_number` | `nationalRegistrationNumber` | Review | Rename / normalize column name |  |
| 20 | `shipping_name` | `shippingName` | Review | Rename / normalize column name |  |
| 21 | `shipping_address` | `shippingAddress` | Review | Rename / normalize column name |  |
| 22 | `shipping_address2` | `shippingAddress2` | Review | Rename / normalize column name |  |
| 23 | `shipping_address3` | `shippingAddress3` | Review | Rename / normalize column name |  |
| 24 | `shipping_address4` | `shippingAddress4` | Review | Rename / normalize column name |  |
| 25 | `shipping_address5` | `shippingAddress5` | Review | Rename / normalize column name |  |
| 26 | `shipping_phone` | `shippingPhone` | Review | Rename / normalize column name |  |
| 27 | `shipping_phone2` | `shippingPhone2` | Review | Rename / normalize column name |  |
| 28 | `shipping_city` | `shippingCity` | Review | Rename / normalize column name |  |
| 29 | `shipping_post_code` | `shippingPostCode` | Review | Rename / normalize column name |  |
| 30 | `shipping_country` | `shippingCountry` | Review | Rename / normalize column name |  |
| 31 | `shipping_region` | `shippingRegion` | Review | Rename / normalize column name |  |
| 32 | `billing_name` | `billingName` | Review | Rename / normalize column name |  |
| 33 | `billing_addr` | `billingAddr` | Review | Rename / normalize column name |  |
| 34 | `billing_addr2` | `billingAddr2` | Review | Rename / normalize column name |  |
| 35 | `billing_addr3` | `billingAddr3` | Review | Rename / normalize column name |  |
| 36 | `billing_addr4` | `billingAddr4` | Review | Rename / normalize column name |  |
| 37 | `billing_addr5` | `billingAddr5` | Review | Rename / normalize column name |  |
| 38 | `billing_phone` | `billingPhone` | Review | Rename / normalize column name |  |
| 39 | `billing_phone2` | `billingPhone2` | Review | Rename / normalize column name |  |
| 40 | `billing_city` | `billingCity` | Review | Rename / normalize column name |  |
| 41 | `billing_post_code` | `billingPostCode` | Review | Rename / normalize column name |  |
| 42 | `billing_country` | `billingCountry` | Review | Rename / normalize column name |  |
| 43 | `tax_code` | `taxCode` | Review | Rename / normalize column name |  |
| 44 | `branch_number` | `branchNumber` | Review | Rename / normalize column name |  |
| 45 | `tax_invoice_requested` | `taxInvoiceRequested` | Review | Rename / normalize column name |  |
| 46 | `pay_method` | `payMethod` | Review | Rename / normalize column name |  |
| 47 | `paid_price` | `paidPrice` | Review | Rename / normalize column name |  |
| 48 | `unit_price` | `unitPrice` | Review | Rename / normalize column name |  |
| 49 | `seller_discount_total` | `sellerDiscountTotal` | Review | Rename / normalize column name |  |
| 50 | `shipping_fee` | `shippingFee` | Review | Rename / normalize column name |  |
| 51 | `wallet_credit` | `walletCredit` | Review | Rename / normalize column name |  |
| 52 | `item_name` | `itemName` | Review | Rename / normalize column name |  |
| 53 | `variation` | `variation` | Review | Rename / normalize column name |  |
| 54 | `cd_shipping_provider` | `cdShippingProvider` | Review | Rename / normalize column name |  |
| 55 | `shipping_provider` | `shippingProvider` | Review | Rename / normalize column name |  |
| 56 | `shipment_type_name` | `shipmentTypeName` | Review | Rename / normalize column name |  |
| 57 | `shipping_provider_type` | `shippingProviderType` | Review | Rename / normalize column name |  |
| 58 | `cd_tracking_code` | `cdTrackingCode` | Review | Rename / normalize column name |  |
| 59 | `tracking_code` | `trackingCode` | Review | Rename / normalize column name |  |
| 60 | `tracking_url` | `trackingUrl` | Review | Rename / normalize column name |  |
| 61 | `shipping_provider_fm` | `shippingProviderFM` | Review | Rename / normalize column name |  |
| 62 | `tracking_code_fm` | `trackingCodeFM` | Review | Rename / normalize column name |  |
| 63 | `tracking_url_fm` | `trackingUrlFM` | Review | Rename / normalize column name |  |
| 64 | `promised_shipping_time` | `promisedShippingTime` | Review | Rename / normalize column name |  |
| 65 | `premium` | `premium` | Review | Rename / normalize column name |  |
| 66 | `status` | `status` | Review | Rename / normalize column name |  |
| 67 | `buyer_failed_delivery_return_initiator` | `buyerFailedDeliveryReturnInitiator` | Review | Rename / normalize column name |  |
| 68 | `buyer_failed_delivery_reason` | `buyerFailedDeliveryReason` | Review | Rename / normalize column name |  |
| 69 | `buyer_failed_delivery_detail` | `buyerFailedDeliveryDetail` | Review | Rename / normalize column name |  |
| 70 | `buyer_failed_delivery_user_name` | `buyerFailedDeliveryUserName` | Review | Rename / normalize column name |  |
| 71 | `bundle_id` | `bundleId` | Review | Rename / normalize column name |  |
| 72 | `semi_managed` | `semiManaged` | Review | Rename / normalize column name |  |
| 73 | `flexible_delivery_time` | `flexibleDeliveryTime` | Review | Rename / normalize column name |  |
| 74 | `bundle_discount` | `bundleDiscount` | Review | Rename / normalize column name |  |
| 75 | `refund_amount` | `refundAmount` | Review | Rename / normalize column name |  |
| 76 | `seller_note` | `sellerNote` | Review | Rename / normalize column name |  |
| 77 | `platform_discount_total` | `platformDiscountTotal` | Review | Rename / normalize column name |  |
| 78 | `nama_toko` | Injected from filename / override | Review | Injected metadata | Bukan kolom asli file sumber. |
| 79 | `source_filename` | Injected from file basename | Review | Injected metadata | Bukan kolom asli file sumber. |

## Schema Drift Notes

- Audit menemukan 2 signature: file lama tanpa `platformDiscountTotal`, file baru dengan `platformDiscountTotal`.
- `platformDiscountTotal` sudah dimapping ke `platform_discount_total` dan diizinkan dalam schema guard.

## Review Status

- Status: draft, perlu review bisnis untuk menentukan kolom required dan nullable.
- Setelah review, isi dokumen ini bisa diturunkan ke `config/schema_contracts.yml`.
