# Shopee Income Service Fee STTM

## Scope

- Target table: `stg_shopee_income_service_fee`
- Marketplace: `shopee`
- Phase: `Income`
- Source mapping constant: `SHOPEE_INCOME_SF_COLUMN_MAP`
- Schema guard constant: `VALID_SHOPEE_INCOME_SF_COLS`

## File Reading Rules

- Sheet `Service Fee`: header row index 1, data row index 2.
- Sheet `Seller Fee`: header row index 1, data row index 2, lalu data juga diarahkan ke tabel Service Fee.
- Kolom biaya campaign tahunan dinormalisasi ke kolom target campaign bulanan yang sama.
- Jika tabel fisik memiliki `uploaded_at`, kolom tersebut diasumsikan diisi oleh database/default load process, bukan kolom source file.

## Source Signature Summary

| Sheet / Role | Signature | Count | Years | Months | Language | Column Count | Example |
|---|---:|---:|---|---|---|---:|---|
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
| Service Fee | `887ed90326bb` | 32 |  |  | - | 4 | `income/2025/Income.sudah dilepas.id.20250101_20251231 berasmedanorganik.xlsx | income/2025/Income.sudah dilepas.id.20250101_20251231 berasporangporice.xlsx` |
| Service Fee | `2219285dffc1` | 10 |  |  | - | 5 | `income/2026/februari/Income.sudah dilepas.id.20260201_20260228 basecamp organik.xlsx | income/2026/februari/Income.sudah dilepas.id.20260201_20260228 beras medan organik.xlsx` |
| Service Fee | `538e45d1ba39` | 8 |  |  | - | 3 | `income/2025/Income.sudah dilepas.id.20250101_20251231 mapanorganik.xlsx | income/2025/Income.sudah dilepas.id.20250101_20251231 solusiberassehat.xlsx` |
| Service Fee | `a9f21504448a` | 7 |  |  | - | 4 | `income/2026/februari/Income.sudah dilepas.id.20260201_20260228 (6) solo organik.xlsx | income/2026/maret/Income.sudah dilepas.id.20260301_20260331 basecamp.xlsx` |
| Service Fee | `0b7612c3b468` | 6 |  |  | - | 3 | `income/2024/Income.sudah dilepas.id.20240101_20241231 berasmedanorganik.xlsx | income/2024/Income.sudah dilepas.id.20240101_20241231 zonapangan.xlsx` |
| Service Fee | `29347d29cd48` | 6 |  |  | - | 5 | `income/2025/Income.sudah dilepas.id.20250101_20251231 bandarorganik.xlsx | income/2025/Income.sudah dilepas.id.20250101_20251231 bogorhealthy.xlsx` |
| Service Fee | `af778016dc31` | 5 |  |  | - | 5 | `income/2026/maret/Income.sudah dilepas.id.20260301_20260331 bandar.xlsx | income/2026/maret/Income.sudah dilepas.id.20260301_20260331 bromo.xlsx` |
| Service Fee | `e73a3a80f704` | 4 |  |  | - | 7 | `income/2025/Income.sudah dilepas.id.20250101_20251231 official.xlsx | income/2025/Income.sudah dilepas.id.20250101_20251231 official.xlsx` |
| Service Fee | `efef024e6808` | 3 |  |  | - | 5 | `income/2024/Income.sudah dilepas.id.20240101_20241231Official.xlsx | income/2024/Income.sudah dilepas.id.20240101_20241231Official.xlsx` |
| Service Fee | `e8b15c9c6896` | 2 |  |  | - | 6 | `income/2024/Income.sudah dilepas.id.20240101_20241231 basecamporganik.xlsx | income/2024/Income.sudah dilepas.id.20240101_20241231 sumberorganikshop.xlsx` |
| Service Fee | `d93973675ec8` | 2 |  |  | - | 11 | `income/2024/Income.sudah dilepas.id.20240101_20241231 beras sehat.xlsx | income/2024/Income.sudah dilepas.id.20240101_20241231 bromoorganik.xlsx` |
| Service Fee | `ea2b5afce179` | 2 |  |  | - | 8 | `income/2024/Income.sudah dilepas.id.20240101_20241231 diabetashop.xlsx | income/2024/Income.sudah dilepas.id.20240101_20241231 merbabuorganik.xlsx` |
| Service Fee | `5a08c3df50be` | 2 |  |  | - | 9 | `income/2024/Income.sudah dilepas.id.20240101_20241231 lembahorganik.xlsx | income/2024/Income.sudah dilepas.id.20240101_20241231 trulyorganik.xlsx` |
| Service Fee | `3dcaa4e6c381` | 2 |  |  | - | 3 | `income/2026/februari/Income.sudah dilepas.id.20260201_20260228 (1) Official.xlsx | income/2026/maret/Income.sudah dilepas.id.20260301_20260331 official.xlsx` |
| Service Fee | `2a8720395b24` | 2 |  |  | - | 6 | `income/2026/februari/Income.sudah dilepas.id.20260201_20260228 bandar organik.xlsx | income/2026/februari/Income.sudah dilepas.id.20260201_20260228 merapi organik.xlsx` |
| Service Fee | `dd7acc20bfd1` | 1 |  |  | - | 10 | `income/2024/Income.sudah dilepas.id.20240101_20241231 bandarorganik.xlsx` |
| Service Fee | `2bf8953dffca` | 1 |  |  | - | 10 | `income/2024/Income.sudah dilepas.id.20240101_20241231 berasporangporice.xlsx` |
| Service Fee | `17e385d43984` | 1 |  |  | - | 9 | `income/2024/Income.sudah dilepas.id.20240101_20241231 bogorhealthystore.xlsx` |
| Service Fee | `5db6b974e6b1` | 1 |  |  | - | 7 | `income/2024/Income.sudah dilepas.id.20240101_20241231 diethealthy.xlsx` |
| Service Fee | `f66e09cd0eb6` | 1 |  |  | - | 4 | `income/2024/Income.sudah dilepas.id.20240101_20241231 medanorganik.xlsx` |
| Service Fee | `00e74c677042` | 1 |  |  | - | 12 | `income/2024/Income.sudah dilepas.id.20240101_20241231 merapiorganik.xlsx` |
| Service Fee | `02c5815710d5` | 1 |  |  | - | 5 | `income/2024/Income.sudah dilepas.id.20240101_20241231 owellness.xlsx` |
| Service Fee | `b1a0779feb40` | 1 |  |  | - | 5 | `income/2024/Income.sudah dilepas.id.20240101_20241231 soloorganik.xlsx` |
| Service Fee | `e67d936e2c8a` | 1 |  |  | - | 7 | `income/2024/Income.sudah dilepas.id.20240101_20241231 wellfarmdiyjateng.xlsx` |
| Service Fee | `a15db516fe52` | 1 |  |  | - | 5 | `income/2025/Income.sudah dilepas.id.20250101_20251231 basecamporganik.xlsx` |
| Service Fee | `e779ca40fb86` | 1 |  |  | - | 4 | `income/2026/februari/Income.sudah dilepas.id.20260201_20260228 (3) owellness.xlsx` |
| Service Fee | `b6d0f74e5216` | 1 |  |  | - | 4 | `income/2026/januari/Income.sudah dilepas.id.20260101_20260131 official.xlsx` |
| Service Fee | `b836d353607d` | 1 |  |  | - | 3 | `income/2026/maret/Income.sudah dilepas.id.20260301_20260331 owellness.xlsx` |

## Source To Target Mapping

| No | Target Column | Source Column | Required | Transform / Rule | Notes |
|---:|---|---|---|---|---|
| 1 | `no` | `No.` | Review | Rename / normalize column name |  |
| 2 | `no_pesanan` | `No. Pesanan` | Review | Rename / normalize column name |  |
| 3 | `biaya_layanan_cashback_xtra` | `Biaya Layanan Cashback XTRA`<br>`Biaya Layanan Cashback Xtra` | Review | Rename / normalize column name | Memiliki beberapa alias source. |
| 4 | `biaya_layanan_cashbackxtra` | `Biaya Layanan CashbackXTRA` | Review | Rename / normalize column name |  |
| 5 | `biaya_layanan_gratis_ongkir_xtra` | `Biaya Layanan Gratis Ongkir XTRA` | Review | Rename / normalize column name |  |
| 6 | `biaya_layanan_gratis_ongkir_xtra_2` | `Biaya Layanan Gratis Ongkir Xtra` | Review | Rename / normalize column name |  |
| 7 | `biaya_layanan_promo_xtra` | `Biaya Layanan Promo XTRA` | Review | Rename / normalize column name |  |
| 8 | `biaya_pembayaran` | `Biaya Pembayaran` | Review | Rename / normalize column name |  |
| 9 | `biaya_program_shopee_live_xtra` | `Biaya Program Shopee Live Xtra` | Review | Rename / normalize column name |  |
| 10 | `biaya_campaign_1_1` | `Biaya Campaign 1.1 2024`<br>`Biaya Campaign 1.1 2025` | Review | Rename / normalize column name | Memiliki beberapa alias source. |
| 11 | `biaya_campaign_2_2` | `Biaya Campaign 2.2 2024`<br>`Biaya Campaign 2.2 2025` | Review | Rename / normalize column name | Memiliki beberapa alias source. |
| 12 | `biaya_campaign_3_3` | `Biaya Campaign 3.3 2024`<br>`Biaya Campaign 3.3 2025` | Review | Rename / normalize column name | Memiliki beberapa alias source. |
| 13 | `biaya_campaign_4_4` | `Biaya Campaign 4.4 2024`<br>`Biaya Campaign 4.4 2025` | Review | Rename / normalize column name | Memiliki beberapa alias source. |
| 14 | `biaya_campaign_5_5` | `Biaya Campaign 5.5 2024`<br>`Biaya Campaign 5.5 2025` | Review | Rename / normalize column name | Memiliki beberapa alias source. |
| 15 | `biaya_campaign_6_6` | `Biaya Campaign 6.6 2024`<br>`Biaya Campaign 6.6 2025` | Review | Rename / normalize column name | Memiliki beberapa alias source. |
| 16 | `biaya_campaign_7_7` | `Biaya Campaign 7.7 2024`<br>`Biaya Campaign 7.7 2025` | Review | Rename / normalize column name | Memiliki beberapa alias source. |
| 17 | `biaya_campaign_8_8` | `Biaya Campaign 8.8 2024`<br>`Biaya Campaign 8.8 2025` | Review | Rename / normalize column name | Memiliki beberapa alias source. |
| 18 | `biaya_campaign_9_9` | `Biaya Campaign 9.9 2024`<br>`Biaya Campaign 9.9 2025` | Review | Rename / normalize column name | Memiliki beberapa alias source. |
| 19 | `biaya_campaign_10_10` | `Biaya Campaign 10.10 2024`<br>`Biaya Campaign 10.10 2025` | Review | Rename / normalize column name | Memiliki beberapa alias source. |
| 20 | `biaya_campaign_11_11` | `Biaya Campaign 11.11 2024`<br>`Biaya Campaign 11.11 2025` | Review | Rename / normalize column name | Memiliki beberapa alias source. |
| 21 | `biaya_campaign_12_12` | `Biaya Campaign 12.12 2024`<br>`Biaya Campaign 12.12 2025` | Review | Rename / normalize column name | Memiliki beberapa alias source. |
| 22 | `biaya_proses_pesanan` | `Biaya Proses Pesanan` | Review | Rename / normalize column name |  |
| 23 | `nama_toko` | Injected from filename / override | Review | Injected metadata | Bukan kolom asli file sumber. |
| 24 | `source_filename` | Injected from file basename | Review | Injected metadata | Bukan kolom asli file sumber. |

## Schema Drift Notes

- Audit menemukan banyak variasi kolom pada `Seller Fee`/`Service Fee`, terutama biaya layanan gratis ongkir, promo XTRA, payment fee, dan campaign.
- `Biaya Layanan Cashback XTRA`, `CashbackXTRA`, dan `Cashback Xtra` diperlakukan sebagai alias.

## Review Status

- Status: draft, perlu review bisnis untuk menentukan kolom required dan nullable.
- Setelah review, isi dokumen ini bisa diturunkan ke `config/schema_contracts.yml`.
