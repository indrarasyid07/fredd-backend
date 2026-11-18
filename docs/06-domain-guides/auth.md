# Auth

Fitur `auth`: endpoint di `app/api/v1/auth/`, logika di `app/modules/auth/`. Masuk, keluar, sesi, daftar, verifikasi email, reset kata sandi, dan Google. Desain layar: [frontend ui/auth.md](https://gitlab.com/databiota-fredd/frontend/-/blob/development/docs/06-domain-guides/ui/auth.md). Format respons: [api-conventions.md](../03-api/api-conventions.md#format-respons). Model keamanan umum: [security-model.md](../05-security-and-access/security-model.md).

## Irisan pengerjaan

Auth dibangun dalam empat irisan. Setiap irisan bisa dijalankan dan dites sendiri.

| Irisan | Isi | Layar | Butuh |
|---|---|---|---|
| **1. Login** | Masuk email + kata sandi, keluar, cek sesi; user dev dibuat lewat CLI | 01 Masuk | Postgres, Redis (sudah ada) |
| 2. Daftar | Daftar, verifikasi email | 02 Daftar | Pengirim email (SMTP / penyedia) |
| 3. Lupa kata sandi | Minta reset, kata sandi baru, cabut sesi lain | 03–06 | Pengirim email |
| 4. Google | Masuk/daftar dengan Google, wajib SSO per workspace | Tombol Google di 01 dan 02 | OAuth client Google Cloud |

Backend irisan 1-4 selesai pada 16 November 2026. Layar web 02-06 belum dibangun: di layar Masuk, tombol Google sudah berfungsi (bila dikonfigurasi), sedangkan "Daftar" dan "Lupa kata sandi?" tampil tanpa tujuan sampai layarnya ada.

## Irisan 1: Login

### Endpoint

| Method | Path | Auth | Body | Sukses | Error |
|---|---|---|---|---|---|
| POST | `/api/v1/auth/login` | publik | `LoginRequest` | `200`, cookie `fluctuz_session`, `data`: `MeResponse` | `401 invalid_credentials`, `422`, `429 too_many_attempts`, `403 csrf_rejected` |
| POST | `/api/v1/auth/logout` | opsional | – | `200`, `data: null`, cookie dihapus | `403 csrf_rejected` |
| GET | `/api/v1/auth/me` | wajib | – | `200`, `data`: `MeResponse` | `401 not_authenticated` |

`logout` selalu `200` meskipun belum login, agar tombol keluar tidak pernah gagal di sisi pengguna.

### Schema

```python
class LoginRequest(BaseModel):
    email: EmailStr  # dinormalisasi: trim + huruf kecil
    password: str = Field(min_length=1, max_length=128)


class UserOut(BaseModel):
    id: UUID
    email: str
    name: str


class MembershipOut(BaseModel):  # app/modules/workspaces/schemas.py; hanya keanggotaan yang disetujui
    workspace_id: UUID
    workspace_name: str
    workspace_type: Literal["personal", "organization"]
    role: Literal["admin", "form_editor", "reviewer"]


class MeResponse(BaseModel):
    user: UserOut
    memberships: list[MembershipOut]
```

Login tidak memeriksa aturan kekuatan kata sandi (hanya tidak kosong); aturan kekuatan berlaku saat daftar dan reset.

### Contoh respons

`POST /api/v1/auth/login` berhasil:

```json
{
  "success": true,
  "message": "Berhasil masuk.",
  "data": {
    "user": { "id": "0193a1b2-7c4d-7e8f-9a0b-1c2d3e4f5a6b", "email": "dina@contoh.id", "name": "Dina Admin" },
    "memberships": []
  },
  "errors": [],
  "meta": { "request_id": "01JCX4K7P9Q2W3E5R6T8Y0U1I2", "timestamp": "2026-11-14T03:24:00Z", "pagination": null }
}
```

Header: `Set-Cookie: fluctuz_session=<token>; HttpOnly; Secure; SameSite=Lax; Path=/; Max-Age=2592000`

Email atau kata sandi salah:

```json
{
  "success": false,
  "message": "Email atau kata sandi salah.",
  "data": null,
  "errors": [{ "code": "invalid_credentials", "message": "Email atau kata sandi salah.", "field": null }],
  "meta": { "request_id": "01JCX5…", "timestamp": "2026-11-14T03:24:05Z", "pagination": null }
}
```

Terlalu banyak percobaan (`429`, header `Retry-After: 840`):

```json
{
  "success": false,
  "message": "Terlalu banyak percobaan. Coba lagi dalam 14 menit.",
  "data": null,
  "errors": [{ "code": "too_many_attempts", "message": "Terlalu banyak percobaan. Coba lagi dalam 14 menit.", "field": null }],
  "meta": { "request_id": "01JCX8…", "timestamp": "2026-11-14T03:26:00Z", "pagination": null }
}
```

### Alur login

```mermaid
sequenceDiagram
  participant B as Browser
  participant R as api/v1/auth/router.py
  participant S as modules/auth/service.py
  participant L as core/rate_limit.py
  participant D as PostgreSQL

  B->>R: POST /api/v1/auth/login {email, password}
  R->>L: cek kunci login:{ip}:{email}
  alt sudah 5 gagal dalam 15 menit
    R-->>B: 429 too_many_attempts + Retry-After
  end
  R->>S: authenticate(email, password)
  S->>D: SELECT user WHERE email = lower(email)
  S->>S: verifikasi argon2 (hash palsu bila user tidak ada)
  alt gagal
    S-->>R: AppError invalid_credentials
    R->>L: tambah hitungan gagal
    R-->>B: 401
  end
  S->>D: INSERT sessions (token_hash, user_agent, ip, expires_at)
  S-->>R: token, MeResponse
  R->>L: hapus hitungan gagal
  R-->>B: 200 + Set-Cookie fluctuz_session
```

### Sesi dan cookie

| Hal | Nilai |
|---|---|
| Nama cookie | `fluctuz_session` |
| Atribut | `HttpOnly; Secure; SameSite=Lax; Path=/`. Di development `Secure` dimatikan otomatis (HTTP lokal) |
| Token | `secrets.token_urlsafe(32)`; hanya hash SHA-256-nya yang disimpan di `sessions.token_hash` |
| Masa berlaku | 30 hari sejak terakhir dipakai (sliding) |
| Perpanjangan | `last_seen_at` dan `expires_at` diperbarui paling sering sekali per 5 menit per sesi, agar tidak menulis ke database di setiap request |
| Logout | `revoked_at` diisi; cookie dihapus (`Max-Age=0`) |
| Validasi per request | `get_current_user`: cari sesi berdasarkan hash token, `revoked_at IS NULL`, `expires_at > now()`; gagal → `401 not_authenticated` |

### Kata sandi

- Hash **argon2id** lewat `argon2-cffi`, parameter bawaan library (setara rekomendasi OWASP: memori 19–64 MiB, 2–3 iterasi).
- Bila parameter berubah di masa depan, hash diperbarui otomatis saat login berhasil (`check_needs_rehash`).
- Saat email tidak ditemukan, service tetap memverifikasi terhadap hash palsu tetap, agar waktu respons tidak membocorkan email mana yang terdaftar.
- `password_hash` bernilai `null` untuk akun yang hanya memakai Google; login kata sandi untuk akun itu → `invalid_credentials`.

### Rate limit

| Kunci Redis | Batas | Reset |
|---|---|---|
| `rl:login:{ip}:{email}` | 5 kegagalan per 15 menit | Dihapus setelah login berhasil |
| `rl:login:{ip}` | 30 kegagalan per 15 menit | Kedaluwarsa otomatis |

Memakai `INCR` + `EXPIRE` (window tetap). Bila Redis tidak tersedia, login tetap berjalan tanpa rate limit dan kejadian dicatat sebagai warning, agar gangguan Redis tidak mengunci semua pengguna.

### CSRF

Middleware `app/api/middleware/csrf.py` berlaku untuk semua request `POST`, `PUT`, `PATCH`, `DELETE` di bawah `/api/`:

- Header `Origin` wajib ada dan sama dengan `APP_BASE_URL`; bila tidak ada, `Referer` dipakai sebagai cadangan.
- Tidak cocok → `403 csrf_rejected`.
- `/webhooks/*` dikecualikan (diverifikasi dengan tanda tangan).
- Di development, `http://localhost:3000` dan `http://localhost:8080` diizinkan lewat `ALLOWED_ORIGINS`.

### Status irisan 1

Selesai 14 November 2026: 27 tes lulus, diuji di browser (mode native) dan lewat Caddy (mode Docker).

Catatan implementasi: `verify_password` dan `hash_password` dijalankan lewat `asyncio.to_thread` karena argon2 memakai CPU puluhan milidetik dan tidak boleh memblokir event loop.

### Membuat user untuk development

User untuk development juga bisa dibuat lewat CLI (langsung terverifikasi, tanpa email):

```bash
uv run python -m scripts.create_user --email dina@contoh.id --name "Dina Admin"
# kata sandi ditanyakan secara interaktif (tidak lewat argumen, agar tidak tersimpan di riwayat shell)
```

Perintah ini menolak berjalan bila `ENVIRONMENT=production`.

### Tabel

| Tabel | Kolom | Index / constraint |
|---|---|---|
| `users` | `id` UUID v7 (PK), `email` text, `name` text, `password_hash` text null, `email_verified_at` timestamptz null, `google_sub` text null, `organization` text null, `created_at`, `updated_at` | `UNIQUE (email)`; email selalu disimpan huruf kecil; `UNIQUE (google_sub)` |
| `auth_tokens` | `id` UUID v7 (PK), `user_id` → users (on delete cascade), `purpose` (`verify_email` \| `reset_password`), `token_hash` text, `created_at`, `expires_at`, `used_at` null | `UNIQUE (token_hash)`; index `(user_id)`; hanya hash yang disimpan |
| `sessions` | `id` UUID v7 (PK), `user_id` → users (on delete cascade), `token_hash` text, `user_agent` text, `ip` inet, `created_at`, `last_seen_at`, `expires_at`, `revoked_at` null | `UNIQUE (token_hash)`; index `(user_id)` |

`email_verified_at` dan `google_sub` dibuat di irisan 1. Migrasi `auth_tokens_and_sign_up_fields` (16 November 2026) menambah `auth_tokens` dan `users.organization`, dan mengisi `email_verified_at` untuk akun yang sudah ada. UUID v7 dibuat dengan `uuid.uuid7()` bawaan Python 3.14.

Migrasi: `alembic/versions/<tanggal>_create_users_and_sessions_<rev>.py`.

### Letak kode

Mengikuti [struktur kode](../02-architecture/system-architecture.md#struktur-kode).

```
app/
├── main.py                      # pasang middleware, exception handler, router
├── api/
│   ├── router.py                # mount v1 (+ webhooks, devtools nanti)
│   ├── cookies.py               # set_session_cookie(), clear_session_cookie(), read_session_token()
│   ├── deps.py                  # get_db, get_current_user, client_ip
│   ├── responses.py             # ApiResponse[T], ApiErrorResponse, ok()
│   ├── errors.py                # handler AppError, validasi, HTTPException, 500
│   ├── middleware/
│   │   ├── request_id.py
│   │   └── csrf.py
│   └── v1/
│       ├── router.py            # /api/v1 + include system, auth
│       ├── system/router.py     # GET /health
│       └── auth/
│           ├── __init__.py
│           └── router.py        # login, logout, get_me, register, verify-email(+resend), password forgot/reset, google login/callback
├── modules/
│   └── auth/
│       ├── __init__.py          # __all__ = ["service", "schemas", "errors"]
│       ├── models.py            # User, Session
│       ├── schemas.py           # LoginRequest, UserOut, MembershipOut, MeResponse
│       ├── repository.py        # user, sesi, dan auth_tokens (issue/consume)
│       ├── service.py           # login, logout, get_me, resolve_session, register, verify_email, resend_verification, forgot_password, reset_password, login_with_google
│       ├── google.py            # alur kode otorisasi + PKCE (httpx)
│       ├── emails.py            # isi email verifikasi, reset, pemberitahuan
│       └── errors.py            # InvalidCredentials, NotAuthenticated, TooManyAttempts, EmailAlreadyRegistered, WeakPassword
├── core/
│   ├── config.py
│   ├── errors.py                # AppError, NotFound, Forbidden, Conflict
│   ├── security.py              # hash_password, verify_password, new_token, hash_token
│   ├── mail.py                  # send_email (SMTP STARTTLS)
│   ├── rate_limit.py
│   ├── redis.py
│   ├── logging.py
│   └── time.py
└── db/
    ├── base.py
    ├── session.py
    └── models.py                # from app.modules.auth.models import *  (untuk Alembic)
scripts/
└── create_user.py
tests/
├── unit/core/test_security.py
├── unit/modules/auth/test_service.py
└── api/v1/auth/test_login.py, test_session.py, test_csrf.py, test_signup_and_reset.py, test_google.py
```

### Kode error

| Code | HTTP | Kapan |
|---|---|---|
| `invalid_credentials` | 401 | Email tidak terdaftar, kata sandi salah, atau akun hanya Google |
| `not_authenticated` | 401 | `/me` tanpa sesi valid |
| `too_many_attempts` | 429 | Batas rate limit login, daftar, kirim ulang, lupa, atau reset tercapai |
| `csrf_rejected` | 403 | `Origin` tidak cocok |
| `required`, `invalid_email` | 422 | Field login kosong atau email tidak valid |
| `email_already_registered` | 409 | Membuat user lewat CLI dengan email yang sudah ada (endpoint daftar tidak memakainya) |
| `email_not_verified` | 403 | Login dengan kata sandi benar tetapi email belum diverifikasi |
| `invalid_token` | 400 | Token verifikasi atau reset salah, terpakai, atau kedaluwarsa (`field: token`) |
| `terms_not_accepted` | 422 | `accept_terms` bukan `true` |
| `weak_password` | 422 | Kata sandi kurang dari 8 karakter atau tanpa huruf dan angka |

### Tes wajib

| # | Skenario | Harapan |
|---|---|---|
| 1 | Login dengan kredensial benar | 200, format respons standar, cookie terpasang dengan atribut benar, baris `sessions` dibuat |
| 2 | Kata sandi salah vs email tidak terdaftar | Keduanya 401 dengan `message` dan `code` identik |
| 3 | Email dengan huruf besar/spasi | Dinormalisasi dan berhasil login |
| 4 | Percobaan gagal ke-6 untuk IP + email yang sama | 429 dengan header `Retry-After` |
| 5 | `/me` dengan cookie valid | 200 dan `data.user` benar |
| 6 | `/me` tanpa cookie, cookie palsu, sesi dicabut, sesi kedaluwarsa | 401 `not_authenticated` |
| 7 | Logout lalu `/me` | 200, lalu 401 |
| 8 | POST login dengan `Origin` domain lain | 403 `csrf_rejected` |
| 9 | Body bukan JSON / field hilang | 400 / 422 dengan `errors[].field` terisi |
| 10 | Respons error 500 (dipaksa di tes) | Format standar, tanpa detail teknis, `request_id` ada di header dan body |

## Irisan 2: Daftar

Selesai 16 November 2026.

| Method | Path | Body | Sukses | Error |
|---|---|---|---|---|
| POST | `/api/v1/auth/register` | `RegisterRequest` | `200`, `data: null` | `422 weak_password`, `422 terms_not_accepted`, `422`, `429 too_many_attempts` |
| POST | `/api/v1/auth/verify-email` | `{token}` | `200`, cookie sesi, `data`: `MeResponse` | `400 invalid_token`, `429` |
| POST | `/api/v1/auth/verify-email/resend` | `{email}` | `200`, `data: null` | `422`, `429` |

```python
class RegisterRequest(BaseModel):
    first_name: str  # 1-100
    last_name: str  # 1-100
    email: EmailStr  # dinormalisasi: trim + huruf kecil
    organization: str | None  # maks 200; disimpan di users.organization
    password: str  # min 8, huruf + angka, maks 128 (weak_password)
    accept_terms: bool  # harus true (terms_not_accepted, field accept_terms)
```

- **Respons seragam.** `register` selalu `200` dengan pesan yang sama, untuk email baru, email yang belum terverifikasi, maupun email yang sudah terdaftar, sehingga tidak bisa dipakai menebak email terdaftar. Email baru atau belum terverifikasi menerima tautan verifikasi (24 jam, sekali pakai); email yang sudah terverifikasi menerima pemberitahuan tanpa tautan. Kata sandi di-hash di semua jalur agar waktu respons sama.
- **Daftar ulang sebelum verifikasi** membatalkan tautan lama dan mengirim yang baru; kata sandi dari pendaftaran pertama tetap berlaku (isian kedua diabaikan).
- **Login sebelum verifikasi** → `403 email_not_verified`, hanya setelah kata sandi benar. User yang dibuat CLI dan akun lama dianggap sudah terverifikasi (migrasi mengisi `email_verified_at`).
- **`verify-email`** menandai email terverifikasi dan langsung membuat sesi. Token salah, sudah dipakai, atau kedaluwarsa → `400 invalid_token` (`field: token`).
- **`resend`** selalu `200`; hanya mengirim bila email ada dan belum terverifikasi.
- **Rate limit** (Redis, window tetap, dihitung per permintaan): `register` 10 per jam per IP; `resend` 3 per jam per email dan 20 per jam per IP; `verify-email` 30 per jam per IP.
- **Tautan di email:** `{APP_BASE_URL}/login/verify-email?token=…`. Halaman web-nya belum dibangun; sementara itu token bisa dikirim langsung ke `verify-email`.
- Workspace Perorangan paket Gratis (user sebagai `admin`) dibuat saat verifikasi email, daftar/masuk Google, dan `create_user`; login juga membuatnya bila akun lama belum punya (B-050). `/auth/me` mengembalikan `memberships` yang sudah disetujui (Perorangan dulu, lalu Organisasi urut nama); workspace aktif dipilih dengan header `X-Workspace-Id` (B-051); `organization` tetap hanya disimpan di user.

### Pengiriman email

`app/core/mail.py`: SMTP dengan STARTTLS, teks polos, dijalankan lewat `BackgroundTasks` setelah respons terkirim (server email yang lambat tidak menunda respons dan tidak membocorkan ada tidaknya akun). `send_email` tidak pernah melempar error; kegagalan dicatat di log.

| Variabel | Arti |
|---|---|
| `SMTP_HOST`, `SMTP_PORT` (587), `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` | Server pengirim. Penyedia belum dipilih; semua yang mendukung SMTP + STARTTLS cocok |
| (`SMTP_HOST` kosong) | Development: isi email, termasuk tautannya, ditulis ke log API (cara mengambil tautan saat mengembangkan). Produksi: dicatat sebagai error, email tidak terkirim |

Isi email ada di `app/modules/auth/emails.py`.

## Irisan 3: Lupa kata sandi

Selesai 16 November 2026.

| Method | Path | Body | Sukses | Error |
|---|---|---|---|---|
| POST | `/api/v1/auth/password/forgot` | `{email}` | `200`, `data: null` | `422`, `429` |
| POST | `/api/v1/auth/password/reset` | `{token, password}` | `200`, `data: null` | `400 invalid_token`, `422 weak_password`, `429` |

- `forgot` selalu `200` dengan pesan yang sama. Bila akun ada, token 30 menit dikirim; permintaan baru membatalkan token lama. Akun yang hanya memakai Google juga bisa menetapkan kata sandi lewat alur ini.
- `reset`: kekuatan kata sandi diperiksa **sebelum** token dipakai, jadi salah ketik tidak menghanguskan tautan. Sukses: kata sandi baru (argon2id), email ditandai terverifikasi (tautan membuktikan kepemilikan), dan **semua sesi user dicabut**. Reset tidak membuat sesi; pengguna diarahkan ke layar Masuk.
- Rate limit: `forgot` 3 per jam per email dan 20 per jam per IP (tetap `429` untuk email yang tidak ada, jadi tidak membocorkan apa pun); `reset` 30 per jam per IP.
- Tautan di email: `{APP_BASE_URL}/login/reset-password?token=…` (halaman web belum dibangun).
- Token disimpan sebagai hash SHA-256 di `auth_tokens`; satu `UPDATE … RETURNING` menandainya terpakai, jadi dua permintaan serentak tidak bisa memakainya dua kali.

## Irisan 4: Google

Selesai 16 November 2026. Aktif hanya bila `GOOGLE_CLIENT_ID` dan `GOOGLE_CLIENT_SECRET` diisi.

| Method | Path | Catatan |
|---|---|---|
| GET | `/api/v1/auth/google/login?next=` | `303` ke Google (kode otorisasi + PKCE S256) |
| GET | `/api/v1/auth/google/callback` | Menukar kode, membuat sesi, `303` ke `{APP_BASE_URL}{next}` |

Kedua endpoint dibuka langsung oleh browser, jadi mereka mengalihkan, bukan mengembalikan JSON, dan tidak masuk `openapi.json`.

- **State.** `login` membuat `state` dan `code_verifier`, menyimpannya di Redis (`oauth:google:{state}`, 10 menit), dan hanya `state` yang dipasang di cookie `fluctuz_oauth` (HttpOnly, `SameSite=Lax`, path `/api/v1/auth/google`). `callback` menolak bila `state` di query tidak sama dengan cookie atau tidak ada di Redis, dan mengambilnya dengan `GETDEL` (sekali pakai).
- **Profil.** Kode ditukar dengan `client_secret` dan `code_verifier` lewat TLS, lalu `userinfo` dibaca. `email_verified` wajib `true`.
- **Pencocokan akun:** `google_sub` → email → akun baru.
  - Cocok `google_sub`: masuk.
  - Email sudah ada: `google_sub` ditautkan dan email ditandai terverifikasi. Bila akun itu **belum terverifikasi**, kata sandinya dihapus, karena bisa jadi dibuat orang lain dengan email ini (mencegah pembajakan akun lewat pendaftaran lebih dulu).
  - Belum ada: akun baru tanpa kata sandi, langsung terverifikasi.
- **`next`** hanya boleh diawali `/app` (bukan `//`, tanpa `\`); selain itu `/app`.
- **Gagal** → `303` ke `{APP_BASE_URL}/login?error=<alasan>`: `google_unavailable` (belum dikonfigurasi), `google_failed` (state salah, ditolak pengguna, atau Google/Redis bermasalah). Layar Masuk menampilkan pesannya.
- **Konfigurasi Google Cloud:** daftarkan *Authorized redirect URI* `{APP_BASE_URL}/api/v1/auth/google/callback` (mis. `http://localhost:8080/api/v1/auth/google/callback` untuk Docker).
- **Belum dikerjakan:** `require_sso` dan domain yang diizinkan per workspace menunggu modul workspaces.

## Endpoint sesi lain (setelah irisan 1)

| Method | Path | Catatan |
|---|---|---|
| GET | `/api/v1/auth/sessions` | Daftar sesi aktif milik user (halaman Keamanan) |
| DELETE | `/api/v1/auth/sessions/{id}` | Keluarkan sesi lain; tidak bisa menghapus sesi saat ini (pakai logout) |
