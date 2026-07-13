# Lazada Report STTM

## Scope

- Target table: `stg_lazada_report`
- Marketplace: `lazada`
- Phase: `Report`
- Source mapping constant: `LAZADA_REPORT_COLUMN_MAP`
- Schema guard constant: `VALID_LAZADA_REPORT_COLS`

## File Reading Rules

- File dibaca dengan `openpyxl` dari sheet wajib `Balance Transactions`.
- Header berada pada baris pertama sheet.
- `nama_toko` diekstrak dari nama file; `source_filename` diisi dari nama file.
- Jika tabel fisik memiliki `uploaded_at`, kolom tersebut diasumsikan diisi oleh database/default load process, bukan kolom source file.

## Source Signature Summary

| Sheet / Role | Signature | Count | Years | Months | Language | Column Count | Example |
|---|---:|---:|---|---|---|---:|---|
| Balance Transactions | `f0de9a0212` | 18 | 2024|2025|2026 | april|januari februari maret|juni|mei | english | 6 | `etc/fixed data/lazada/report/2024/Report Lazada Beras sehat 2024.xlsx || etc/fixed data/lazada/report/2024/Report Lazada Merapi 2024.xlsx || etc/fixed data/lazada/report/2024/Report Lazada Official 2024.xlsx || etc/fixed data/lazada/report/2025/Report Lazada Beras sehat 2025.xlsx || etc/fixed data/lazada/report/2025/Report Lazada Merapi 2025.xlsx` |

## Source To Target Mapping

| No | Target Column | Source Column | Required | Transform / Rule | Notes |
|---:|---|---|---|---|---|
| 1 | `transaction_number` | `Transaction Number` | Review | Rename / normalize column name |  |
| 2 | `transaction_time` | `Transaction Time` | Review | Rename / normalize column name |  |
| 3 | `type` | `Type` | Review | Rename / normalize column name |  |
| 4 | `sub_type` | `Sub Type` | Review | Rename / normalize column name |  |
| 5 | `amount` | `Amount` | Review | Rename / normalize column name |  |
| 6 | `remarks` | `Remarks` | Review | Rename / normalize column name |  |
| 7 | `nama_toko` | Injected from filename / override | Review | Injected metadata | Bukan kolom asli file sumber. |
| 8 | `source_filename` | Injected from file basename | Review | Injected metadata | Bukan kolom asli file sumber. |

## Schema Drift Notes

- Audit menemukan 1 signature stabil untuk semua file Lazada Report.
- Semua report Lazada yang diaudit memiliki sheet `Balance Transactions`.

## Review Status

- Status: draft, perlu review bisnis untuk menentukan kolom required dan nullable.
- Setelah review, isi dokumen ini bisa diturunkan ke `config/schema_contracts.yml`.
