# Marketplace Staging Schema Drift Register

Register ini merangkum perubahan sheet/kolom yang terdeteksi dari audit `etc/fixed data/` dan implikasinya ke loader/staging.

| No | Dataset | Drift Type | Evidence | Impact | Suggested Handling | Status |
|---:|---|---|---|---|---|---|
| 1 | Lazada Orders | Added column | `platformDiscountTotal` muncul pada signature 2026 April/Mei/Juni. | Aman jika mapping aktif; berisiko terbuang jika schema lama. | Pertahankan mapping ke `platform_discount_total` dan allowed column. | Handled in loader |
| 2 | Shopee Report | Sheet name change | 1 file report memakai sheet `Sheet1`, bukan `Transaction Report`. | Loader saat ini mengabaikan file tersebut. | Tambahkan fallback deteksi report-like header pada row 3 atau rename sheet manual. | Needs decision |
| 3 | Shopee Income Main | Column label variants | `Biaya Administrasi` vs `Biaya Administrasi (termasuk PPN 11%)`; variasi double-space pada pro-rated columns. | Bisa membuat kolom tidak termapping jika alias tidak lengkap. | Pertahankan alias mapping dan pindahkan ke schema contract aliases. | Handled in loader |
| 4 | Shopee Income Service Fee | Many optional fee columns | Seller Fee/Service Fee memiliki banyak variasi kolom gratis ongkir, promo, payment fee, campaign. | Tidak semua kolom muncul di semua file. | Tandai sebagai optional; required cukup `no`/`no_pesanan` jika disepakati. | Needs review |
| 5 | Shopee Income OPF | Mixed sheet role | `Seller Fee` lama diproses ke OPF dan Service Fee sekaligus. | Satu sheet menghasilkan dua staging target. | Dokumentasikan routing dan pastikan dedup/key jelas saat transform. | Documented |
| 6 | TikTok-Tokopedia Income | Language change | Mei/Juni 2026 memakai kolom Indonesia pada sheet order details. | Mapping Inggris saat ini tidak cukup; data bisa kehilangan kolom. | Tambahkan alias Indonesia ke `TIKTOK_INCOME_COLUMN_MAP`/schema contract. | Needs implementation |
| 7 | TikTok-Tokopedia Income | Sheet name/content addition | Sheet `Withdrawal records`/Indonesia muncul di file income. | Report-like data berada di file income, bukan hanya folder report. | Putuskan apakah diroute ke `stg_tiktok_tokopedia_report` atau tetap diabaikan. | Needs decision |
| 8 | TikTok-Tokopedia Report | Language change | Withdrawal records Indonesia: `Jenis transaksi`, `ID referensi`, `Waktu permintaan`, `Total`, dll. | Report Indonesia tidak termapping oleh map Inggris. | Tambahkan alias Indonesia ke report mapping. | Needs implementation |
| 9 | TikTok-Tokopedia Income | Temporary lock files | File `.~...xlsx` terdeteksi pada folder income. | File tidak valid/empty dan menghasilkan error audit. | Abaikan file berawalan `.~` pada proses scanning/upload. | Needs implementation |
