**Planning Otomasi Accurate Dengan Prefect**

**1. Pisahkan Jenis Flow**
Buat minimal 2 flow:

```text
fetch_accurate_master_snapshot
fetch_accurate_incremental
```

Master snapshot:
- untuk `fetch_mode = full`
- jalan harian atau mingguan
- mengambil master data seperti item, customer, warehouse

Incremental:
- untuk `fetch_mode = incremental`
- jalan harian atau beberapa kali sehari
- mengambil sales, inventory, finance, purchase, dll.

**2. Flow Master Snapshot**
Alur:

```text
1. Ambil semua endpoint fetch_mode=full
2. Fetch seluruh page dengan sp.pageSize=100
3. Simpan raw file ke data/api/accurate/active/master_data/fetched_date=...
4. Insert metadata ke api_staging.raw_file_manifest
5. Insert daftar snapshot ke api_staging.master_snapshot_index
6. Nanti, trigger diff snapshot
```

Jadwal rekomendasi:

```text
setiap hari jam 02:00
atau mingguan kalau ingin hemat request
```

**3. Flow Incremental**
Alur:

```text
1. Tentukan date window otomatis
2. Ambil semua endpoint fetch_mode=incremental
3. Generate filter Accurate
4. Fetch page dengan sp.pageSize=100
5. Simpan raw file ke data/api/accurate/...
6. Insert metadata ke api_staging.raw_file_manifest
```

Date window awal:

```text
start_date = kemarin 00:00
end_date = hari ini 23:59
```

Atau lebih aman:

```text
start_date = sekarang - 3 hari
end_date = sekarang
```

Kenapa 3 hari? Untuk menangkap keterlambatan update/modify transaksi.

**4. Strategi Filter Incremental**
Perlu dibuat mapping per endpoint:

```text
endpoint -> date_filter_field
```

Contoh awal:

```text
sales_invoice      -> transDate
sales_receipt      -> transDate
journal_voucher    -> transDate
other_payment      -> transDate
item_adjustment    -> transDate
receive_item       -> transDate
```

Kalau ada endpoint yang tidak mendukung `transDate`, fallback:

```text
modifiedTime / createdTime / lastUpdate
```

Ini perlu diuji bertahap.

**5. Tambahkan CLI Helper**
Update `api_extract.py` agar bisa:

```bash
--source-system accurate
--fetch-mode incremental
--start-date 2026-07-10
--end-date 2026-07-13
```

Lalu script otomatis membuat payload:

```text
filter.transDate.op=BETWEEN
filter.transDate.val[0]=...
filter.transDate.val[1]=...
```

**6. Prefect Task Structure**
Di `scripts/flows/fetch_accurate_raw.py`:

```text
task: fetch_master_snapshot
task: fetch_incremental_group
task: validate_manifest_insert
flow: Accurate Master Snapshot
flow: Accurate Incremental
```

Flow tidak berisi logic besar. Flow hanya memanggil runner di `scripts/api/runners/accurate.py`.

**7. Deployment Prefect**
Deployment yang dibuat:

```text
Accurate_Master_Snapshot/daily-master-snapshot
Accurate_Incremental/hourly-incremental
```

Jadwal awal:

```text
master snapshot: 02:00 WIB setiap hari
incremental: 06:00, 12:00, 18:00 WIB
```

Atau kalau ingin hemat:

```text
incremental: 1x sehari jam 03:00 WIB
```

**8. Guardrail Wajib**
Sebelum scheduled run aktif:

- `manual` endpoint tidak boleh ikut flow otomatis
- `incremental` endpoint wajib punya date filter
- `max_pages` bisa dipasang saat awal testing
- request delay tetap aktif
- manifest tetap mencatat sukses/gagal

**9. Tahap Implementasi**
Urutan kerja:

```text
1. Tambah mapping date filter per endpoint
2. Tambah helper start_date/end_date di CLI
3. Tambah mode fetch-mode di CLI
4. Test incremental 1 endpoint
5. Test incremental 1 group
6. Implement flow Prefect
7. Deploy master snapshot
8. Deploy incremental
9. Monitoring hasil di Prefect UI dan raw_file_manifest
```

**Kesimpulan**
Prefect cocok. Kita tidak perlu Airflow. Logic tetap di `scripts/api/`, Prefect hanya menjadi scheduler dan orchestrator.






---
---
---










Untuk deployment di VPS nanti, jalankan dari `/opt/wf-project`:

```bash
prefect deploy scripts/flows/fetch_accurate_raw.py:accurate_master_snapshot_flow \
  --name daily-master-snapshot \
  --pool wellfarm-process-pool \
  --cron "0 2 * * *" \
  --timezone "Asia/Jakarta"
```

```bash
prefect deploy scripts/flows/fetch_accurate_raw.py:accurate_incremental_flow \
  --name hourly-incremental \
  --pool wellfarm-process-pool \
  --cron "0 6,12,18 * * *" \
  --timezone "Asia/Jakarta"
```

Monitoring database:

```sql
SELECT *
FROM api_staging.raw_file_manifest
WHERE source_system = 'accurate'
ORDER BY fetched_at DESC
LIMIT 50;
```

```sql
SELECT
    run_id,
    endpoint_group,
    COUNT(*) AS endpoint_count,
    COUNT(*) FILTER (WHERE success) AS success_count,
    COUNT(*) FILTER (WHERE NOT success) AS failed_count,
    SUM(record_count) AS total_records,
    MAX(fetched_at) AS latest_fetched_at
FROM api_staging.raw_file_manifest
WHERE source_system = 'accurate'
GROUP BY run_id, endpoint_group
ORDER BY latest_fetched_at DESC;
```

Catatan: saya belum menjalankan deployment Prefect sungguhan dari sini, karena itu sebaiknya dilakukan di VPS yang terhubung ke Prefect server dan punya `.env` production.















---
---
---








Planning pengerjaan API BigSeller:

1. **Tentukan endpoint final**
   - Pakai endpoint read-only saja:
     - order IDs
     - order details
     - in-warehouse order IDs
     - in-warehouse order details
     - settlement order IDs
     - settlement order details
   - Abaikan endpoint purchase/write.

2. **Tambahkan konfigurasi BigSeller**
   - Update `scripts/api/config.py`
   - Tambahkan:
     - `bigseller_raw_root`
     - `base_url`
     - `timeout_seconds`
     - `default_page_size`

3. **Buat client BigSeller**
   - Isi `scripts/api/clients/bigseller.py`
   - Handle:
     - `app_id`
     - `app_key`
     - `access_token`
     - `refresh_token`
     - HMAC-SHA256 signature
     - common headers
     - helper `post(endpoint, payload)`

4. **Buat registry endpoint BigSeller**
   - Buat `scripts/api/registry/bigseller.py`
   - Isi endpoint read-only:
     - `endpoint_group`
     - `endpoint`
     - `file_prefix`
     - `method`
     - `required_params`
     - `pagination_strategy`
     - `fetch_mode`

5. **Buat runner BigSeller**
   - Buat `scripts/api/runners/bigseller.py`
   - Alur:
     - ambil endpoint dari registry
     - build payload
     - call client
     - simpan raw response ke `/data/api/bigseller/...`
     - insert manifest ke `api_staging.raw_file_manifest`





6. **Update CLI**
   - Update `scripts/api_extract.py`
   - Tambahkan `--source-system bigseller`
   - Tambahkan default raw root BigSeller.

7. **Buat Prefect flow placeholder**
   - Buat `scripts/flows/fetch_bigseller_raw.py`
   - Belum perlu schedule sebelum manual test aman.

8. **Dry-run lokal**
   - Pastikan CLI bisa jalan tanpa hit API.
   - Validate registry dan compile.

9. **Manual API test setelah kredensial tersedia**
   - Test endpoint paling kecil dulu.
   - Simpan ke `/tmp` atau raw root dev.
   - Cek manifest.

10. **Scheduling Prefect**
   - Setelah aman:
     - order IDs: harian/beberapa kali sehari
     - order details: mengikuti hasil order IDs
     - settlement: harian.