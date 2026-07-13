# Shopee Report STTM

## Scope

- Target table: `stg_shopee_report`
- Marketplace: `shopee`
- Phase: `Report`
- Source mapping constant: `SHOPEE_REPORT_COLUMN_MAP`
- Schema guard constant: `VALID_SHOPEE_REPORT_COLS`

## File Reading Rules

- File report Shopee wajib memiliki sheet `Transaction Report` menurut loader saat ini.
- Header berada pada row index 17; data dimulai dari row index 18.
- `nama_toko` diekstrak dari nama file; `source_filename` diisi dari nama file.
- Jika tabel fisik memiliki `uploaded_at`, kolom tersebut diasumsikan diisi oleh database/default load process, bukan kolom source file.

## Source Signature Summary

| Sheet / Role | Signature | Count | Years | Months | Language | Column Count | Example |
|---|---:|---:|---|---|---|---:|---|
| Unknown report-like sheet | `3b36f4293b2c` | 1 |  |  | - | 8 | `report/2025/7. Report Shopee Official.xlsx` |
| Transaction Report | `3b36f4293b2c` | 257 |  |  | - | 8 | `report/2022/Report Shopee official.xlsx | report/2023/Report Shopee bandar organik.xlsx` |

## Source To Target Mapping

| No | Target Column | Source Column | Required | Transform / Rule | Notes |
|---:|---|---|---|---|---|
| 1 | `tanggal_transaksi` | `Tanggal Transaksi` | Review | Rename / normalize column name |  |
| 2 | `tipe_transaksi` | `Tipe Transaksi` | Review | Rename / normalize column name |  |
| 3 | `deskripsi` | `Deskripsi` | Review | Rename / normalize column name |  |
| 4 | `no_pesanan` | `No. Pesanan` | Review | Rename / normalize column name |  |
| 5 | `jenis_transaksi` | `Jenis Transaksi` | Review | Rename / normalize column name |  |
| 6 | `jumlah` | `Jumlah` | Review | Rename / normalize column name |  |
| 7 | `status` | `Status` | Review | Rename / normalize column name |  |
| 8 | `saldo_akhir` | `Saldo Akhir` | Review | Rename / normalize column name |  |
| 9 | `nama_toko` | Injected from filename / override | Review | Injected metadata | Bukan kolom asli file sumber. |
| 10 | `source_filename` | Injected from file basename | Review | Injected metadata | Bukan kolom asli file sumber. |

## Schema Drift Notes

- Audit menemukan 1 file report Shopee dengan sheet `Sheet1`, bukan `Transaction Report`.
- File anomali tersebut memiliki header report-like pada Excel row 3; loader saat ini akan mengabaikannya sampai rule fallback ditambahkan.

## Review Status

- Status: draft, perlu review bisnis untuk menentukan kolom required dan nullable.
- Setelah review, isi dokumen ini bisa diturunkan ke `config/schema_contracts.yml`.
