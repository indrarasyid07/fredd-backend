# Security Model

## Login dashboard

- Email + kata sandi: hash argon2id, minimal 8 karakter dengan huruf dan angka, email wajib diverifikasi sebelum bisa masuk dan membuat workspace. Token verifikasi dan reset (30 menit) disimpan sebagai hash dan hanya sekali pakai. Reset kata sandi mencabut semua sesi lain.
- Endpoint login, daftar, dan lupa kata sandi diberi rate limit per IP dan per email; pesan error tidak membedakan "email tidak terdaftar" dan "kata sandi salah".
- Workspace Organisasi bisa mewajibkan SSO Google (`require_sso`); anggotanya tidak bisa masuk dengan kata sandi.
- Google OAuth: kode otorisasi + PKCE lewat httpx; `state` sekali pakai di Redis; akun belum terverifikasi yang ditautkan ke Google kehilangan kata sandinya. Domain email yang diizinkan diatur per workspace; anggota baru dari domain itu menunggu persetujuan admin.
- Setelah callback, backend membuat baris `sessions` dan mengirim cookie:
  `fluctuz_session=<token acak 32 byte>; HttpOnly; Secure; SameSite=Lax; Path=/`
- Database hanya menyimpan hash token. Sesi bisa dicabut (halaman Keamanan › Sesi aktif).
- Sesi kedaluwarsa setelah 30 hari tidak aktif; diperpanjang saat dipakai.

## CSRF

Cookie `SameSite=Lax` + middleware yang menolak request selain GET/HEAD/OPTIONS bila header `Origin` bukan domain Fluctuz. Tidak perlu token CSRF terpisah. Webhook dikecualikan (diverifikasi tanda tangan).

## Peran

| Hak akses | admin | form_editor | reviewer |
|---|---|---|---|
| Lihat dashboard dan data lapangan | ya | ya | ya |
| Buat dan ubah struktur data | ya | ya | tidak |
| Ekspor data dan laporan | ya | ya | tidak |
| Kelola penyuluh | ya | tidak | tidak |
| Kelola kanal | ya | tidak | tidak |
| Kelola anggota dan pengaturan | ya | tidak | tidak |

Diterapkan sebagai dependency FastAPI di `app/api/deps.py` (Langkah 1.4). Frontend menyembunyikan tombol sesuai peran (`can()`), tetapi backend yang menolak.

```python
from app.api.deps import AdminMember, EditorMember, ReviewerMember

@router.get("")                      # lihat data: semua peran
async def list_forms(member: ReviewerMember, db: DB): ...

@router.post("")                     # ubah struktur data / ekspor
async def create_form(member: EditorMember, db: DB): ...

@router.post("/{id}/members")        # kelola anggota, penyuluh, kanal, pengaturan
async def invite(member: AdminMember, db: DB): ...
```

- Urutan `reviewer < form_editor < admin`; `require_role(min_role)` membuat dependency untuk tingkat lain bila perlu.
- Urutan pemeriksaan: tanpa sesi `401 not_authenticated` → tanpa `X-Workspace-Id` `400 workspace_required` → bukan anggota yang disetujui `404 workspace_not_found` → peran kurang `403 forbidden`. Admin workspace lain tetap mendapat 404.
- `workspace_id` untuk query selalu `member.workspace_id`, tidak pernah dari body/query.
- Tabel milik tenant memakai mixin `WorkspaceOwned` (`app/db/base.py`); repository-nya menerima `workspace_id` sebagai argumen wajib dan memakai `in_workspace(stmt, Model, workspace_id)`.
- Tes domain lain: fixture `organization` dan helper `add_member(...)` / `sign_in(...)` di `tests/conftest.py`.

## Peran platform (konten)

Selain peran workspace, `users.platform_role` (`content_author`, `content_editor`) memberi akses ke pengelolaan artikel Fluctuz. Tidak bisa diatur lewat API atau UI, hanya lewat CLI; admin workspace pelanggan tidak mendapat akses apa pun ke blog. Dependency `require_platform_role(...)`. Rincian, serta aturan unggah gambar dan Markdown: [articles.md](../06-domain-guides/articles.md).

## Isolasi tenant

- Setiap query difilter `workspace_id` dari sesi, tidak pernah dari input request.
- Event realtime dipublikasikan ke channel Redis `events:{workspace_id}`; `/api/v1/events` hanya berlangganan workspace milik sesi.

## Webhook

- WhatsApp: verifikasi `X-Hub-Signature-256` (HMAC-SHA256 dengan app secret) atas body mentah; tolak bila tidak cocok.
- Telegram: `setWebhook` dengan `secret_token` acak untuk bot platform; tolak bila header `X-Telegram-Bot-Api-Secret-Token` tidak cocok.
- Pesan disimpan dengan `UNIQUE (channel_id, external_id)` sehingga pengiriman ulang tidak dobel.

## Rahasia dan enkripsi

- Token bot Telegram dan kredensial WhatsApp adalah rahasia **platform** (env atau secret manager), tidak lagi disimpan per organisasi. Bila kelak ada bot sendiri untuk Enterprise, kredensialnya dienkripsi dengan `MultiFernet([key_new, key_old])`.
- Token tidak pernah dikembalikan ke frontend.

## Kode gabung

Kode gabung adalah rahasia setingkat undangan: acak 40 bit, tidak pernah turunan nama topik, hanya tampil ke admin dan reviewer organisasi pemiliknya, dibatasi percobaan salin (5 salah per jam per identitas chat), dan bisa dijeda, dibatasi, kedaluwarsa, dicabut, atau diganti. Klaim, persetujuan, pemblokiran, dan pembuatan ulang tercatat di `audit_logs`. Pesan dari identitas chat tanpa ikatan tidak boleh membuat percakapan, laporan, atau media di organisasi mana pun (diuji khusus). Rincian: [join-codes.md](../06-domain-guides/join-codes.md#keamanan-dan-penyalahgunaan).
- Rahasia lain lewat env; tidak ada rahasia di repo.

## Berkas

- Bucket privat. Foto dilayani lewat URL bertanda tangan berumur 10 menit.
- Validasi tipe dan ukuran media sebelum disimpan.
- Gambar blog memakai awalan **publik** yang terpisah dari bucket privat ini ([articles.md](../06-domain-guides/articles.md#media)); foto laporan tidak pernah di sana.

## Data pribadi

- Nama petani dan nomor HP penyuluh bisa disamarkan saat ekspor.
- Retensi: percakapan 12 bulan, foto 24 bulan (dapat diatur per workspace), dijalankan cron.
- Log audit untuk ekspor, ubah peran, publikasi struktur, ambil alih, hapus workspace.

## Pembayaran

- Checkout di halaman hosted penyedia; Fluctuz tidak menerima atau menyimpan data kartu.
- Status langganan hanya berubah dari webhook penyedia yang tanda tangannya terverifikasi; idempoten per ID transaksi.

## Rate limit

- `/api/v1/public/leads` dan endpoint login: rate limit per IP di Redis.
- Pengiriman pesan keluar mengikuti batas kanal (WA: batas percakapan harian; Telegram: ~30 pesan/detik per bot).

## Lain-lain

- `/api/docs` hanya di development.
- Fitur LLM ("Tanya Fluctuz", insight) hanya menerima data workspace milik sesi dan menandai hasilnya "perlu diverifikasi".
