# Shopee Income Order Processing Fee STTM

## Scope

- Target table: `stg_shopee_income_order_processing_fee`
- Marketplace: `shopee`
- Phase: `Income`
- Source mapping constant: `SHOPEE_INCOME_OPF_COLUMN_MAP`
- Schema guard constant: `VALID_SHOPEE_INCOME_OPF_COLS`

## File Reading Rules

- Sheet `Order Processing Fee`: header row index 0, data row index 1.
- Sheet `Seller Fee`: header row index 1, data row index 2, lalu data juga diarahkan ke tabel OPF.
- Pada format Seller Fee lama, kolom posisi B tanpa nama dipaksa menjadi `Lihat berdasarkan`.
- Jika tabel fisik memiliki `uploaded_at`, kolom tersebut diasumsikan diisi oleh database/default load process, bukan kolom source file.

## Source Signature Summary

| Sheet / Role | Signature | Count | Years | Months | Language | Column Count | Example |
|---|---:|---:|---|---|---|---:|---|
| Order Processing Fee | `57d7e36e2937` | 94 |  |  | - | 7 | `income/2025/Income.sudah dilepas.id.20250101_20251231 bandarorganik.xlsx | income/2025/Income.sudah dilepas.id.20250101_20251231 basecamporganik.xlsx` |
| Seller Fee | `e9441132e4d9` | 38 |  |  | - | 6 | `income/2025/Income.sudah dilepas.id.20250101_20251231 organicgroceries.xlsx | income/2026/april/4. Income Shopee beras porang porice 2026.xlsx` |
| Seller Fee | `3f942313f8f2` | 15 |  |  | - | 9 | `income/2026/juni/Income.sudah dilepas.id.20260601_20260630 bandarorganik.xlsx | income/2026/juni/Income.sudah dilepas.id.20260601_20260630 basecamporganik.xlsx` |
| Seller Fee | `64c82a224b64` | 8 |  |  | - | 10 | `income/2026/mei/Income.sudah dilepas.id.20260501_20260531 bandarorganik.xlsx | income/2026/mei/Income.sudah dilepas.id.20260501_20260531 basecamporganik.xlsx` |
| Seller Fee | `6601a9cc4c7a` | 7 |  |  | - | 8 | `income/2026/april/4. Income Shopee basecamp organik 2026.xlsx | income/2026/april/4. Income Shopee beras medan organik 2026.xlsx` |
| Seller Fee | `426c13235e47` | 6 |  |  | - | 9 | `income/2026/april/4. Income Shopee bandar organik 2026.xlsx | income/2026/april/4. Income Shopee beras sehat 2026.xlsx` |
| Seller Fee | `894d80f0ccdc` | 5 |  |  | - | 7 | `income/2026/april/4. Income Shopee mapan organik 2026.xlsx | income/2026/juni/Income.sudah dilepas.id.20260601_20260630 medanorganik.xlsx` |
| Seller Fee | `22efd7755e46` | 5 |  |  | - | 12 | `income/2026/mei/Income.sudah dilepas.id.20260501_20260531 berasdiabetes.xlsx | income/2026/mei/Income.sudah dilepas.id.20260501_20260531 berassehat.xlsx` |
| Seller Fee | `63be45372c4a` | 4 |  |  | - | 8 | `income/2023/Income.sudah dilepas.id.20230101_20231231 bandarorganik.xlsx | income/2023/Income.sudah dilepas.id.20230101_20231231 berassehat.xlsx` |
| Seller Fee | `8d6c6f11cd2c` | 4 |  |  | - | 10 | `income/2026/juni/Income.sudah dilepas.id.20260601_20260630 berasdiabetes.xlsx | income/2026/juni/Income.sudah dilepas.id.20260601_20260630 berassehat.xlsx` |
| Seller Fee | `f71f8954ff94` | 3 |  |  | - | 7 | `income/2023/Income.sudah dilepas.id.20230101_20231231 diabetashop.xlsx | income/2023/Income.sudah dilepas.id.20230101_20231231 lembahorganik.xlsx` |
| Seller Fee | `04c855562cec` | 3 |  |  | - | 7 | `income/2026/april/4. Income Shopee official 2026.xlsx | income/2026/juni/Income.sudah dilepas.id.20260601_20260630 official.xlsx` |
| Seller Fee | `14a1ef0d2a08` | 3 |  |  | - | 7 | `income/2026/april/4. Income Shopee organic groceries 2026.xlsx | income/2026/april/4. Income Shopee owellness 2026.xlsx` |
| Seller Fee | `b8b2e8c70f48` | 3 |  |  | - | 8 | `income/2026/juni/Income.sudah dilepas.id.20260601_20260630 bogorhealthystore.xlsx | income/2026/juni/Income.sudah dilepas.id.20260601_20260630 mapanorganik.xlsx` |
| Seller Fee | `07e61407ebe6` | 2 |  |  | - | 7 | `income/2023/Income.sudah dilepas.id.20230101_20231231 berasporangporice.xlsx | income/2023/Income.sudah dilepas.id.20230101_20231231 wellfarmdiyjateng.xlsx` |
| Seller Fee | `dd41d1222e66` | 2 |  |  | - | 8 | `income/2026/juni/Income.sudah dilepas.id.20260601_20260630 berasmedanorganik.xlsx | income/2026/juni/Income.sudah dilepas.id.20260601_20260630 trulyorganik.xlsx` |
| Seller Fee | `13fa14b91169` | 2 |  |  | - | 9 | `income/2026/mei/Income.sudah dilepas.id.20260501_20260531 organicgroceries.xlsx | income/2026/mei/Income.sudah dilepas.id.20260501_20260531 pusatberasberkualitas.xlsx` |
| Seller Fee | `0a1487d91094` | 1 |  |  | - | 9 | `income/2023/Income.sudah dilepas.id.20230101_20231231 official.xlsx` |
| Seller Fee | `329ad40e0f3c` | 1 |  |  | - | 9 | `income/2026/april/4. Income Shopee medan organik 2026.xlsx` |
| Seller Fee | `1edb47aa0e1f` | 1 |  |  | - | 8 | `income/2026/april/4. Income Shopee porang sachet 2026.xlsx` |
| Seller Fee | `8f68c2069e0d` | 1 |  |  | - | 9 | `income/2026/maret/Income.sudah dilepas.id.20260301_20260331 beras sehat.xlsx` |
| Seller Fee | `a3430696186b` | 1 |  |  | - | 8 | `income/2026/maret/Income.sudah dilepas.id.20260301_20260331 diy jateng.xlsx` |
| Seller Fee | `4714330fdf97` | 1 |  |  | - | 7 | `income/2026/maret/Income.sudah dilepas.id.20260301_20260331 organic.xlsx` |
| Seller Fee | `67b7aacc8589` | 1 |  |  | - | 9 | `income/2026/mei/Income.sudah dilepas.id.20260501_20260531 berasmedanorganik.xlsx` |
| Seller Fee | `814396ffea41` | 1 |  |  | - | 11 | `income/2026/mei/Income.sudah dilepas.id.20260501_20260531 medanorganik.xlsx` |
| Seller Fee | `738d554ef5e5` | 1 |  |  | - | 10 | `income/2026/mei/Income.sudah dilepas.id.20260501_20260531 porangsachetstore.xlsx` |

## Source To Target Mapping

| No | Target Column | Source Column | Required | Transform / Rule | Notes |
|---:|---|---|---|---|---|
| 1 | `no` | `No.` | Review | Rename / normalize column name |  |
| 2 | `lihat_berdasarkan` | `Lihat berdasarkan` | Review | Rename / normalize column name |  |
| 3 | `no_pesanan` | `No. Pesanan` | Review | Rename / normalize column name |  |
| 4 | `id_produk` | `ID Produk` | Review | Rename / normalize column name |  |
| 5 | `nama_produk` | `Nama Produk` | Review | Rename / normalize column name |  |
| 6 | `biaya_proses_pesanan` | `Biaya Proses Pesanan` | Review | Rename / normalize column name |  |
| 7 | `biaya_proses_pesanan_per_produk_prorata` | `Biaya Proses Pesanan per Produk (Prorata harga produk tiap pesanan)` | Review | Rename / normalize column name |  |
| 8 | `nama_toko` | Injected from filename / override | Review | Injected metadata | Bukan kolom asli file sumber. |
| 9 | `source_filename` | Injected from file basename | Review | Injected metadata | Bukan kolom asli file sumber. |

## Schema Drift Notes

- `Seller Fee` berperan ganda: dipakai untuk OPF dan Service Fee pada beberapa file lama.
- Kolom `Biaya Proses Pesanan per Produk (Prorata harga produk tiap pesanan)` hanya tersedia pada signature tertentu.

## Review Status

- Status: draft, perlu review bisnis untuk menentukan kolom required dan nullable.
- Setelah review, isi dokumen ini bisa diturunkan ke `config/schema_contracts.yml`.
