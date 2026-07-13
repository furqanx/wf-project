# TikTok-Tokopedia Report STTM

## Scope

- Target table: `stg_tiktok_tokopedia_report`
- Marketplace: `tiktok_tokopedia`
- Phase: `Report`
- Source mapping constant: `TIKTOK_REPORT_COLUMN_MAP`
- Schema guard constant: `VALID_TIKTOK_REPORT_COLS`

## File Reading Rules

- File `.csv` dibaca dengan `pd.read_csv(..., dtype=str)`.
- File `.xlsx` dibaca dengan `openpyxl` pada active sheet.
- Header berada pada row index 0; data dimulai dari row index 1.
- `nama_toko` untuk report TikTok diekstrak dengan helper khusus agar bagian nama toko TikTok lebih diprioritaskan.
- Jika tabel fisik memiliki `uploaded_at`, kolom tersebut diasumsikan diisi oleh database/default load process, bukan kolom source file.

## Source Signature Summary

| Sheet / Role | Signature | Count | Years | Months | Language | Column Count | Example |
|---|---:|---:|---|---|---|---:|---|
| Withdrawal records | `12fdca26fa` | 61 | 2023|2024|2025|2026 | april|februari|januari|maret | english | 7 | `etc/fixed data/tiktok-tokopedia/report/2023/Report Tiktok Wellfarm ID 2023.xlsx || etc/fixed data/tiktok-tokopedia/report/2024/Report Tiktok Wellfarm ID.xlsx || etc/fixed data/tiktok-tokopedia/report/2025/Report Owellness 2025.xlsx || etc/fixed data/tiktok-tokopedia/report/2025/Report Tiktok Beras Organik ID 2025.xlsx || etc/fixed data/tiktok-tokopedia/report/2025/Report Tiktok Beras Sehat 2025.xlsx` |

## Source To Target Mapping

| No | Target Column | Source Column | Required | Transform / Rule | Notes |
|---:|---|---|---|---|---|
| 1 | `type` | `Type` | Review | Rename / normalize column name |  |
| 2 | `reference_id` | `Reference ID` | Review | Rename / normalize column name |  |
| 3 | `request_time` | `Request time` | Review | Rename / normalize column name |  |
| 4 | `amount` | `Amount` | Review | Rename / normalize column name |  |
| 5 | `status` | `Status` | Review | Rename / normalize column name |  |
| 6 | `success_time` | `Success time` | Review | Rename / normalize column name |  |
| 7 | `bank_account` | `Bank account` | Review | Rename / normalize column name |  |
| 8 | `nama_toko` | Injected from filename / override | Review | Injected metadata | Bukan kolom asli file sumber. |
| 9 | `source_filename` | Injected from file basename | Review | Injected metadata | Bukan kolom asli file sumber. |

## Indonesian Sheet Aliases

| Indonesian Sheet | English / Existing Role | Loader Role |
|---|---|---|
| `Riwayat penarikan` | `Withdrawal records` | Report / withdrawal records |

## Indonesian Source Column Aliases

| No | Target Column | Indonesian Source Column | English Equivalent | Status |
|---:|---|---|---|---|
| 1 | `type` | `Jenis transaksi` | `Type` | Ready alias |
| 2 | `reference_id` | `ID referensi` | `Reference ID` | Ready alias |
| 3 | `request_time` | `Waktu permintaan` | `Request time` | Ready alias |
| 4 | `amount` | `Total` | `Amount` | Ready alias |
| 5 | `status` | `Status` | `Status` | Ready alias |
| 6 | `success_time` | `Waktu keberhasilan` | `Success time` | Ready alias |
| 7 | `bank_account` | `Rekening bank` | `Bank account` | Ready alias |

## Schema Drift Notes

- Report resmi menggunakan signature withdrawal records berbahasa Inggris.
- Sheet withdrawal records juga muncul di file income 2026; perlu keputusan apakah ikut dimuat sebagai report atau tetap diabaikan pada flow income.
- Versi Indonesia memiliki kolom `Jenis transaksi`, `ID referensi`, `Waktu permintaan`, `Total`, `Status`, `Waktu keberhasilan`, `Rekening bank` dan butuh alias mapping.

## Review Status

- Status: draft, perlu review bisnis untuk menentukan kolom required dan nullable.
- Setelah review, isi dokumen ini bisa diturunkan ke `config/schema_contracts.yml`.
