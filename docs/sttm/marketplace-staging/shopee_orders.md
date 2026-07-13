# Shopee Orders STTM

## Scope

- Target table: `stg_shopee_orders`
- Marketplace: `shopee`
- Phase: `Order`
- Source mapping constant: `SHOPEE_ORDER_COLUMN_MAP`
- Schema guard constant: `VALID_SHOPEE_ORDER_COLS`

## File Reading Rules

- File `.xlsx` dibaca dengan `pd.read_excel(..., engine="openpyxl")` pada sheet pertama/default.
- Header berada pada baris pertama file.
- `nama_toko` diekstrak dari nama file; `source_filename` diisi dari nama file.
- Jika tabel fisik memiliki `uploaded_at`, kolom tersebut diasumsikan diisi oleh database/default load process, bukan kolom source file.

## Source Signature Summary

| Sheet / Role | Signature | Count | Years | Months | Language | Column Count | Example |
|---|---:|---:|---|---|---|---:|---|
| Order first sheet | `d3e7e576dc5d` | 543 |  |  | - | 49 | `order/2023/10. order bandar organik 2023.xlsx | order/2023/10. order beras porang porice 2023.xlsx` |
| Order first sheet | `2cbe30379667` | 78 |  |  | - | 49 | `order/2025/12. Order DIY Jateng 2025.xlsx | order/2025/12. Order Organic groceries 2025.xlsx` |
| Order first sheet | `83dd96b3e9c3` | 50 |  |  | - | 50 | `order/2022/1. order official 2022.xlsx | order/2022/10. order official 2022.xlsx` |
| Order first sheet | `7f85d58937bb` | 26 |  |  | - | 50 | `order/2026/juni/Order.all.20260601_20260630 bandarorganik.xlsx | order/2026/juni/Order.all.20260601_20260630 basecamporganik.xlsx` |
| Order first sheet | `a9c10d0e93fb` | 26 |  |  | - | 49 | `order/2026/mei/Order.all.20260501_20260531 bandarorganik.xlsx | order/2026/mei/Order.all.20260501_20260531 basecamporganik.xlsx` |
| Order first sheet | `bacce47b48c4` | 3 |  |  | - | 50 | `order/2025/12. Order official 2025.xlsx | order/2026/april/4. Order Shopee official 2026.xlsx` |
| Order first sheet | `245f4911a030` | 1 |  |  | - | 50 | `order/2025/1. order official 2025.xlsx` |
| Order first sheet | `4deaee17d66f` | 1 |  |  | - | 51 | `order/2026/juni/Order.all.20260601_20260630 official.xlsx` |
| Order first sheet | `cb6dcbb0d009` | 1 |  |  | - | 50 | `order/2026/mei/Order.all.20260501_20260531 official.xlsx` |

## Source To Target Mapping

| No | Target Column | Source Column | Required | Transform / Rule | Notes |
|---:|---|---|---|---|---|
| 1 | `no_pesanan` | `No. Pesanan` | Review | Rename / normalize column name |  |
| 2 | `status_pesanan` | `Status Pesanan` | Review | Rename / normalize column name |  |
| 3 | `alasan_pembatalan` | `Alasan Pembatalan` | Review | Rename / normalize column name |  |
| 4 | `status_pembatalan_pengembalian` | `Status Pembatalan/ Pengembalian` | Review | Rename / normalize column name |  |
| 5 | `no_resi` | `No. Resi` | Review | Rename / normalize column name |  |
| 6 | `opsi_pengiriman` | `Opsi Pengiriman` | Review | Rename / normalize column name |  |
| 7 | `antar_ke_counter_pickup` | `Antar ke counter/ pick-up` | Review | Rename / normalize column name |  |
| 8 | `pesanan_harus_dikirimkan_sebelum` | `Pesanan Harus Dikirimkan Sebelum (Menghindari keterlambatan)` | Review | Rename / normalize column name |  |
| 9 | `waktu_pengiriman_diatur` | `Waktu Pengiriman Diatur` | Review | Rename / normalize column name |  |
| 10 | `waktu_pesanan_dibuat` | `Waktu Pesanan Dibuat` | Review | Rename / normalize column name |  |
| 11 | `waktu_pembayaran_dilakukan` | `Waktu Pembayaran Dilakukan` | Review | Rename / normalize column name |  |
| 12 | `metode_pembayaran` | `Metode Pembayaran` | Review | Rename / normalize column name |  |
| 13 | `sku_induk` | `SKU Induk` | Review | Rename / normalize column name |  |
| 14 | `nama_produk` | `Nama Produk` | Review | Rename / normalize column name |  |
| 15 | `nomor_referensi_sku` | `Nomor Referensi SKU` | Review | Rename / normalize column name |  |
| 16 | `nama_variasi` | `Nama Variasi` | Review | Rename / normalize column name |  |
| 17 | `harga_awal` | `Harga Awal` | Review | Rename / normalize column name |  |
| 18 | `harga_setelah_diskon` | `Harga Setelah Diskon` | Review | Rename / normalize column name |  |
| 19 | `jumlah` | `Jumlah` | Review | Rename / normalize column name |  |
| 20 | `returned_quantity` | `Returned quantity` | Review | Rename / normalize column name |  |
| 21 | `total_harga_produk` | `Dibayar Pembeli`<br>`Total Harga Produk` | Review | Rename / normalize column name | Memiliki beberapa alias source. |
| 22 | `total_diskon` | `Total Diskon` | Review | Rename / normalize column name |  |
| 23 | `diskon_dari_penjual` | `Diskon Dari Penjual` | Review | Rename / normalize column name |  |
| 24 | `diskon_dari_shopee` | `Diskon Dari Shopee` | Review | Rename / normalize column name |  |
| 25 | `berat_produk` | `Berat Produk` | Review | Rename / normalize column name |  |
| 26 | `jumlah_produk_di_pesan` | `Jumlah Produk di Pesan` | Review | Rename / normalize column name |  |
| 27 | `total_berat` | `Total Berat` | Review | Rename / normalize column name |  |
| 28 | `nama_gudang` | `Nama Gudang` | Review | Rename / normalize column name |  |
| 29 | `voucher_ditanggung_penjual` | `Voucher Ditanggung Penjual` | Review | Rename / normalize column name |  |
| 30 | `cashback_koin` | `Cashback Koin` | Review | Rename / normalize column name |  |
| 31 | `voucher_ditanggung_shopee` | `Voucher Ditanggung Shopee` | Review | Rename / normalize column name |  |
| 32 | `paket_diskon` | `Paket Diskon` | Review | Rename / normalize column name |  |
| 33 | `paket_diskon_dari_shopee` | `Paket Diskon (Diskon dari Shopee)` | Review | Rename / normalize column name |  |
| 34 | `paket_diskon_dari_penjual` | `Paket Diskon (Diskon dari Penjual)` | Review | Rename / normalize column name |  |
| 35 | `potongan_koin_shopee` | `Potongan Koin Shopee` | Review | Rename / normalize column name |  |
| 36 | `diskon_kartu_kredit` | `Diskon Kartu Kredit` | Review | Rename / normalize column name |  |
| 37 | `ongkos_kirim_dibayar_oleh_pembeli` | `Ongkos Kirim Dibayar oleh Pembeli` | Review | Rename / normalize column name |  |
| 38 | `estimasi_potongan_biaya_pengiriman` | `Estimasi Potongan Biaya Pengiriman` | Review | Rename / normalize column name |  |
| 39 | `ongkos_kirim_pengembalian_barang` | `Ongkos Kirim Pengembalian Barang` | Review | Rename / normalize column name |  |
| 40 | `total_pembayaran` | `Total Pembayaran` | Review | Rename / normalize column name |  |
| 41 | `perkiraan_ongkos_kirim` | `Perkiraan Ongkos Kirim` | Review | Rename / normalize column name |  |
| 42 | `catatan_dari_pembeli` | `Catatan dari Pembeli` | Review | Rename / normalize column name |  |
| 43 | `catatan` | `Catatan` | Review | Rename / normalize column name |  |
| 44 | `username_pembeli` | `Username (Pembeli)` | Review | Rename / normalize column name |  |
| 45 | `nama_penerima` | `Nama Penerima` | Review | Rename / normalize column name |  |
| 46 | `no_telepon` | `No. Telepon` | Review | Rename / normalize column name |  |
| 47 | `alamat_pengiriman` | `Alamat Pengiriman` | Review | Rename / normalize column name |  |
| 48 | `kota_kabupaten` | `Kota/Kabupaten` | Review | Rename / normalize column name |  |
| 49 | `provinsi` | `Provinsi` | Review | Rename / normalize column name |  |
| 50 | `waktu_pesanan_selesai` | `Waktu Pesanan Selesai` | Review | Rename / normalize column name |  |
| 51 | `nama_toko` | Injected from filename / override | Review | Injected metadata | Bukan kolom asli file sumber. |
| 52 | `source_filename` | Injected from file basename | Review | Injected metadata | Bukan kolom asli file sumber. |

## Schema Drift Notes

- Jumlah sheet order Shopee konsisten satu sheet utama menurut audit.
- Mapping memiliki alias `Dibayar Pembeli` dan `Total Harga Produk` yang sama-sama masuk ke `total_harga_produk`.

## Review Status

- Status: draft, perlu review bisnis untuk menentukan kolom required dan nullable.
- Setelah review, isi dokumen ini bisa diturunkan ke `config/schema_contracts.yml`.
