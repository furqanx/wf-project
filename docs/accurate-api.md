# Accurate API

## Master / Reference Data

Menyimpan profil entitas utama dan konfigurasi dasar yang relatif jarang berubah.

| No. | Kategori | Endpoint |
|---:|---|---|
| 1 | Branch | `/api/branch` |
| 2 | Department | `/api/department` |
| 3 | Employee | `/api/employee` |
| 4 | Currency | `/api/currency` |
| 5 | Customer | `/api/customer` |
| 6 | Customer Category | `/api/customer-category` |
| 7 | Fixed Asset | `/api/fixed-asset` |
| 8 | FOB | `/api/fob` |
| 9 | Free On Board | `/api/freeonboard` |
| 10 | General Ledger Account | `/api/glaccount` |
| 11 | Item | `/api/item` |
| 12 | Item Category | `/api/item-category` |
| 13 | Payment Term | `/api/payment-term` |
| 14 | Price Category | `/api/price-category` |
| 15 | Project | `/api/project` |
| 16 | Shipment | `/api/shipment` |
| 17 | Tax | `/api/tax` |
| 18 | Unit | `/api/unit` |
| 19 | Vendor | `/api/vendor` |
| 20 | Vendor Category | `/api/vendor-category` |
| 21 | Vendor Price | `/api/vendor-price` |
| 22 | Warehouse | `/api/warehouse` |

## Sales

Menyimpan dokumen operasional yang berhubungan dengan pelanggan, penjualan, piutang, pengiriman, dan pendapatan.

| No. | Kategori | Endpoint |
|---:|---|---|
| 1 | Customer Claim | `/api/customer-claim` |
| 2 | Exchange Invoice | `/api/exchange-invoice` |
| 3 | Sales Check-in | `/api/sales-checkin` |
| 4 | Sales Invoice | `/api/sales-invoice` |
| 5 | Sales Order | `/api/sales-order` |
| 6 | Sales Quotation | `/api/sales-quotation` |
| 7 | Sales Receipt | `/api/sales-receipt` |
| 8 | Sales Return | `/api/sales-return` |
| 9 | Salesman Commission | `/api/salesman-commission` |
| 10 | Selling Price Adjustment | `/api/sellingprice-adjustment` |

## Purchases

Menyimpan dokumen pengadaan barang, pembelian, retur pembelian, pembayaran, dan tagihan dari pemasok.

| No. | Kategori | Endpoint |
|---:|---|---|
| 1 | Purchase Order | `/api/purchase-order` |
| 2 | Purchase Invoice | `/api/purchase-invoice` |
| 3 | Purchase Payment | `/api/purchase-payment` |
| 4 | Purchase Requisition | `/api/purchase-requisition` |
| 5 | Purchase Return | `/api/purchase-return` |
| 6 | Vendor Claim | `/api/vendor-claim` |

## Inventory

Menyimpan pergerakan fisik barang keluar, masuk, transfer, penyesuaian, dan stock opname.

| No. | Kategori | Endpoint |
|---:|---|---|
| 1 | Delivery Order | `/api/delivery-order` |
| 2 | Item Adjustment | `/api/item-adjustment` |
| 3 | Item Transfer | `/api/item-transfer` |
| 4 | Receive Item | `/api/receive-item` |
| 5 | Stock Opname Order | `/api/stock-opname-order` |
| 6 | Stock Opname Result | `/api/stock-opname-result` |

## Finance

Menyimpan pencatatan biaya, mutasi rekening, kas masuk/keluar, dan jurnal umum.

| No. | Kategori | Endpoint |
|---:|---|---|
| 1 | Bank Transfer | `/api/bank-transfer` |
| 2 | Expense | `/api/expense` |
| 3 | Journal Voucher | `/api/journal-voucher` |
| 4 | Other Deposit | `/api/other-deposit` |
| 5 | Other Payment | `/api/other-payment` |

## Manufacturing

Menyimpan instruksi kerja, bill of material, proses produksi, material slip, dan dokumen pabrikasi.

| No. | Kategori | Endpoint |
|---:|---|---|
| 1 | Bill of Material | `/api/bill-of-material` |
| 2 | BOM Process Category | `/api/bom-process-category` |
| 3 | Finished Good Slip | `/api/finished-good-slip` |
| 4 | Job Order | `/api/job-order` |
| 5 | Manufacture Order | `/api/manufacture-order` |
| 6 | Material Adjustment | `/api/material-adjustment` |
| 7 | Material Slip | `/api/material-slip` |
| 8 | Process Stages | `/api/process-stages` |
| 9 | Standard Product Cost | `/api/standard-product-cost` |
| 10 | WO PIC | `/api/wo-pic` |
| 11 | Work Order | `/api/work-order` |

## POS

Menyimpan data dan transaksi dari modul kasir offline.

| No. | Kategori | Endpoint |
|---:|---|---|
| 1 | POS Customer | `/api/pos/customer` |
| 2 | POS Item | `/api/pos/item` |
| 3 | POS Transaction | `/api/pos/transaction` |

## System Config

Menyimpan data konfigurasi sistem, penomoran, klasifikasi, laporan, dan proses tutup buku.

| No. | Kategori | Endpoint |
|---:|---|---|
| 1 | Auto Number | `/api/auto-number` |
| 2 | Data Classification | `/api/data-classification` |
| 3 | Report | `/api/report` |
| 4 | Roll Over | `/api/roll-over` |
