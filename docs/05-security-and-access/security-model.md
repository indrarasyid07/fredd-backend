# Security Model

## Login dashboard

- Email + kata sandi: hash argon2id, minimal 8 karakter dengan huruf dan angka, email wajib diverifikasi sebelum bisa membuat workspace. Token verifikasi dan reset (30 menit) disimpan sebagai hash dan hanya sekali pakai. Reset kata sandi mencabut semua sesi lain.
- Endpoint login, daftar, dan lupa kata sandi diberi rate limit per IP dan per email; pesan error tidak membedakan "email tidak terdaftar" dan "kata sandi salah".
- Workspace Organisasi bisa mewajibkan SSO Google (`require_sso`); anggotanya tidak bisa masuk dengan kata sandi.
- Google OAuth (authlib). Domain email yang diizinkan diatur per workspace; anggota baru dari domain itu menunggu persetujuan admin.
- Setelah callback, backend membuat baris `sessions` dan mengirim cookie:
  `fredd_session=<token acak 32 byte>; HttpOnly; Secure; SameSite=Lax; Path=/`
- Database hanya menyimpan hash token. Sesi bisa dicabut (halaman Keamanan › Sesi aktif).
- Sesi kedaluwarsa setelah 30 hari tidak aktif; diperpanjang saat dipakai.

## CSRF

Cookie `SameSite=Lax` + middleware yang menolak request selain GET/HEAD/OPTIONS bila header `Origin` bukan domain Fredd. Tidak perlu token CSRF terpisah. Webhook dikecualikan (diverifikasi tanda tangan).

## Peran

| Hak akses | admin | form_editor | reviewer |
|---|---|---|---|
| Lihat dashboard dan data lapangan | ya | ya | ya |
| Buat dan ubah struktur data | ya | ya | tidak |
| Ekspor data dan laporan | ya | ya | tidak |
| Kelola penyuluh | ya | tidak | tidak |
| Kelola kanal | ya | tidak | tidak |
| Kelola anggota dan pengaturan | ya | tidak | tidak |

Diterapkan sebagai dependency FastAPI (`require_role("admin")`). Frontend menyembunyikan tombol sesuai peran, tetapi backend yang menolak.

## Isolasi tenant

- Setiap query difilter `workspace_id` dari sesi, tidak pernah dari input request.
- Event realtime dipublikasikan ke channel Redis `events:{workspace_id}`; `/api/v1/events` hanya berlangganan workspace milik sesi.

## Webhook

- WhatsApp: verifikasi `X-Hub-Signature-256` (HMAC-SHA256 dengan app secret) atas body mentah; tolak bila tidak cocok.
- Telegram: `setWebhook` dengan `secret_token` acak per kanal; tolak bila header `X-Telegram-Bot-Api-Secret-Token` tidak cocok.
- Pesan disimpan dengan `UNIQUE (channel_id, external_id)` sehingga pengiriman ulang tidak dobel.

## Rahasia dan enkripsi

- Token bot Telegram dan kredensial WhatsApp dienkripsi dengan `MultiFernet([key_new, key_old])`. Kunci dari env, bisa dirotasi tanpa memutus kanal.
- Token tidak pernah dikembalikan ke frontend (hanya 6 karakter terakhir).
- Rahasia lain lewat env; tidak ada rahasia di repo.

## Berkas

- Bucket privat. Foto dilayani lewat URL bertanda tangan berumur 10 menit.
- Validasi tipe dan ukuran media sebelum disimpan.

## Data pribadi

- Nama petani dan nomor HP penyuluh bisa disamarkan saat ekspor.
- Retensi: percakapan 12 bulan, foto 24 bulan (dapat diatur per workspace), dijalankan cron.
- Log audit untuk ekspor, ubah peran, publikasi struktur, ambil alih, hapus workspace.

## Pembayaran

- Checkout di halaman hosted penyedia; Fredd tidak menerima atau menyimpan data kartu.
- Status langganan hanya berubah dari webhook penyedia yang tanda tangannya terverifikasi; idempoten per ID transaksi.

## Rate limit

- `/api/v1/public/leads` dan endpoint login: rate limit per IP di Redis.
- Pengiriman pesan keluar mengikuti batas kanal (WA: batas percakapan harian; Telegram: ~30 pesan/detik per bot).

## Lain-lain

- `/api/docs` hanya di development.
- Fitur LLM ("Tanya Fredd", insight) hanya menerima data workspace milik sesi dan menandai hasilnya "perlu diverifikasi".
