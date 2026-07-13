# Shopee Income Adjustment STTM

## Scope

- Target table: `stg_shopee_income_adjustment`
- Marketplace: `shopee`
- Phase: `Income`
- Source mapping constant: `SHOPEE_INCOME_ADJ_COLUMN_MAP`
- Schema guard constant: `VALID_SHOPEE_INCOME_ADJ_COLS`

## File Reading Rules

- Sheet diproses jika nama sheet mengandung `adjustment`.
- Header dicari dinamis: baris dengan kolom pertama `No.` dan kolom sekitar berisi `tanggal` atau `tipe`.
- Baris kosong dan baris total pada kolom `no` dibuang sebelum load.
- Jika tabel fisik memiliki `uploaded_at`, kolom tersebut diasumsikan diisi oleh database/default load process, bukan kolom source file.

## Source Signature Summary

| Sheet / Role | Signature | Count | Years | Months | Language | Column Count | Example |
|---|---:|---:|---|---|---|---:|---|
| Adjustment | `98efe71331c2` | 108 |  |  | - | 7 | `income/2023/Income.sudah dilepas.id.20230101_20231231 berasporangporice.xlsx | income/2023/Income.sudah dilepas.id.20230101_20231231 berassehat.xlsx` |

## Source To Target Mapping

| No | Target Column | Source Column | Required | Transform / Rule | Notes |
|---:|---|---|---|---|---|
| 1 | `no` | `No.` | Review | Rename / normalize column name |  |
| 2 | `tanggal_penyesuaian_dibuat` | `Tanggal Penyesuaian Dibuat` | Review | Rename / normalize column name |  |
| 3 | `tipe_penyesuaian_deskripsi` | `Tipe Penyesuaian | Deskripsi` | Review | Rename / normalize column name |  |
| 4 | `alasan_penyesuaian` | `Alasan Penyesuaian` | Review | Rename / normalize column name |  |
| 5 | `biaya_penyesuaian` | `Biaya Penyesuaian` | Review | Rename / normalize column name |  |
| 6 | `no_pesanan_terhubung` | `No. Pesanan Terhubung` | Review | Rename / normalize column name |  |
| 7 | `tanggal_dana_dilepaskan` | `Tanggal Dana Dilepaskan` | Review | Rename / normalize column name |  |
| 8 | `nama_toko` | Injected from filename / override | Review | Injected metadata | Bukan kolom asli file sumber. |
| 9 | `source_filename` | Injected from file basename | Review | Injected metadata | Bukan kolom asli file sumber. |

## Schema Drift Notes

- Audit menemukan signature adjustment stabil.
- Loader memakai dynamic anchor agar tahan terhadap tambahan baris metadata di atas header.

## Review Status

- Status: draft, perlu review bisnis untuk menentukan kolom required dan nullable.
- Setelah review, isi dokumen ini bisa diturunkan ke `config/schema_contracts.yml`.
