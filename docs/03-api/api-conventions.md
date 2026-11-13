# API Conventions

Aturan untuk semua endpoint FastAPI. Daftar endpoint: [endpoints.md](endpoints.md). Penempatan kodenya: [system-architecture.md](../02-architecture/system-architecture.md#struktur-kode).

## Bahasa: Inggris

Endpoint, field JSON, nama tabel, dan kode memakai Bahasa Inggris. Teks untuk pengguna (`message` di respons, pesan chat) tetap Bahasa Indonesia.

Alasan:

1. Kode Python/TypeScript, library, dan HTTP semuanya berbahasa Inggris. Campuran (`get_laporan_by_penyuluh`) sulit dibaca dan tidak konsisten.
2. Klien TypeScript di-generate dari OpenAPI. Nama Inggris menghasilkan tipe yang konsisten dengan kode frontend lain.
3. Developer atau vendor baru tidak perlu menebak kata Indonesia.
4. Istilah domain tetap terjaga lewat [glosarium](../06-domain-guides/glossary.md), mis. `extension_worker` = penyuluh, `form` = struktur data.

Pengecualian: kode yang terlihat pengguna seperti `LP-2411-0248` dan pesan chat ke penyuluh.

## Bentuk URL

- Prefix `/api/v1`. Webhook di `/webhooks/...` (tanpa versi karena didaftarkan ke Meta, Telegram, dan penyedia pembayaran).
- Nama resource jamak, `kebab-case`: `/api/v1/extension-workers`, `/api/v1/reference-data`.
- Aksi yang bukan CRUD memakai sub-resource kata kerja: `POST /api/v1/forms/{id}/publish`.
- Endpoint milik pengguna yang sedang login memakai `me`: `GET /api/v1/auth/me`.
- ID di path berupa UUID. Kode tampilan (`LP-…`) hanya untuk pencarian: `GET /api/v1/reports?code=LP-2411-0248`.

## Field JSON

- `snake_case`, sama dengan Python. Frontend memakai tipe hasil generate apa adanya, tanpa konversi ke camelCase.
- Waktu dalam ISO 8601 UTC (`2026-11-13T03:24:00Z`). Frontend yang mengubah ke zona waktu workspace.
- Angka desimal (luas lahan) dikirim sebagai number, bukan string berformat ("1,5").
- Nilai kosong ditulis `null`, bukan string kosong. Key tetap ada.
- Uang dalam Rupiah sebagai integer (`49000`), tanpa desimal.

## Format respons

Semua respons JSON memakai **satu bentuk yang sama**. Key yang sama selalu ada, baik sukses maupun error; yang berbeda hanya isinya. Frontend cukup membaca satu pola untuk semua endpoint.

```json
{
  "success": true,
  "message": null,
  "data": {},
  "errors": [],
  "meta": {
    "request_id": "01JCX4K7P9Q2W3E5R6T8Y0U1I2",
    "timestamp": "2026-11-14T03:24:00Z",
    "pagination": null
  }
}
```

| Key | Tipe | Saat sukses | Saat error |
|---|---|---|---|
| `success` | boolean | `true` | `false` |
| `message` | string \| null | `null` atau kalimat singkat untuk ditampilkan (mis. "Berhasil masuk.") | Selalu ada; ringkasan error dalam Bahasa Indonesia, aman ditampilkan |
| `data` | object \| array \| null | Isi respons; `null` bila aksi tidak mengembalikan data (mis. logout) | Selalu `null` |
| `errors` | array | Selalu `[]` | Minimal 1 item (lihat di bawah) |
| `meta.request_id` | string | ID unik request | ID unik request |
| `meta.timestamp` | string (ISO 8601 UTC) | Waktu server | Waktu server |
| `meta.pagination` | object \| null | Terisi untuk daftar, selain itu `null` | Selalu `null` |

### Item `errors`

```json
{ "code": "invalid_email", "message": "Format email tidak valid.", "field": "email" }
```

| Key | Isi |
|---|---|
| `code` | Kode tetap, Bahasa Inggris, `snake_case`. Dipakai frontend untuk logika; **tidak boleh diubah** setelah dipakai |
| `message` | Kalimat Bahasa Indonesia untuk pengguna. Boleh diubah kapan saja |
| `field` | Path field yang salah memakai titik untuk isian bersarang (`email`, `fields.2.question`, `rules.0.then.require`); `null` bila error tidak terkait satu field |

Satu respons bisa berisi beberapa error (mis. dua field gagal validasi). `message` di level atas adalah ringkasannya.

### Contoh

**Sukses dengan data** (`200 OK`):

```json
{
  "success": true,
  "message": "Berhasil masuk.",
  "data": {
    "user": { "id": "0193a1b2-…", "email": "dina@contoh.id", "name": "Dina Admin" },
    "memberships": []
  },
  "errors": [],
  "meta": { "request_id": "01JCX4…", "timestamp": "2026-11-14T03:24:00Z", "pagination": null }
}
```

**Sukses tanpa data** (`200 OK`, mis. logout):

```json
{
  "success": true,
  "message": "Berhasil keluar.",
  "data": null,
  "errors": [],
  "meta": { "request_id": "01JCX4…", "timestamp": "2026-11-14T03:30:00Z", "pagination": null }
}
```

**Error tanpa field** (`401 Unauthorized`):

```json
{
  "success": false,
  "message": "Email atau kata sandi salah.",
  "data": null,
  "errors": [
    { "code": "invalid_credentials", "message": "Email atau kata sandi salah.", "field": null }
  ],
  "meta": { "request_id": "01JCX5…", "timestamp": "2026-11-14T03:24:05Z", "pagination": null }
}
```

**Error validasi per field** (`422 Unprocessable Content`):

```json
{
  "success": false,
  "message": "Periksa kembali isian Anda.",
  "data": null,
  "errors": [
    { "code": "invalid_email", "message": "Format email tidak valid.", "field": "email" },
    { "code": "required", "message": "Kata sandi wajib diisi.", "field": "password" }
  ],
  "meta": { "request_id": "01JCX6…", "timestamp": "2026-11-14T03:24:09Z", "pagination": null }
}
```

**Error server** (`500 Internal Server Error`), tanpa detail teknis:

```json
{
  "success": false,
  "message": "Terjadi kesalahan pada server. Coba lagi beberapa saat.",
  "data": null,
  "errors": [
    { "code": "internal_error", "message": "Terjadi kesalahan pada server. Coba lagi beberapa saat.", "field": null }
  ],
  "meta": { "request_id": "01JCX9…", "timestamp": "2026-11-14T03:26:00Z", "pagination": null }
}
```

### Aturan

1. **Status HTTP tetap benar** dan menjadi patokan utama. `success` hanya memudahkan pembacaan dan selalu sesuai status: `true` untuk 2xx, `false` untuk 4xx/5xx.
2. **Tidak memakai `204 No Content`.** Respons 204 tidak boleh punya body; aksi tanpa data mengembalikan `200` dengan `data: null`.
3. **Pesan untuk pengguna selalu dari `message`/`errors[].message`.** Frontend tidak menyusun pesan sendiri dari `code`, kecuali untuk perilaku khusus (mis. redirect saat `not_authenticated`).
4. **Error 500 tidak membocorkan detail** (stack trace, query, nama tabel). Detail lengkap hanya di log, dicari dengan `request_id`.
5. **`request_id`** dibuat per request (ULID). Bila klien atau Caddy mengirim header `X-Request-ID` yang valid, nilai itu dipakai. Nilai ini dikirim balik di header `X-Request-ID` dan dicatat di setiap baris log request tersebut.
6. **Respons selalu `Content-Type: application/json; charset=utf-8`**, termasuk 404 route yang tidak ada dan 405 method salah.

### Pengecualian format

| Endpoint | Format | Alasan |
|---|---|---|
| `/webhooks/*` | Sesuai permintaan pengirim (umumnya `200` body kosong atau teks pendek) | Meta, Telegram, dan penyedia pembayaran menentukan respons yang mereka harapkan |
| `/api/v1/events` | `text/event-stream` | Aliran Server-Sent Events, bukan JSON tunggal |
| Unduhan file (`/reports/export`, PDF) | File (`Content-Disposition: attachment`) | Body berupa file. **Bila gagal sebelum file dikirim, error tetap memakai format standar** |
| `/api/docs`, `/api/openapi.json` | Bawaan FastAPI | Dokumentasi, hanya di development |

## Pagination

Daftar memakai pagination berbasis cursor. `data` berisi array; info halaman ada di `meta.pagination`.

```
GET /api/v1/reports?form_id=…&region_id=…&channel=whatsapp&from=2026-11-01&to=2026-11-13&condition=infested&limit=50&cursor=eyJpZCI6…&sort=-received_at
```

```json
{
  "success": true,
  "message": null,
  "data": [ { "id": "…" }, { "id": "…" } ],
  "errors": [],
  "meta": {
    "request_id": "01JCX7…",
    "timestamp": "2026-11-14T03:25:00Z",
    "pagination": { "next_cursor": "eyJpZCI6…", "limit": 50, "has_more": true }
  }
}
```

| Parameter / field | Aturan |
|---|---|
| `limit` | Default 20, maksimal 100 |
| `cursor` | String buram dari `next_cursor` sebelumnya; jangan dibentuk di frontend. Cursor rusak → `400 invalid_cursor` |
| `sort` | Nama field; tanda minus = menurun (`-received_at`). Hanya field yang diizinkan per endpoint |
| `has_more` | `false` dan `next_cursor: null` di halaman terakhir |
| Total baris | Tidak dikirim di daftar (mahal dihitung); angka total disediakan endpoint ringkasan/KPI bila diperlukan |

## Katalog kode error

Kode umum di bawah dipakai semua domain. Kode khusus domain ditambahkan di dokumen domainnya (mis. [auth.md](../06-domain-guides/auth.md#kode-error)) dan dicatat di sini saat dipakai lebih dari satu domain.

| Code | HTTP | Kapan | `field` |
|---|---|---|---|
| `bad_request` | 400 | Body bukan JSON valid, parameter tidak bisa dibaca | `null` |
| `invalid_cursor` | 400 | Cursor pagination rusak atau kedaluwarsa | `cursor` |
| `validation_error` | 422 | Validasi gagal tanpa kode yang lebih spesifik | terisi |
| `required` | 422 | Field wajib kosong | terisi |
| `invalid_format` | 422 | Format salah (UUID, tanggal, enum) | terisi |
| `invalid_email` | 422 | Format email salah | terisi |
| `too_short` / `too_long` | 422 | Panjang teks di luar batas | terisi |
| `out_of_range` | 422 | Angka di luar rentang | terisi |
| `not_authenticated` | 401 | Belum login, cookie tidak ada, sesi habis atau dicabut | `null` |
| `forbidden` | 403 | Peran tidak cukup, atau data milik workspace lain | `null` |
| `csrf_rejected` | 403 | Header `Origin` bukan domain Fredd pada request yang mengubah data | `null` |
| `plan_limit_reached` | 403 | Kuota paket habis (lihat [billing-and-plans.md](../06-domain-guides/billing-and-plans.md#kuota-dan-fitur)) | `null` |
| `not_found` | 404 | Data atau route tidak ada | `null` |
| `method_not_allowed` | 405 | Method HTTP tidak didukung route | `null` |
| `conflict` | 409 | Bentrok status (mis. percakapan sudah diambil alih admin lain) | `null` |
| `too_many_attempts` | 429 | Rate limit; header `Retry-After` berisi detik tunggu | `null` |
| `internal_error` | 500 | Error tak terduga | `null` |
| `service_unavailable` | 503 | Database/Redis tidak tersedia | `null` |

Pemetaan validasi Pydantic ke kode di atas dilakukan di satu tempat (`app/api/errors.py`), termasuk pesan Bahasa Indonesia untuk kode umum. Kode khusus fitur didefinisikan sebagai kelas di `app/modules/<fitur>/errors.py`.

## Header

| Header | Arah | Isi |
|---|---|---|
| `X-Request-ID` | Respons (dan opsional request) | Sama dengan `meta.request_id` |
| `Retry-After` | Respons 429 | Detik sampai boleh mencoba lagi |
| `Set-Cookie: fredd_session=…` | Respons login | Lihat [auth.md](../06-domain-guides/auth.md#sesi-dan-cookie) |
| `Origin` | Request | Wajib cocok dengan domain Fredd untuk method selain GET/HEAD/OPTIONS |

## Dokumentasi OpenAPI

- `/api/docs` dan `/api/openapi.json` aktif hanya di development.
- Setiap endpoint mendeklarasikan `response_model=ApiResponse[NamaSchema]`, sehingga skema OpenAPI menampilkan bentuk `data` per endpoint.
- Respons error didokumentasikan lewat `responses={401: ..., 422: ...}` memakai `ApiErrorResponse`.
- Frontend generate tipe dari `openapi.json`; CI membandingkan file yang di-commit dengan hasil ekspor terbaru.
