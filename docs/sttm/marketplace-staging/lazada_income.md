# Lazada Income STTM

## Scope

- Target table: `stg_lazada_income`
- Marketplace: `lazada`
- Phase: `Income`
- Source mapping constant: `LAZADA_INCOME_COLUMN_MAP`
- Schema guard constant: `VALID_LAZADA_INCOME_COLS`

## File Reading Rules

- File dibaca dengan `pd.read_excel(..., engine="openpyxl")` pada sheet pertama/default.
- Header berada pada baris pertama file.
- `nama_toko` diekstrak dari nama file; `source_filename` diisi dari nama file.
- Jika tabel fisik memiliki `uploaded_at`, kolom tersebut diasumsikan diisi oleh database/default load process, bukan kolom source file.

## Source Signature Summary

| Sheet / Role | Signature | Count | Years | Months | Language | Column Count | Example |
|---|---:|---:|---|---|---|---:|---|
| Income-like | `deb270e99b` | 24 | 2024|2025|2026 | april|februari|januari|juni|maret|mei | indonesian | 19 | `etc/fixed data/lazada/income/2024/Income Lazada Beras sehat 2024.xlsx || etc/fixed data/lazada/income/2024/Income Lazada Merapi 2024.xlsx || etc/fixed data/lazada/income/2024/Income Lazada Official 2024.xlsx || etc/fixed data/lazada/income/2025/Income Lazada Beras sehat 2025.xlsx || etc/fixed data/lazada/income/2025/Income Lazada Merapi 2025.xlsx` |

## Source To Target Mapping

| No | Target Column | Source Column | Required | Transform / Rule | Notes |
|---:|---|---|---|---|---|
| 1 | `periode_laporan` | `Periode Laporan` | Review | Rename / normalize column name |  |
| 2 | `nomor_laporan` | `Nomor Laporan` | Review | Rename / normalize column name |  |
| 3 | `tanggal_transaksi` | `Tanggal Transaksi` | Review | Rename / normalize column name |  |
| 4 | `nama_biaya` | `Nama Biaya` | Review | Rename / normalize column name |  |
| 5 | `jumlah_termasuk_pajak` | `Jumlah (Termasuk Pajak)` | Review | Rename / normalize column name |  |
| 6 | `vat_amount` | `VAT Amount` | Review | Rename / normalize column name |  |
| 7 | `status_pelepasan_dana` | `Status Pelepasan Dana` | Review | Rename / normalize column name |  |
| 8 | `tanggal_dilepas` | `Tanggal Dilepas` | Review | Rename / normalize column name |  |
| 9 | `komentar` | `Komentar` | Review | Rename / normalize column name |  |
| 10 | `tanggal_pesanan_dibuat` | `Tanggal Pesanan Dibuat` | Review | Rename / normalize column name |  |
| 11 | `nomor_pesanan` | `Nomor Pesanan` | Review | Rename / normalize column name |  |
| 12 | `id_pesanan` | `ID Pesanan` | Review | Rename / normalize column name |  |
| 13 | `sku_penjual` | `SKU Penjual` | Review | Rename / normalize column name |  |
| 14 | `lazada_sku` | `Lazada SKU` | Review | Rename / normalize column name |  |
| 15 | `wht_amount` | `WHT Amount` | Review | Rename / normalize column name |  |
| 16 | `wht_termasuk_dalam_jumlah` | `WHT termasuk dalam jumlah` | Review | Rename / normalize column name |  |
| 17 | `status_pesanan` | `Status Pesanan` | Review | Rename / normalize column name |  |
| 18 | `nama_produk` | `Nama Produk` | Review | Rename / normalize column name |  |
| 19 | `short_code` | `Short Code` | Review | Rename / normalize column name |  |
| 20 | `nama_toko` | Injected from filename / override | Review | Injected metadata | Bukan kolom asli file sumber. |
| 21 | `source_filename` | Injected from file basename | Review | Injected metadata | Bukan kolom asli file sumber. |

## Schema Drift Notes

- Audit menemukan 1 signature stabil untuk semua file Lazada Income.
- Bahasa kolom sumber konsisten dalam Bahasa Indonesia.

## Review Status

- Status: draft, perlu review bisnis untuk menentukan kolom required dan nullable.
- Setelah review, isi dokumen ini bisa diturunkan ke `config/schema_contracts.yml`.
