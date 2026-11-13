# API Conventions

## Bahasa: Inggris

Endpoint, field JSON, nama tabel, dan kode memakai Bahasa Inggris. Teks untuk pengguna (pesan error yang ditampilkan, pesan chat) tetap Bahasa Indonesia.

Alasan:

1. Kode Python/TypeScript, library, dan HTTP semuanya berbahasa Inggris. Campuran (`get_laporan_by_penyuluh`) sulit dibaca dan tidak konsisten.
2. Klien TypeScript di-generate dari OpenAPI. Nama Inggris menghasilkan tipe yang konsisten dengan kode frontend lain.
3. Developer atau vendor baru tidak perlu menebak kata Indonesia.
4. Istilah domain tetap terjaga lewat [glosarium](../06-domain-guides/glossary.md), mis. `extension_worker` = penyuluh, `form` = struktur data.

Pengecualian: kode yang terlihat pengguna seperti `LP-2411-0248` dan pesan chat ke penyuluh.

## Bentuk URL

- Prefix `/api/v1`. Webhook di `/webhooks/...` (tanpa versi karena didaftarkan ke Meta/Telegram).
- Nama resource jamak, `kebab-case`: `/api/v1/extension-workers`, `/api/v1/reference-data`.
- Aksi yang bukan CRUD memakai sub-resource kata kerja: `POST /api/v1/forms/{id}/publish`.
- ID di path berupa UUID. Kode tampilan (`LP-…`) hanya untuk pencarian: `GET /api/v1/reports?code=LP-2411-0248`.

## Field JSON

- `snake_case`, sama dengan Python. Frontend memakai tipe hasil generate apa adanya, tanpa konversi ke camelCase.
- Waktu dalam ISO 8601 UTC (`2026-11-13T03:24:00Z`). Frontend yang mengubah ke zona waktu workspace.
- Angka desimal (luas lahan) dikirim sebagai number, bukan string berformat ("1,5").

## Daftar dan filter

```
GET /api/v1/reports?form_id=…&region_id=…&channel=whatsapp&from=2026-11-01&to=2026-11-13&condition=infested&limit=50&cursor=…
```

- Pagination berbasis cursor: respons `{ "items": [...], "next_cursor": "…" | null }`.
- Sortir: `sort=-received_at` (tanda minus = menurun).

## Error

Format tunggal untuk semua error:

```json
{ "error": { "code": "form_not_found", "message": "Struktur data tidak ditemukan.", "details": {} } }
```

- `code`: Inggris, `snake_case`, stabil, dipakai frontend untuk logika.
- `message`: Bahasa Indonesia, aman ditampilkan ke pengguna.
- Status HTTP: 400 validasi bisnis, 401 belum login, 403 peran tidak cukup, 404, 409 konflik (mis. percakapan sudah diambil alih admin lain), 422 validasi skema dari FastAPI, 429 rate limit.

## Dokumentasi

`/api/docs` (OpenAPI) aktif hanya di lingkungan development. Frontend generate tipe dari `openapi.json` yang diekspor saat build.

Daftar endpoint: [endpoints.md](endpoints.md).
