# Shopee Income Shipping Discrepancy STTM

## Scope

- Target table: `stg_shopee_income_shipping_discrepancy`
- Marketplace: `shopee`
- Phase: `Income`
- Source mapping constant: `SHOPEE_INCOME_SD_COLUMN_MAP`
- Schema guard constant: `VALID_SHOPEE_INCOME_SD_COLS`

## File Reading Rules

- Sheet diproses jika nama sheet mengandung `shipping fee`.
- Header row index 1; data row index 2.
- Jika tabel fisik memiliki `uploaded_at`, kolom tersebut diasumsikan diisi oleh database/default load process, bukan kolom source file.

## Source Signature Summary

| Sheet / Role | Signature | Count | Years | Months | Language | Column Count | Example |
|---|---:|---:|---|---|---|---:|---|
| Shipping Fee | `e740eaf404f8` | 79 |  |  | - | 4 | `income/2023/Income.sudah dilepas.id.20230101_20231231 berasporangporice.xlsx | income/2023/Income.sudah dilepas.id.20230101_20231231 berassehat.xlsx` |

## Source To Target Mapping

| No | Target Column | Source Column | Required | Transform / Rule | Notes |
|---:|---|---|---|---|---|
| 1 | `no_pesanan` | `No. Pesanan` | Review | Rename / normalize column name |  |
| 2 | `estimasi_ongkos_kirim` | `Estimasi Ongkos Kirim:` | Review | Rename / normalize column name |  |
| 3 | `ongkos_kirim_yang_dibayarkan_ke_jasa_kirim` | `Ongkos Kirim yang Dibayarkan ke Jasa Kirim:` | Review | Rename / normalize column name |  |
| 4 | `discrepancy_reason` | `Discrepancy reason` | Review | Rename / normalize column name |  |
| 5 | `nama_toko` | Injected from filename / override | Review | Injected metadata | Bukan kolom asli file sumber. |
| 6 | `source_filename` | Injected from file basename | Review | Injected metadata | Bukan kolom asli file sumber. |

## Schema Drift Notes

- Audit menemukan signature shipping fee/discrepancy yang konsisten untuk kolom utama.

## Review Status

- Status: draft, perlu review bisnis untuk menentukan kolom required dan nullable.
- Setelah review, isi dokumen ini bisa diturunkan ke `config/schema_contracts.yml`.
