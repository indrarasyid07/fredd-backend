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
| GET, POST | `/forms` | reviewer / form_editor. **Ada**: daftar terbaru dulu (cursor); POST membuat form `draft` + versi 1 sebagai draf |
| GET, PATCH | `/forms/{id}` | reviewer / form_editor (hanya draf). **Ada**: PATCH = autosave wizard (`name`, `description`, `definition`, `settings`); tanpa draf → 409 `form_not_editable` |
| POST, DELETE | `/forms/{id}/draft` | form_editor. **Ada**: POST membuka struktur aktif untuk diubah: draf versi berikutnya, salinan versi aktif; idempoten (draf yang terbuka dikembalikan); audit `form.draft_opened`; diarsipkan → 409 `form_archived`. DELETE membuang draf itu, versi aktif tetap; audit `form.draft_discarded`; form yang belum pernah terbit → 409 `draft_is_only_version`. Lihat [forms.md](../06-domain-guides/forms.md#mengubah-struktur-yang-sudah-aktif) |
| GET | `/form-templates` | reviewer. **Ada**: katalog template wizard per sektor |
| GET | `/forms/{id}/versions` | reviewer |
| POST | `/forms/{id}/validate` | form_editor (periksa otomatis). **Ada**: selalu 200 dengan `{valid, errors[], warnings[]}`; tiap masalah punya `code`, `message`, `field` bertitik (`fields.2.question`); tanpa draf → 409 |
| POST | `/forms/{id}/voice-test` | form_editor. **Ada (12.2)**: `{text}` (≤ 1.000 karakter, kalimat yang akan diucapkan analis) → nilai yang terbaca memakai draf yang sedang disunting (atau versi terbit bila tanpa draf): `values[]` (`key`, `label`, `value`, `display`, `confidence`, `confident`, `heard`, `doubt`) dan `missing[]` isian wajib yang belum disebut. Tidak menyimpan apa pun. Lihat [voice-lab.md](../06-domain-guides/voice-lab.md) |
| POST | `/forms/{id}/test-runs` | form_editor (uji di akun sendiri) |
| POST | `/forms/{id}/pilot` | admin (body: daftar extension_worker_id) |
| POST | `/forms/{id}/publish` | admin. **Ada**: draf → versi terbit (`published_at`, `current_version_id`), status `active`, audit `form.publish`; masih ada masalah → 422 `form_has_problems`; tanpa draf → 409 `form_not_editable`; diarsipkan → 409 `form_archived` |
| POST | `/forms/{id}/archive` | admin. **Ada**: status `archived`, audit `form.archive`, idempoten; form arsip tidak bisa diubah atau dipublikasikan |
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
| GET | `/extension-workers` | reviewer. **Ada (4.4)**: filter `status` (boleh berulang), `channel` (`telegram`/`whatsapp`), `form_id` (punya topik aktif), `q` (nama); `sort` = `newest` (bawaan), `last_active`, `name`; cursor. Tiap baris: `name`, `status`, `pending_reason`, `channel`, `telegram_username`, `phone_e164`, `region` (`id`, `name`), `joined_at`, `confirmed_at`, `last_active_at`, `topic` (terbaru: `form_id`, `form_name`, `join_code`), `topic_count`. Penyuluh dibuat lewat kode gabung, bukan POST |
| GET | `/extension-workers/summary` | reviewer. **Ada (4.4)**: `total`, `active`, `pending_approval`, `inactive` (left + blocked + unreachable), `new_this_week` (aktif, bergabung 7 hari terakhir), `manual_approval_forms`. Angka laporan menyusul bersama tabel `reports` |
| GET, PATCH | `/extension-workers/{id}` | GET reviewer, PATCH admin. **Ada (4.4)**: GET = baris daftar + `name_source` + `topics` (semua topik, aktif dulu: `form_name`, `status`, `join_code`, `joined_at`, `left_at`). PATCH `name` (→ `name_source = admin`), `region_id` (wilayah yang terlihat workspace, salah → `422 unknown_region` di `region_id`; `null` mengosongkan); audit `extension_worker.updated`. DELETE belum (data laporan harus tetap) |
| GET | `/extension-workers/{id}/reports` | reviewer. Belum: menunggu tabel `reports` (4.0) |
| GET, PATCH | `/forms/{id}/join-code` | reviewer / admin (PATCH: admin). **Ada**: kode (`K7M2-9QXA`), status, `approval_mode`, `max_uses`, `expires_at`, `use_count`, `claimable` (kode aktif dan form pilot/aktif), tautan WhatsApp/Telegram (null bila bot belum diatur). PATCH: `status` (`active`/`paused`), `approval_mode`, `max_uses`, `expires_at` |
| POST | `/forms/{id}/join-code/rotate` | admin. **Ada (3.10)**: kode lama `revoked` (+`revoked_at`), kode baru dengan `approval_mode`, `max_uses`, `expires_at` (bila belum lewat) dan status jeda yang sama, `use_count` 0; audit `join_code.rotated`. Penyuluh yang sudah bergabung tetap terhubung |
| POST | `/extension-workers/{id}/approve` | admin. **Ada (4.6)**: hanya untuk `pending_approval` (selain itu `409 extension_worker_not_pending`; workspace lain `404 extension_worker_not_found`). Penyuluh `active`, topik terbaru dibuka di chat dan bot mengirim "Permintaan Anda sudah disetujui… Sudah benar?" dengan tombol Ya, tetap / Bukan, ganti (bila chat sedang di topik lain, topik itu tetap dan bot hanya mengabarkan). Audit `extension_worker.approved` |
| POST | `/extension-workers/{id}/block`, `/unblock` | admin. **Ada (4.6, diperluas 4.4)**: block untuk penyuluh berstatus apa pun selain `blocked` (`409 extension_worker_already_blocked`): semua topik aktif `left`, `chat_contexts` yang menunjuk topik itu dikosongkan, tanpa pesan ke penyuluh; kode organisasi ini dibalas "kode tertutup". Unblock hanya dari `blocked` (`409 extension_worker_not_blocked`) → `left`; penyuluh bergabung lagi dengan mengirim kode. Audit `extension_worker.blocked` / `.unblocked` |
| ~~POST~~ | ~~`/extension-workers/invites`, `/invites/{id}/resend`~~ | dihapus (B-048) |

## Dashboard

Rancangan, belum dibangun. Rincian, skema respons, dan definisi angka: [dashboard.md](../06-domain-guides/dashboard.md).

| Method | Path | Peran |
|---|---|---|
| GET | `/dashboard/forms/{form_id}?range=today\|7d\|30d` | reviewer. **Ada (4.7)**: data widget generik satu struktur (D17): `total`, `daily` 7 hari, setiap isian pilihan (`choices`: nilai, label, jumlah, persen; pilihan tunggal berjumlah 100, pilihan ganda = bagian laporan yang menjawab) dan angka (`numbers`: count, sum, avg, min, max) menurut urutan versi terkini (nilai dari versi lama tetap dihitung), kabupaten teratas. Struktur workspace lain → `404` |
| GET | `/dashboard/summary?range=today\|7d\|30d` | reviewer. **Ada (4.2)**: KPI, `daily` + `previous_daily` (7 + 7 hari), `hourly` (`yesterday` dan `today`, masing-masing 24 angka per jam di zona workspace; untuk peta jam sibuk Laporan masuk), `channels` (persen 7 hari), kondisi + wilayah Terserang teratas (mengikuti `range`), `top_regions` (kabupaten), `setup` (`form_created`, `channel_and_worker`, `has_reports`). Cache Redis 15 dtk per (workspace, rentang); lihat [dashboard.md](../06-domain-guides/dashboard.md) |

Peta, jumlah, ekspor, dan SSE untuk dashboard ada di bagian Laporan dan Aktivitas di bawah.

## Laporan (field reports)

| Method | Path | Peran |
|---|---|---|
| GET | `/reports` | reviewer. **Ada (4.3)**: terbaru dahulu (`received_at`, cursor); filter `form_id`, `extension_worker_id`, `region_id`, `condition` (boleh berulang; `unknown` = tanpa kondisi), `needs_review`, `since` (inklusif), `until` (eksklusif), `voice` (Voice Lab 12.4: `true` hanya laporan dari pesan suara, baris membawa `transcript`), `q` (≤ 100 karakter: cari di kode laporan, nama penyuluh, dan nama wilayah, tidak peka huruf besar/kecil). Baris: kode, struktur, penyuluh, kanal, wilayah, kondisi, `area_ha`, `photo_count`, `needs_review`, `complete`, `received_at` |
| GET | `/reports/map` | reviewer (agregat per wilayah + titik; [dashboard.md](../06-domain-guides/dashboard.md#get-reportsmaprangeform_idcondition)) |
| GET | `/reports/count` | reviewer (jumlah untuk jendela unduh) |
| GET | `/reports/photos` | reviewer (galeri) |
| GET | `/reports/{id}` | reviewer. **Ada (4.3)**: isian berlabel menurut **versi struktur saat laporan dibuat** (`value` mentah + `display` Bahasa Indonesia, mis. "1,5 ha", "Terserang", "Dilewati"), lokasi, wilayah, foto dengan URL bertanda tangan (`STORAGE_PRESIGN_EXPIRY_SECONDS`; `url: null` bila foto masih rujukan Telegram atau penyimpanan lokal), `photos[].ai_note` (catatan AI untuk peninjau, 12.7; null bila belum/tidak diperiksa), alasan tinjauan dalam kalimat, dan `voice` (12.4: transkrip, URL rekaman bertanda tangan, kata yang didengar + keyakinan per isian; null untuk laporan chat). Workspace lain → `404 report_not_found` |
| POST | `/reports/{id}/corrections` | reviewer. **Ada (12.5)**: `{field_key, value, reason}` (alasan wajib ≥ 3 karakter). Nilai diketik dibaca dengan aturan suara/chat (angka + satuan isian, pilihan, tanggal, teks); kolom filter, `report_values`, dan kelengkapan dihitung ulang; riwayat `report_corrections` + audit `report.corrected`. Isian lokasi/media/tidak dikenal → `422 field_not_correctable`; tak terbaca atau satuan lain → `422 invalid_correction`; laporan terverifikasi → `409 report_already_verified` |
| POST | `/reports/{id}/verify` | reviewer. **Ada (12.5)**: `verified_at` + `verified_by_user_id`, audit `report.verified`; sudah terverifikasi → `409 report_already_verified`. Detail membawa `verification` dan `corrections[]`; daftar membawa `verified` dan menerima filter `verified=true\|false` |
| GET | `/reports/voice-export` | form_editor. **Ada (12.6)**: `?form_id=&format=csv|xlsx&since=&until=`; langsung mengirim berkas (`Content-Disposition: attachment`) berisi laporan **suara yang sudah diverifikasi** dari satu struktur, terlama dulu: Nomor, Analis, Diterima, Diverifikasi oleh, Waktu verifikasi, lalu satu kolom per isian (isian media tidak ikut). Waktu dalam zona workspace; CSV UTF-8 ber-BOM, angka bertitik; Excel menyimpan angka sebagai angka. Maks 5.000 baris → `422 export_too_large`; struktur lain workspace → `404 form_not_found`. Audit `report.voice_exported` |
| PATCH | `/reports/{id}/review` | reviewer (tandai ditinjau) |
| PUT | `/reports/{id}/follow-up` | reviewer (status, assignee, prioritas, catatan) |
| POST | `/reports/exports` | form_editor (pekerjaan ekspor PDF/Excel/CSV; menggantikan `GET /reports/export`) |
| GET | `/reports/exports/{id}` | pembuat / admin (status + tautan unduh) |

## Aktivitas & percakapan

| Method | Path | Peran |
|---|---|---|
| GET | `/activity` | reviewer. **Ada (6.2)**: log Aktivitas Agent, terbaru di atas, cursor (`occurred_at`, `id`); filter `type` = `report_received` \| `needs_help`. Tiap baris: `type`, `status` (`done`, `needs_review`, `needs_help`), `channel`, `extension_worker {id, name}` (null untuk sistem), `conversation_id`, `details` (`form_name` + `report_id`/`code` atau `reason`/`field`/`field_label`) |
| GET | `/events` | reviewer (SSE; `report.created`, `report.updated`, `worker.activity`, `conversation.needs_help`, `export.ready`; [dashboard.md](../06-domain-guides/dashboard.md#event-realtime-sse)) |
| GET | `/conversations?status=needs_help` | reviewer. **Ada (6.3)**: terakhir berubah di atas, cursor (`updated_at`, `id`); `status` opsional = `needs_help` \| `taken_over`. Tiap baris: penyuluh, struktur, kanal, `step`, `last_inbound_at`, dan `help {reason, field, field_label, at}` selama `needs_help` |
| GET | `/conversations/{id}` | reviewer. **Ada (6.3)**: baris daftar + 50 pesan terakhir (terlama dulu; `delivery_status` hanya pesan keluar, Telegram tidak pernah `read`). Workspace lain → `404 conversation_not_found` |
| POST | `/conversations/{id}/takeover` | admin (409 `conversation_taken_over` bila sudah diambil admin lain). **Ada (6.4)**: mengembalikan detail percakapan; respons percakapan kini menyertakan `taken_over_by {id, name}`, `taken_over_at`, `whatsapp_window_expires_at` (null untuk Telegram) |
| POST | `/conversations/{id}/messages` | admin (hanya pemilik takeover, selain itu 403 `not_taken_over_by_you`). **Ada (6.4)**: body `{text}` 1–2000 karakter; mengembalikan pesan (`admin_name`); WhatsApp di luar 24 jam → 409 `whatsapp_window_closed` |
| POST | `/conversations/{id}/release` | admin (kembalikan ke Fluctuz). **Ada (6.4)**: tanpa takeover → 409 `conversation_not_taken_over`; otomatis setelah 4 jam tanpa balasan admin |
| POST | `/agent/pause`, `/agent/resume` | admin |

## Pengaturan agent

Satu pengaturan per organisasi, dipakai bot untuk semua struktur data. Lihat [conversation-engine.md](../06-domain-guides/conversation-engine.md#pengaturan-agent).

| Method | Path | Peran |
|---|---|---|
| GET | `/agent/settings` | reviewer. **Ada**: `name`, `style` (`friendly`/`formal`/`brief`), `greeting` (null = sapaan bawaan gaya), `read_free_answers`, `voice_and_photos`, `updated_at`, plus `ai_available` / `voice_available` (server punya penyedia LLM / STT OpenAI). Belum pernah disimpan → nilai bawaan |
| PUT | `/agent/settings` | admin. **Ada**: body = lima kolom di atas (`name` 1–40 karakter, `greeting` ≤ 200; spasi dirapikan; kolom lain → 422). Disimpan di `workspaces.settings["agent"]`, berlaku mulai pesan berikutnya; audit `agent.settings_updated` dengan daftar kolom yang berubah |
| POST | `/agent/preview` | reviewer. **Ada**: body = pengaturan yang dicoba, `?topic=` opsional (judul laporan; bawaan contoh struktur). Mengembalikan `after_join`, `report_start`, `report_opening` (kalimat pembuka saja), `report_saved`. Tidak menyimpan apa pun |
| POST | `/agent/test` | admin. **Ada**: `{form_id, settings, messages[]}` (≤ 40 pesan `{text?, button?, ai_text?}`). Server memutar ulang seluruh percakapan lewat mesin percakapan yang sama dengan pengaturan yang dicoba dan mengembalikan `turns[]` (`message`, `replies[]` dengan tombol, `events[]`, `ai_text`) dan `status`. Tidak menyimpan percakapan, laporan, atau penyuluh; bacaan AI dikembalikan agar putaran berikutnya tidak memanggil model lagi. Struktur tanpa versi terbit → 409 `form_not_testable` |

## Kanal

| Method | Path | Peran |
|---|---|---|
| GET | `/bots` | semua anggota. **Ada (3.10)**: daftar `{type, name, handle, url, available}` untuk WhatsApp dan Telegram dari env `WHATSAPP_PUBLIC_NUMBER` / `TELEGRAM_BOT_USERNAME`; `available: false` bila belum diatur di lingkungan itu |
| GET | `/channels/logs` | admin (aktivitas pesan organisasi di bot bersama). **Ada (7.2)**: terbaru di atas, cursor (`created_at`, `id`); `status=failed` = "Susul yang gagal" (pesan keluar `failed`/`uncertain` yang tidak dicoba ulang lagi). Tanpa isi pesan; kontak disamarkan (`+62 811-****-1234`, `•••6789`); `failure` = `blocked`, `network`, `rejected`, `taken_over`, `timeout`, `other`; `retrying` |
| POST | `/channels/logs/{message_id}/resend` | admin. **Ada (7.2)**: kirim ulang pesan keluar `failed` (audit `message.resent`); selain itu 409 `message_not_resendable`; workspace lain 404 `channel_message_not_found` |
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
