# Endpoints

Sketsa awal. Sumber kebenaran setelah implementasi adalah OpenAPI yang di-generate FastAPI. Semua respons JSON memakai [format standar](api-conventions.md#format-respons). Semua di bawah prefix `/api/v1` kecuali webhook.

Kolom "Peran" = peran minimum: `reviewer` < `form_editor` < `admin`.

## Auth & sesi

Rincian request, respons, dan error per endpoint: [auth.md](../06-domain-guides/auth.md). Kolom "Irisan" = urutan pengerjaan; irisan 1-4 sudah dibangun (16 November 2026), `/auth/sessions` belum.

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
| GET, PATCH | `/workspace` | reviewer / admin — **ada** (Langkah 1.5): pengaturan workspace aktif (nama, jenis organisasi, zona waktu WIB/WITA/WIT, format tanggal, awal pekan, jam operasional, jam tenang, retensi, `member_count`). `PATCH` hanya mengubah field yang dikirim; `null` menghapus jam operasional/jam tenang; tercatat `workspace.updated` (B-057) |
| GET | `/members` | admin — **ada** (Langkah 1.6): daftar anggota + `last_active_at`, pagination cursor |
| GET, POST | `/members/invites` | admin — **ada** (Langkah 1.6): daftar undangan terbuka (`pending`/`expired`), undang `{email, role}` (email yang sama → undangan lama diganti); anggota aktif → `409 already_member`; workspace Perorangan → `409 personal_workspace` (B-055) |
| POST | `/members/invites/{id}/resend` | admin — **ada**: tautan baru + 7 hari lagi; tautan lama mati |
| DELETE | `/members/invites/{id}` | admin — **ada**: batalkan undangan; id workspace lain → `404 invite_not_found` |
| POST | `/invites/preview` | publik — **ada**: `{token}` → nama workspace, email, peran, pengundang; tidak berlaku → `404 invite_invalid` |
| POST | `/invites/accept` | login (tanpa `X-Workspace-Id`) — **ada**: `{token}` → langsung jadi anggota aktif; email beda → `403 invite_email_mismatch` |
| PATCH, DELETE | `/members/{id}` | admin — **ada**: ubah peran (`{role}`), keluarkan; admin terakhir → `409 last_admin`; id workspace lain → `404 member_not_found`; tercatat di `audit_logs` |
| GET | `/audit-logs` | admin — **ada**: terbaru dulu, pagination cursor; `actor_name`, `action`, `target`, `details` |
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
| GET, POST | `/reference-data?type=region\|commodity\|farmer_group\|unit` | reviewer / form_editor. **GET ada**: filter `parent_id`, `level`, `q` (nama/alias), `geometry=true` (GeoJSON, maks. 50 baris); data platform + milik workspace |
| GET | `/reference-data/locate?lat=&lng=` | reviewer. **Ada**: kecamatan, kab/kota, provinsi dari titik GPS |
| PATCH, DELETE | `/reference-data/{id}` | form_editor |
| POST | `/reference-data/import` | form_editor (CSV) |

## Penyuluh (extension workers)

| Method | Path | Peran |
|---|---|---|
| GET, POST | `/extension-workers` | reviewer / admin |
| GET, PATCH, DELETE | `/extension-workers/{id}` | reviewer / admin |
| GET, PATCH | `/forms/{id}/join-code` | reviewer / admin (PATCH: admin) |
| POST | `/forms/{id}/join-code/rotate` | admin |
| POST | `/extension-workers/{id}/approve`, `/block` | admin |
| ~~POST~~ | ~~`/extension-workers/invites`, `/invites/{id}/resend`~~ | dihapus (B-048) |

## Dashboard

Rancangan, belum dibangun. Rincian, skema respons, dan definisi angka: [dashboard.md](../06-domain-guides/dashboard.md).

| Method | Path | Peran |
|---|---|---|
| GET | `/dashboard/summary?range=today\|7d\|30d` | reviewer (KPI, 7 hari, kondisi, wilayah teratas, status persiapan) |

Peta, jumlah, ekspor, dan SSE untuk dashboard ada di bagian Laporan dan Aktivitas di bawah.

## Laporan (field reports)

| Method | Path | Peran |
|---|---|---|
| GET | `/reports` | reviewer (filter, cursor) |
| GET | `/reports/map` | reviewer (agregat per wilayah + titik; [dashboard.md](../06-domain-guides/dashboard.md#get-reportsmaprangeform_idcondition)) |
| GET | `/reports/count` | reviewer (jumlah untuk jendela unduh) |
| GET | `/reports/photos` | reviewer (galeri) |
| GET | `/reports/{id}` | reviewer |
| PATCH | `/reports/{id}/review` | reviewer (tandai ditinjau) |
| PUT | `/reports/{id}/follow-up` | reviewer (status, assignee, prioritas, catatan) |
| POST | `/reports/exports` | form_editor (pekerjaan ekspor PDF/Excel/CSV; menggantikan `GET /reports/export`) |
| GET | `/reports/exports/{id}` | pembuat / admin (status + tautan unduh) |

## Aktivitas & percakapan

| Method | Path | Peran |
|---|---|---|
| GET | `/activity` | reviewer |
| GET | `/events` | reviewer (SSE; `report.created`, `report.updated`, `worker.activity`, `conversation.needs_help`, `export.ready`; [dashboard.md](../06-domain-guides/dashboard.md#event-realtime-sse)) |
| GET | `/conversations?status=needs_help` | reviewer |
| GET | `/conversations/{id}` | reviewer |
| POST | `/conversations/{id}/takeover` | admin (409 bila sudah diambil admin lain) |
| POST | `/conversations/{id}/messages` | admin (hanya pemilik takeover) |
| POST | `/conversations/{id}/release` | admin (kembalikan ke Fluctuz) |
| POST | `/agent/pause`, `/agent/resume` | admin |

## Kanal

| Method | Path | Peran |
|---|---|---|
| GET | `/bots` | semua anggota (hanya baca: nomor WhatsApp, username Telegram, status) |
| GET | `/channels/logs` | admin (aktivitas pesan organisasi di bot bersama) |
| ~~POST, DELETE~~ | ~~`/channels/telegram`, `/channels/whatsapp`, `/channels/{id}/test`, `/channels/{id}`~~ | dihapus (B-048): organisasi tidak menghubungkan kanal |

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
| POST | `/webhooks/telegram` | Wajib header `X-Telegram-Bot-Api-Secret-Token`; satu URL untuk bot platform |

## Paket dan tagihan

Rincian: [billing-and-plans.md](../06-domain-guides/billing-and-plans.md#endpoint).

| Method | Path | Peran |
|---|---|---|
| GET | `/billing/plans?type=personal\|organization` | publik |
| GET | `/billing/subscription`, `/billing/usage` | login |
| POST | `/billing/checkout`, `/billing/cancel` | admin |
| POST | `/webhooks/payments/{provider}` (tanpa `/api/v1`) | penyedia pembayaran, tanda tangan wajib |

## Artikel

Rancangan, belum dibangun. Rincian: [articles.md](../06-domain-guides/articles.md). Peran di kolom ini adalah **peran platform** (`content_author` < `content_editor`), bukan peran workspace.

| Method | Path | Peran |
|---|---|---|
| GET | `/public/articles`, `/public/articles/{slug}`, `/public/article-categories` | publik |
| GET, POST | `/articles` | content_author |
| GET, PATCH, DELETE | `/articles/{id}` | content_author (draf milik sendiri) / content_editor |
| POST | `/articles/{id}/submit` | content_author |
| POST | `/articles/{id}/return`, `/publish`, `/schedule`, `/unpublish`, `/archive`, `/restore` | content_editor |
| PUT | `/articles/{id}/featured` | content_editor |
| GET, POST | `/articles/{id}/revisions`, `/articles/{id}/revisions/{rev}/restore` | content_author (lihat) / content_editor (pulihkan) |
| POST | `/article-media` | content_author (multipart) |
| GET, POST, PATCH, DELETE | `/article-categories` | GET content_author, sisanya content_editor |

## Publik (untuk website)

| Method | Path | Keterangan |
|---|---|---|
| POST | `/public/leads` | Form kontak/demo dari landing page, dengan rate limit |
