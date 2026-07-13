# Shopee Income Main STTM

## Scope

- Target table: `stg_shopee_income_main`
- Marketplace: `shopee`
- Phase: `Income`
- Source mapping constant: `SHOPEE_INCOME_MAIN_COLUMN_MAP`
- Schema guard constant: `VALID_SHOPEE_INCOME_MAIN_COLS`

## File Reading Rules

- File income Shopee dibaca multi-sheet dengan `openpyxl`.
- Sheet diproses jika nama sheet mengandung `income`.
- Header berada pada row index 5; data dimulai dari row index 6.
- Sheet `Summary` diabaikan.
- Jika tabel fisik memiliki `uploaded_at`, kolom tersebut diasumsikan diisi oleh database/default load process, bukan kolom source file.

## Source Signature Summary

| Sheet / Role | Signature | Count | Years | Months | Language | Column Count | Example |
|---|---:|---:|---|---|---|---:|---|
| Income | `9986f46a7f70` | 166 |  |  | - | 43 | `income/2023/Income.sudah dilepas.id.20230101_20231231 bandarorganik.xlsx | income/2023/Income.sudah dilepas.id.20230101_20231231 berasporangporice.xlsx` |
| Income | `2a7b1ac858ee` | 52 |  |  | - | 43 | `income/2026/juni/Income.sudah dilepas.id.20260601_20260630 bandarorganik.xlsx | income/2026/juni/Income.sudah dilepas.id.20260601_20260630 basecamporganik.xlsx` |
| Income | `4d986c2d761d` | 12 |  |  | - | 43 | `income/2023/Income.sudah dilepas.id.20230101_20231231 official.xlsx | income/2024/Income.sudah dilepas.id.20240101_20241231Official.xlsx` |
| Income | `021d858fe5ea` | 2 |  |  | - | 43 | `income/2026/juni/Income.sudah dilepas.id.20260601_20260630 official.xlsx | income/2026/mei/Income.sudah dilepas.id.20260501_20260531 official.xlsx` |
| Income | `d8f8a21d9c0d` | 1 |  |  | - | 43 | `income/2025/Income.sudah dilepas.id.20250101_20251231 medanorganik.xlsx` |

## Source To Target Mapping

| No | Target Column | Source Column | Required | Transform / Rule | Notes |
|---:|---|---|---|---|---|
| 1 | `no` | `No.` | Review | Rename / normalize column name |  |
| 2 | `no_pesanan` | `No. Pesanan` | Review | Rename / normalize column name |  |
| 3 | `no_pengajuan` | `No. Pengajuan` | Review | Rename / normalize column name |  |
| 4 | `username_pembeli` | `Username (Pembeli)` | Review | Rename / normalize column name |  |
| 5 | `waktu_pesanan_dibuat` | `Waktu Pesanan Dibuat` | Review | Rename / normalize column name |  |
| 6 | `metode_pembayaran_pembeli` | `Metode pembayaran pembeli` | Review | Rename / normalize column name |  |
| 7 | `tanggal_dana_dilepaskan` | `Tanggal Dana Dilepaskan` | Review | Rename / normalize column name |  |
| 8 | `harga_asli_produk` | `Harga Asli Produk` | Review | Rename / normalize column name |  |
| 9 | `total_diskon_produk` | `Total Diskon Produk` | Review | Rename / normalize column name |  |
| 10 | `jumlah_pengembalian_dana_ke_pembeli` | `Jumlah Pengembalian Dana ke Pembeli` | Review | Rename / normalize column name |  |
| 11 | `diskon_produk_dari_shopee` | `Diskon Produk dari Shopee` | Review | Rename / normalize column name |  |
| 12 | `voucher_disponsor_oleh_penjual` | `Voucher disponsor oleh Penjual` | Review | Rename / normalize column name |  |
| 13 | `voucher_co_fund_disponsor_oleh_penjual` | `Voucher co-fund disponsor oleh Penjual` | Review | Rename / normalize column name |  |
| 14 | `cashback_koin_disponsori_penjual` | `Cashback Koin disponsori Penjual` | Review | Rename / normalize column name |  |
| 15 | `cashback_koin_co_fund_disponsori_penjual` | `Cashback Koin Co-fund disponsori Penjual` | Review | Rename / normalize column name |  |
| 16 | `ongkir_dibayar_pembeli` | `Ongkir Dibayar Pembeli` | Review | Rename / normalize column name |  |
| 17 | `diskon_ongkir_ditanggung_jasa_kirim` | `Diskon Ongkir Ditanggung Jasa Kirim` | Review | Rename / normalize column name |  |
| 18 | `gratis_ongkir_dari_shopee` | `Gratis Ongkir dari Shopee` | Review | Rename / normalize column name |  |
| 19 | `ongkir_yang_diteruskan_oleh_shopee_ke_jasa_kirim` | `Ongkir yang Diteruskan oleh Shopee ke Jasa Kirim` | Review | Rename / normalize column name |  |
| 20 | `ongkos_kirim_pengembalian_barang` | `Ongkos Kirim Pengembalian Barang` | Review | Rename / normalize column name |  |
| 21 | `kembali_ke_biaya_pengiriman_pengirim` | `Kembali ke Biaya Pengiriman Pengirim` | Review | Rename / normalize column name |  |
| 22 | `pengembalian_biaya_kirim` | `Pengembalian Biaya Kirim` | Review | Rename / normalize column name |  |
| 23 | `biaya_komisi_ams` | `Biaya Komisi AMS` | Review | Rename / normalize column name |  |
| 24 | `biaya_administrasi_termasuk_ppn_11` | `Biaya Administrasi (termasuk PPN 11%)`<br>`Biaya Administrasi` | Review | Rename / normalize column name | Memiliki beberapa alias source. |
| 25 | `biaya_layanan` | `Biaya Layanan` | Review | Rename / normalize column name |  |
| 26 | `biaya_proses_pesanan` | `Biaya Proses Pesanan` | Review | Rename / normalize column name |  |
| 27 | `premi` | `Premi` | Review | Rename / normalize column name |  |
| 28 | `biaya_program_hemat_biaya_kirim` | `Biaya Program Hemat Biaya Kirim` | Review | Rename / normalize column name |  |
| 29 | `biaya_transaksi` | `Biaya Transaksi` | Review | Rename / normalize column name |  |
| 30 | `biaya_kampanye` | `Biaya Kampanye` | Review | Rename / normalize column name |  |
| 31 | `bea_masuk_ppn_pph` | `Bea Masuk, PPN & PPh` | Review | Rename / normalize column name |  |
| 32 | `biaya_isi_saldo_otomatis_dari_penghasilan` | `Biaya Isi Saldo Otomatis (dari Penghasilan)` | Review | Rename / normalize column name |  |
| 33 | `total_penghasilan` | `Total Penghasilan` | Review | Rename / normalize column name |  |
| 34 | `kode_voucher` | `Kode Voucher` | Review | Rename / normalize column name |  |
| 35 | `kompensasi` | `Kompensasi` | Review | Rename / normalize column name |  |
| 36 | `promo_gratis_ongkir_dari_penjual` | `Promo Gratis Ongkir dari Penjual` | Review | Rename / normalize column name |  |
| 37 | `jasa_kirim` | `Jasa Kirim` | Review | Rename / normalize column name |  |
| 38 | `nama_kurir` | `Nama Kurir` | Review | Rename / normalize column name |  |
| 39 | `pengembalian_dana_ke_pembeli` | `Pengembalian Dana ke Pembeli` | Review | Rename / normalize column name |  |
| 40 | `pro_rata_koin_yang_ditukarkan_untuk_pengembalian_barang` | `Pro-rata Koin yang Ditukarkan untuk Pengembalian Barang` | Review | Rename / normalize column name |  |
| 41 | `pro_rata_voucher_shopee_untuk_pengembalian_barang` | `Pro-rata Voucher Shopee untuk Pengembalian Barang` | Review | Rename / normalize column name |  |
| 42 | `pro_rated_bank_payment_channel_promotion_for_return_refund_item` | `Pro-rated Bank Payment Channel Promotion for return refund Items`<br>`Pro-rated Bank Payment Channel Promotion  for return refund Items` | Review | Rename / normalize column name | Memiliki beberapa alias source. |
| 43 | `pro_rated_shopee_payment_channel_promotion_for_return_refund_it` | `Pro-rated Shopee Payment Channel Promotion for return refund Items`<br>`Pro-rated Shopee Payment Channel Promotion  for return refund Items` | Review | Rename / normalize column name | Memiliki beberapa alias source. |
| 44 | `nama_toko` | Injected from filename / override | Review | Injected metadata | Bukan kolom asli file sumber. |
| 45 | `source_filename` | Injected from file basename | Review | Injected metadata | Bukan kolom asli file sumber. |

## Schema Drift Notes

- Audit menemukan beberapa signature Income karena variasi nama sheet `Income`, `Income - 1`, dst. dan variasi nama kolom.
- `Biaya Administrasi` dan `Biaya Administrasi (termasuk PPN 11%)` dinormalisasi ke kolom target yang sama.
- Ada variasi double-space pada kolom pro-rated payment promotion; sudah dibuat alias di mapping.

## Review Status

- Status: draft, perlu review bisnis untuk menentukan kolom required dan nullable.
- Setelah review, isi dokumen ini bisa diturunkan ke `config/schema_contracts.yml`.
