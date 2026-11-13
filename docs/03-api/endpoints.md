# Endpoints

Sketsa awal. Sumber kebenaran setelah implementasi adalah OpenAPI yang di-generate FastAPI. Semua respons JSON memakai [format standar](api-conventions.md#format-respons). Semua di bawah prefix `/api/v1` kecuali webhook.

Kolom "Peran" = peran minimum: `reviewer` < `form_editor` < `admin`.

## Auth & sesi

Rincian request, respons, dan error per endpoint: [auth.md](../06-domain-guides/auth.md). Kolom "Irisan" = urutan pengerjaan.

| Irisan | Method | Path | Peran | Keterangan |
|---|---|---|---|---|
| 1 | POST | `/auth/login` | publik | Email + kata sandi → `MeResponse` + cookie sesi; rate limit |
| 1 | POST | `/auth/logout` | opsional | Cabut sesi saat ini; selalu `200`, `data: null` |
| 1 | GET | `/auth/me` | login | `MeResponse`: user + keanggotaan workspace |
| 2 | POST | `/auth/register` | publik | Email, nama, instansi, kata sandi; kirim email verifikasi |
| 2 | POST | `/auth/verify-email` | publik | Token dari email; sukses langsung membuat sesi |
| 2 | POST | `/auth/verify-email/resend` | publik | Selalu `200` |
| 3 | POST | `/auth/password/forgot` | publik | Selalu `200` (tidak membocorkan email terdaftar) |
| 3 | POST | `/auth/password/reset` | publik | Token 30 menit + kata sandi baru; cabut semua sesi |
| 4 | GET | `/auth/google/login` | publik | Redirect ke Google (bukan JSON) |
| 4 | GET | `/auth/google/callback` | publik | Buat sesi, redirect ke `next` (bukan JSON) |
| – | GET | `/auth/sessions` | login | Sesi aktif milik user |
| – | DELETE | `/auth/sessions/{id}` | login | Keluarkan sesi lain |

## Workspace & anggota

| Method | Path | Peran |
|---|---|---|
| GET, PATCH | `/workspace` | reviewer / admin |
| GET | `/members` | admin |
| POST | `/members/invites` | admin |
| PATCH, DELETE | `/members/{id}` | admin |
| GET | `/audit-logs` | admin |
| POST | `/workspace/export` | admin |
| DELETE | `/workspace` | admin (konfirmasi nama workspace di body) |

## Struktur data (forms)

| Method | Path | Peran |
|---|---|---|
| GET, POST | `/forms` | reviewer / form_editor |
| GET, PATCH | `/forms/{id}` | reviewer / form_editor (hanya draf) |
| GET | `/forms/{id}/versions` | reviewer |
| POST | `/forms/{id}/validate` | form_editor (periksa otomatis) |
| POST | `/forms/{id}/test-runs` | form_editor (uji di akun sendiri) |
| POST | `/forms/{id}/pilot` | admin (body: daftar extension_worker_id) |
| POST | `/forms/{id}/publish` | admin |
| POST | `/forms/{id}/archive` | admin |
| GET | `/form-templates` | form_editor |

## Data rujukan

| Method | Path | Peran |
|---|---|---|
| GET, POST | `/reference-data?type=region\|commodity\|farmer_group\|unit` | reviewer / form_editor |
| PATCH, DELETE | `/reference-data/{id}` | form_editor |
| POST | `/reference-data/import` | form_editor (CSV) |

## Penyuluh (extension workers)

| Method | Path | Peran |
|---|---|---|
| GET, POST | `/extension-workers` | reviewer / admin |
| GET, PATCH, DELETE | `/extension-workers/{id}` | reviewer / admin |
| POST | `/extension-workers/invites` | admin |
| POST | `/extension-workers/invites/{id}/resend` | admin |

## Laporan (field reports)

| Method | Path | Peran |
|---|---|---|
| GET | `/reports` | reviewer (filter, cursor) |
| GET | `/reports/map` | reviewer (agregat per wilayah + titik) |
| GET | `/reports/photos` | reviewer (galeri) |
| GET | `/reports/{id}` | reviewer |
| PATCH | `/reports/{id}/review` | reviewer (tandai ditinjau) |
| PUT | `/reports/{id}/follow-up` | reviewer (status, assignee, prioritas, catatan) |
| GET | `/reports/export?format=xlsx` | form_editor |

## Aktivitas & percakapan

| Method | Path | Peran |
|---|---|---|
| GET | `/activity` | reviewer |
| GET | `/events` | reviewer (SSE) |
| GET | `/conversations?status=needs_help` | reviewer |
| GET | `/conversations/{id}` | reviewer |
| POST | `/conversations/{id}/takeover` | admin (409 bila sudah diambil admin lain) |
| POST | `/conversations/{id}/messages` | admin (hanya pemilik takeover) |
| POST | `/conversations/{id}/release` | admin (kembalikan ke Fredd) |
| POST | `/agent/pause`, `/agent/resume` | admin |

## Kanal

| Method | Path | Peran |
|---|---|---|
| GET | `/channels` | admin |
| POST | `/channels/telegram` | admin (body: bot token) |
| POST | `/channels/whatsapp` | admin (hasil Embedded Signup Meta) |
| POST | `/channels/{id}/test` | admin |
| DELETE | `/channels/{id}` | admin |
| GET | `/channels/{id}/logs` | admin |

## Analitik

| Method | Path | Peran |
|---|---|---|
| GET | `/analytics/summary` | reviewer |
| GET | `/analytics/trends` | reviewer |
| GET | `/analytics/extension-workers` | reviewer |

## Webhook (tanpa `/api/v1`)

| Method | Path | Keterangan |
|---|---|---|
| GET | `/webhooks/whatsapp` | Verifikasi `hub.challenge` dari Meta |
| POST | `/webhooks/whatsapp` | Pesan masuk + status; wajib `X-Hub-Signature-256` |
| POST | `/webhooks/telegram/{channel_id}` | Wajib header `X-Telegram-Bot-Api-Secret-Token` |

## Paket dan tagihan

Rincian: [billing-and-plans.md](../06-domain-guides/billing-and-plans.md#endpoint).

| Method | Path | Peran |
|---|---|---|
| GET | `/billing/plans?type=personal\|organization` | publik |
| GET | `/billing/subscription`, `/billing/usage` | login |
| POST | `/billing/checkout`, `/billing/cancel` | admin |
| POST | `/webhooks/payments/{provider}` (tanpa `/api/v1`) | penyedia pembayaran, tanda tangan wajib |

## Publik (untuk website)

| Method | Path | Keterangan |
|---|---|---|
| POST | `/public/leads` | Form kontak/demo dari landing page, dengan rate limit |
