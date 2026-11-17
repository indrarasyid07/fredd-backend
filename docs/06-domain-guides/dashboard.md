# Dashboard

Data di balik halaman `/app` ([frontend ui/dashboard.md](https://gitlab.com/databiota-fredd/frontend/-/blob/development/docs/06-domain-guides/ui/dashboard.md)): ringkasan angka, peta, daftar laporan terbaru, ekspor, dan event realtime. Format respons: [api-conventions.md](../03-api/api-conventions.md#format-respons).

**Status: rancangan, belum dibangun** (16 November 2026). Tampilan frontend sudah dibangun dengan data contoh; daftar kebutuhan per elemen layar: [backend-needs.md](https://gitlab.com/databiota-fredd/frontend/-/blob/development/docs/06-domain-guides/ui/backend-needs.md). Semua endpoint di bawah **menunggu modul `workspaces`, `forms`, `extension_workers`, dan `reports`** (urutannya di [roadmap](../10-roadmap/roadmap.md)); dashboard hanya membaca, tidak menulis data lapangan.

## Prinsip

- **Server menghitung, klien menampilkan.** Semua angka, persen, dan insight dihitung di backend dari kueri atas `reports`; frontend hanya memformat dan menskalakan batang.
- **Satu zona waktu per workspace** (`workspaces.timezone`, bawaan `Asia/Jakarta`). "Hari ini", "kemarin", dan batas 7/30 hari memakai tengah malam zona itu; semua timestamp dikirim ISO 8601 dengan offset.
- **Terbatas pada workspace sesi.** Tiap kueri memfilter `workspace_id` dari keanggotaan sesi; id dari klien tidak pernah dipercaya tanpa dicek ke workspace itu.
- **Peran:** `reviewer` ke atas membaca dashboard. Ekspor butuh `form_editor` ke atas.
- **Kondisi** = kolom `reports.condition` (`healthy`, `attention`, `infected`, atau null). Kolom ini disalin dari isian struktur data yang ditandai berperan `condition` (lihat [Kondisi laporan](#kondisi-laporan)). Laporan tanpa kondisi dihitung terpisah sebagai `unknown`.

## Definisi angka

| Angka | Definisi |
|---|---|
| `reports_today` | `COUNT(*)` laporan dengan `received_at` ≥ awal hari ini (zona workspace) |
| `delta_pct` | `(hari ini − kemarin sampai jam yang sama) / kemarin × 100`, satu desimal; `null` bila kemarin 0 |
| `trend` | Jumlah laporan per hari untuk 7 hari terakhir (untuk garis tren kecil) |
| `active_workers` | Penyuluh `status = active` yang punya ≥ 1 laporan hari ini |
| `total_workers` | Penyuluh `status = active` (tidak termasuk "menunggu undangan") |
| `not_reported` | `total − active` |
| `monitored_land.area_ha` | Jumlah isian luas (ha) dari laporan **terbaru per titik lahan** dalam 30 hari terakhir. "Titik lahan" = lokasi yang dibulatkan ke grid 50 m per penyuluh dan struktur |
| `monitored_land.points` | Jumlah titik lahan unik pada rentang yang sama |
| `monitored_land.regencies` | Jumlah kabupaten/kota berbeda di antara titik itu |
| `completion.percent` | Laporan hari ini dengan semua isian wajib terisi ÷ laporan hari ini × 100, dibulatkan; `null` bila 0 laporan |
| `completion.blurry_rejected` | Foto hari ini yang ditolak karena `blur_score` di bawah ambang (`report_photos`) |
| `conditions` | Hitungan per kondisi untuk laporan pada **rentang yang dipilih** (`range`) |
| persen kondisi | Dibulatkan dengan metode sisa terbesar sehingga jumlahnya 100 |
| `top_infected_regions` | Maksimal 2 wilayah dengan `infected` terbanyak (pada rentang); kosong bila tidak ada |
| `top_regions` | 3 wilayah dengan laporan terbanyak pada rentang |

Rentang `range`: `today` (bawaan), `7d`, `30d`. KPI, grafik 7 hari, dan "terbaru" **tidak** mengikuti `range`; hanya `conditions`, `top_infected_regions`, `top_regions`, dan data peta.

## Endpoint

Semua di bawah `/api/v1`, `reviewer` ke atas kecuali disebut lain.

### `GET /dashboard/summary?range=today|7d|30d`

```json
{
  "as_of": "2026-11-13T10:30:00+07:00",
  "timezone": "Asia/Jakarta",
  "kpis": {
    "reports_today": { "value": 128, "yesterday_same_time": 114, "delta_pct": 12.3, "trend": [58, 41, 96, 91, 108, 117, 128] },
    "workers": { "active": 9, "total": 12, "not_reported": 3 },
    "monitored_land": { "area_ha": 1842.0, "points": 214, "regencies": 6 },
    "completion": { "percent": 79, "blurry_rejected": 5 }
  },
  "daily": [
    { "date": "2026-11-07", "count": 58 }, { "date": "2026-11-08", "count": 41 },
    { "date": "2026-11-09", "count": 96 }, { "date": "2026-11-10", "count": 91 },
    { "date": "2026-11-11", "count": 108 }, { "date": "2026-11-12", "count": 117 },
    { "date": "2026-11-13", "count": 128 }
  ],
  "conditions": {
    "range": "today", "total": 128,
    "items": [
      { "key": "healthy", "count": 74, "percent": 58 },
      { "key": "attention", "count": 35, "percent": 27 },
      { "key": "infected", "count": 19, "percent": 15 }
    ],
    "unknown": 0,
    "top_infected_regions": [{ "region_id": "…", "name": "Cianjur", "count": 7 }, { "region_id": "…", "name": "Purwakarta", "count": 5 }]
  },
  "top_regions": [{ "region_id": "…", "name": "Cianjur", "count": 24 }, { "region_id": "…", "name": "Garut", "count": 21 }, { "region_id": "…", "name": "Bandung Barat", "count": 19 }],
  "setup": { "form_created": true, "test_run_done": false, "channel_and_worker": false, "has_reports": true }
}
```

`daily` selalu 7 entri berurutan (hari tanpa laporan bernilai 0), hari ini terakhir. `setup` mengatur kondisi kosong dan checklist. Cache Redis 15 detik per `(workspace, range)`, dibuang saat ada `report.created`.

### `GET /reports/map?range=&form_id=&condition=`

```json
{
  "range": "today",
  "total": 128,
  "legend": { "healthy": 74, "attention": 35, "infected": 19, "unknown": 0 },
  "regions": [
    { "region_id": "…", "name": "Cianjur", "centroid": [107.14, -6.82], "count": 24,
      "by_condition": { "healthy": 12, "attention": 5, "infected": 7 },
      "color": "infected", "latest_report_id": "…" }
  ],
  "points": [{ "id": "…", "lat": -6.8214, "lng": 107.1402, "condition": "infected" }],
  "truncated": false
}
```

- **`color` wilayah**: `infected` bila porsi `infected` ≥ `alert_threshold` (bawaan 0,25) dari laporan wilayah itu, `attention` bila `infected + attention` ≥ ambang (dan bukan infected), selain itu `healthy`. Ambang di `workspaces.settings.map_alert_threshold`. Wilayah tanpa laporan tidak dikirim.
- **`points`** maksimal 2.000 per respons (terbaru dahulu); bila lebih, `truncated: true` dan klien menampilkan peringatan "Menampilkan 2.000 titik terbaru". Titik hanya berisi yang perlu digambar; detail diambil lewat `/reports/{id}`.
- `centroid` dari `reference_data` wilayah (GeoJSON), `[lng, lat]`.
- Batas dan nama wilayah untuk peta dasar: `GET /reference-data?type=region&geometry=true` (di-cache lama; berubah jarang).

### `GET /reports/{id}`

Rincian untuk panel detail:

```json
{
  "id": "…", "code": "LP-2411-0248", "form": { "id": "…", "name": "Survei Kondisi Tanaman" },
  "received_at": "2026-11-13T10:24:00+07:00",
  "worker": { "id": "…", "name": "Budi Santoso", "region": "Cianjur", "channel": "whatsapp" },
  "location": { "lat": -6.8214, "lng": 107.1402, "accuracy_m": 12, "village": "Sukamulya", "district": "Warungkondang" },
  "region": { "id": "…", "name": "Cianjur", "report_count": 24 },
  "fields": [
    { "label": "Nama petani", "type": "text", "value": "Pak Slamet" },
    { "label": "Komoditas", "type": "choice", "value": "Padi" },
    { "label": "Luas lahan", "type": "number", "value": 1.5, "unit": "ha" },
    { "label": "Kondisi tanaman", "type": "condition", "value": "infected" }
  ],
  "photos": [{ "id": "…", "url": "…", "thumb_url": "…", "expires_at": "…" }],
  "review": { "needs_review": true, "reason": "Luas lahan di atas 50 ha menunggu konfirmasi petugas senior." }
}
```

`fields` mengikuti urutan dan label **versi struktur data saat laporan dibuat** (`form_versions.definition`), jadi laporan lama tetap terbaca setelah struktur berubah. URL foto bertanda tangan, berlaku 15 menit. `region.report_count` mengikuti rentang aktif di dashboard bila `range` dikirim.

### `GET /reports?limit=5&sort=-received_at`

Daftar ringkas untuk "Laporan terbaru" (juga dipakai tabel laporan nanti): `id`, `code`, `worker` (id, nama), `region`, `commodity`, `condition`, `received_at`.

### `GET /reports/count`

`range=today|7d|30d|custom&from=&to=&form_id=&region_id=&condition=` → `{ "count": 128 }`. Dipakai ringkasan jendela unduh; `from`/`to` untuk `custom` (tanggal lokal, maksimal rentang 366 hari). Tanpa filter apa pun kecuali rentang, memakai indeks `(workspace_id, received_at)`.

### Ekspor

| Method | Path | Peran | Catatan |
|---|---|---|---|
| POST | `/reports/exports` | form_editor | Membuat pekerjaan; `202` + `{ id, status }`; `429` bila ≥ 3 ekspor berjalan untuk workspace |
| GET | `/reports/exports/{id}` | pembuat atau admin | `{ status, row_count, download_url?, expires_at?, error? }` |

```json
{
  "format": "pdf",
  "range": { "type": "7d" },
  "form_id": "…", "region_ids": [], "conditions": [],
  "include": { "map": true, "photos": true, "gps": true },
  "anonymize_farmers": false
}
```

- `format`: `pdf`, `xlsx`, `csv`. `range.type`: `today`, `7d`, `30d`, `custom` (dengan `from`, `to`). `region_ids`/`conditions` kosong = semua.
- **Pekerjaan arq**, bukan di request. Status: `queued` → `running` → `done` | `failed`. Klien memantau lewat SSE (`export.ready`) dengan cadangan polling 2 detik.
- Berkas ditulis ke penyimpanan objek (bucket privat), `download_url` bertanda tangan 15 menit, berkas dihapus setelah 7 hari. Ekspor di atas **50.000 laporan** ditulis sama tetapi tautannya juga dikirim lewat email dan notifikasi.
- **CSV** mengabaikan `include.map` dan `include.photos` (server menolak `true` untuk keduanya dengan `422`). **`anonymize_farmers`** mengganti nama petani dengan inisial di ketiga format.
- **PDF:** ringkasan, grafik, peta statis, dan tabel; **Excel:** satu lembar per struktur data, kolom mengikuti isiannya.
- Tiap permintaan ekspor dan tiap unduhan dicatat di `audit_logs` (siapa, filter, jumlah baris). Berkas tidak berisi nomor HP penyuluh.
- Ekspor terjadwal ("Jadwalkan berkala") ditunda ke Fase 6; belum ada endpoint.

## Event realtime (SSE)

`GET /events` (satu aliran per sesi dashboard, filter workspace di server). Format `event:` + `data:` JSON, `id:` berurutan, `retry: 3000`; klien yang tersambung ulang mengirim `Last-Event-ID` dan server memutar ulang hingga 100 event terakhir. Heartbeat komentar `:` tiap 20 detik.

| Event | Data | Dipicu |
|---|---|---|
| `report.created` | `{ id, code, region_id, condition, lat, lng, received_at }` | Laporan baru diterima |
| `report.updated` | `{ id, needs_review, status }` | Ditinjau atau dikonfirmasi |
| `worker.activity` | `{ worker_id, last_report_at }` | Penyuluh pertama kali melapor hari ini |
| `conversation.needs_help` | `{ conversation_id, count }` | Percakapan butuh bantuan; `count` = total sekarang |
| `export.ready` | `{ id, status }` | Ekspor selesai atau gagal |

Server menjaga event kecil (tanpa isi laporan, tanpa nama petani); klien memuat rincian lewat endpoint. Redis pub/sub per workspace menjadi perantara antar proses.

## Kondisi laporan

Dashboard menganggap "kondisi tanaman" sebagai satu isian struktur data yang ditandai **peran `condition`** (jenis isian pilihan dengan tiga nilai standar: Sehat, Perlu perhatian, Terserang). Saat laporan disimpan, nilainya disalin ke `reports.condition`. Struktur tanpa isian berperan `condition` menghasilkan laporan `unknown` ("Tanpa kondisi"). Penandaan peran ini **belum ada** di desain struktur data dan harus ditambahkan di [forms.md](https://gitlab.com/databiota-fredd/frontend/-/blob/development/docs/06-domain-guides/ui/forms.md) sebelum irisan 1 (pertanyaan terbuka frontend no. 5); isian luas lahan memakai peran `area` dengan cara yang sama (`reports.area_ha`).

## Model data tambahan

| Tabel / kolom | Isi | Catatan |
|---|---|---|
| `reports.area_ha` | numeric, null | Disalin dari isian berperan `area` |
| `reports.plot_key` | text | Hash grid 50 m + penyuluh + struktur; untuk "titik lahan unik" |
| `reports.complete` | boolean | Semua isian wajib terisi |
| `report_exports` | `workspace_id`, `requested_by`, `params` JSONB, `status`, `object_key`, `row_count`, `error`, `created_at`, `finished_at`, `expires_at` | Satu baris per ekspor |
| `workspaces.settings.map_alert_threshold` | float 0–1, bawaan 0,25 | Ambang warna pin wilayah |

Indeks: `reports (workspace_id, received_at DESC)`, `reports (workspace_id, region_id, received_at DESC)`, `reports (workspace_id, condition, received_at DESC)`, `reports (workspace_id, plot_key, received_at DESC)`. `reports.code` tetap format `LP-YYMM-NNNN` ([data-model](../04-database/data-model.md#detail-penting)).

## Performa dan cache

- `summary` dan `map` untuk satu workspace dihitung dalam satu transaksi baca dengan CTE; target p95 < 300 ms pada 100.000 laporan.
- Hasil di-cache di Redis (15 detik) dan dibuang saat event `report.created` bagi workspace itu, sehingga lonjakan laporan tidak menjalankan ulang kueri berat berkali-kali (maksimal sekali per 2 detik per workspace).
- `points` dibatasi 2.000; bila pemakaian nyata membutuhkan lebih, pindah ke tile vektor yang dihasilkan server (Fase lanjutan).

## Tes wajib

| # | Skenario | Harapan |
|---|---|---|
| 1 | Workspace A tidak melihat laporan workspace B di `summary`, `map`, `reports/{id}`, `count`, dan ekspor | Hanya data sendiri; id milik B → `404` |
| 2 | `daily` untuk hari tanpa laporan | 7 entri, nilai 0 |
| 3 | Batas hari di zona `Asia/Jakarta` (laporan 23.59 dan 00.01) | Jatuh ke hari yang benar |
| 4 | `delta_pct` saat kemarin 0 | `null` |
| 5 | Persen kondisi 3 nilai tidak bulat | Jumlah tepat 100 |
| 6 | Warna wilayah di sekitar ambang (24% vs 25%) | `attention`/`infected` sesuai aturan |
| 7 | Lebih dari 2.000 titik | `truncated: true`, 2.000 terbaru |
| 8 | Laporan lama setelah struktur berubah | `fields` memakai versi lama |
| 9 | Ekspor CSV dengan `include.photos = true` | `422` |
| 10 | Ekspor oleh `reviewer` | `403` |
| 11 | `anonymize_farmers` | Tidak ada nama petani lengkap di berkas |
| 12 | SSE: sambung ulang dengan `Last-Event-ID` | Event terlewat diputar ulang, tidak ada duplikat |

## Irisan pengerjaan

| Irisan | Isi | Syarat |
|---|---|---|
| 1 | `summary` + `reports` (daftar, detail) | Tabel `reports`, `report_photos`, `extension_workers`, `workspaces` |
| 2 | `reports/map` + data wilayah + tile peta | `reference_data` wilayah Jawa Barat (seeder `reference`) |
| 3 | `/events` SSE + Redis pub/sub | Pengirim laporan (ingest) |
| 4 | `count` + ekspor CSV/Excel | Pekerjaan arq, penyimpanan objek |
| 5 | Ekspor PDF (peta statis + grafik) | Irisan 4 |
| 6 | Seeder `demo`: workspace, 12 penyuluh, ~150 laporan 14 hari | Irisan 1 |

Irisan 6 dikerjakan bersama irisan 1 agar frontend punya data nyata untuk dikembangkan ([seed-data.md](../09-seeding/seed-data.md)).

## Pertanyaan terbuka

| # | Pertanyaan | Usulan |
|---|---|---|
| 1 | Penyimpanan objek (R2/S3/MinIO) untuk foto dan ekspor | Mengikuti keputusan penyimpanan foto laporan; satu bucket privat |
| 2 | Pustaka PDF (WeasyPrint, headless browser) dan peta statis | WeasyPrint untuk teks/tabel; peta statis dari tile milik sendiri |
| 3 | Penyedia tile peta | PMTiles milik sendiri (lihat frontend dashboard.md, F-037) |
| 4 | Ambang `blur_score` penolakan foto | Ditetapkan bersama modul foto laporan |
| 5 | Batas titik lahan 50 m | Tinjau setelah ada data nyata |
