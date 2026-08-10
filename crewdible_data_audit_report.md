# Audit Data Crewdible

| Area | Temuan |
|---|---|
| Total file | 30 file |
| Ekstensi | 16 `.xlsx`, 14 `.xls` |
| Format fisik | Semua file berhasil dibaca sebagai `xlsx_zip`; file `.xls` sebenarnya workbook Excel 2007+ dengan ekstensi lama/salah. |
| Signature kolom | 1 signature; signature utama berisi 35 kolom transaksi. |
| Total row fisik | 340,732 row setelah header. |
| Total transaksi logis | 157,754 row transaksi dengan kolom `No` terisi. |
| Row lanjutan packaging | 182,978 row lanjutan dengan `No` kosong, umumnya detail material packaging tambahan. |

## Ringkasan Per Folder

| Folder | File/Sheet | Ekstensi | Sheet | Header Row | Row Fisik | Transaksi | Row Lanjutan | Marketplace | Status | Error |
|---|---:|---|---|---|---:|---:|---:|---|---|---:|
| 2023 Transaksi | 1 | .xlsx:1 | Sheet1:1 | 1:1 | 2,367 | 969 | 1,398 | LAZADA, SHOPEE | CANCELLED, DONE, REJECT | 0 |
| 2024 Transaksi | 12 | .xls:12 | Transaction:12 | 1:12 | 72,281 | 29,606 | 42,675 | LAZADA, SHOPEE, TIKTOK | CANCELLED, DONE, PENDING, REJECT | 0 |
| 2025 Transaksi | 12 | .xlsx:12 | Transaction:12 | 2:12 | 153,402 | 71,846 | 81,556 | LAZADA, SHOPEE, TIKTOK | CANCELLED, DONE, PENDING, REJECT | 0 |
| 2026 Transaksi | 5 | .xls:2, .xlsx:3 | Transaction:5 | 1:5 | 112,682 | 55,333 | 57,349 | LAZADA, SHOPEE, TIKTOK | CANCELLED, DONE, PENDING, PENDING AWB, REJECT | 0 |

## Kolom Utama

| No | Kolom |
|---:|---|
| 1 | `No` |
| 2 | `Gudang` |
| 3 | `Tanggal Transaksi` |
| 4 | `No. Transaksi` |
| 5 | `Status` |
| 6 | `Pengirim` |
| 7 | `No. HP Pengirim` |
| 8 | `Nama Toko` |
| 9 | `Nama Marketplace` |
| 10 | `Penerima` |
| 11 | `No. HP Penerima` |
| 12 | `Alamat Penerima` |
| 13 | `Nama Produk` |
| 14 | `No. SKU` |
| 15 | `Qty Produk` |
| 16 | `Harga Produk` |
| 17 | `Total Harga Produk` |
| 18 | `Total Nilai Transaksi` |
| 19 | `Biaya Transaksi` |
| 20 | `PPN Biaya Transaksi` |
| 21 | `Material Packaging` |
| 22 | `Harga Material Packaging` |
| 23 | `Qty Material Packaging` |
| 24 | `Total Harga Material Packaging` |
| 25 | `Total Biaya Packaging` |
| 26 | `PPN Total Biaya Packaging` |
| 27 | `Total Biaya QC` |
| 28 | `PPN Total Biaya QC` |
| 29 | `Total Biaya Shipping Label` |
| 30 | `PPN Total Biaya Shipping Label` |
| 31 | `Logistik` |
| 32 | `Kode Booking` |
| 33 | `No. AWB` |
| 34 | `Biaya Logistik` |
| 35 | `Total Biaya Transaksi` |

## Catatan Desain Loader

- Jangan mengandalkan ekstensi file. File `.xls` Crewdible perlu dibaca sebagai workbook `.xlsx`/zip.
- Header tidak selalu di baris yang sama: 2023 dan sebagian 2026 di baris 1, 2025 di baris 2.
- Satu transaksi bisa memiliki beberapa row karena material packaging tambahan. Grain raw sebaiknya tetap per row fisik, sedangkan downstream transaksi perlu memakai `No. Transaksi`/`No` dan row lanjutan packaging perlu ditangani.
- Nama sheet tidak sepenuhnya seragam: 2023 memakai `Sheet1`, mayoritas lain memakai `Transaction`. Loader sebaiknya mencari sheet berisi header 35 kolom, bukan hard-code satu nama sheet saja.

Detail per file tersedia di `crewdible_data_sheet_column_audit.csv`.
