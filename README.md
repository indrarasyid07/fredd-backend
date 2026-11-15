# Fredd API

Backend Fredd: API FastAPI, worker, dan migrasi database.

- [Tentang Fredd](#tentang-fredd)
- [Gambaran teknis](#gambaran-teknis)
- [Repo ini: backend](#repo-ini-backend)

## Tentang Fredd

Fredd adalah **asisten AI untuk pengumpulan data lapangan**. Penyuluh pertanian cukup melapor lewat chat WhatsApp atau Telegram yang sudah mereka pakai setiap hari; Fredd menanyakan isian satu per satu, memeriksa jawabannya, lalu menyimpannya sebagai data rapi yang langsung tampil di dashboard instansi.

### Masalah yang diselesaikan

Laporan lapangan (kondisi tanaman, serangan hama, luas tanam, hasil panen) umumnya dikumpulkan lewat formulir kertas, spreadsheet, atau pesan chat bebas. Akibatnya:

- Data datang terlambat dan harus diketik ulang sebelum bisa dianalisis.
- Isian sering tidak lengkap atau salah format (luas tanpa satuan, lokasi tidak jelas, foto tidak ada).
- Penyuluh harus memasang dan belajar aplikasi baru, yang sering tidak jalan di ponsel lama atau sinyal lemah.
- Admin tidak bisa melihat kondisi lapangan secara langsung.

### Cara kerja

1. **Rancang.** Admin menyusun *struktur data* (daftar isian dan aturannya: teks, angka, pilihan, foto, lokasi, tanggal) di dashboard, dibantu Agen AI.
2. **Lapor lewat chat.** Fredd menghubungi penyuluh di WhatsApp atau Telegram, menanyakan isian satu pesan per pertanyaan, mengoreksi jawaban yang tidak valid dengan contoh, dan meminta foto atau lokasi. Bila sinyal hilang, jawaban disimpan sebagai draf dan Fredd mengingatkan nanti.
3. **Pantau.** Laporan masuk ke dashboard secara real-time: tabel, peta sebaran, foto bukti, grafik tren, dan ekspor Excel. Admin bisa meninjau laporan dan mengambil alih percakapan bila perlu.

### Pengguna

| Pengguna | Lewat | Yang dilakukan |
|---|---|---|
| Admin, editor struktur, peninjau | Dashboard web | Menyusun struktur data, mengundang penyuluh, menghubungkan kanal, meninjau laporan, mengambil alih percakapan |
| Penyuluh lapangan | WhatsApp / Telegram | Mengisi laporan; tidak perlu memasang aplikasi apa pun |
| Fredd (agen AI) | Server | Menjalankan percakapan, validasi, pengingat, dan ringkasan |
| Pengunjung | Website publik | Membaca landing page dan mendaftar |

### Model bisnis

Fredd dijual sebagai SaaS berlangganan dengan dua jenis workspace:

| Jenis | Paket |
|---|---|
| Perorangan | Gratis, Plus |
| Organisasi | Starter, Growth, Enterprise |

Paket membatasi jumlah anggota, struktur data aktif, dan laporan per bulan; tagihan bulanan atau tahunan. Rincian: [billing-and-plans.md](https://gitlab.com/databiota-fredd/backend/-/blob/development/docs/06-domain-guides/billing-and-plans.md).

### Status pengembangan (14 November 2026)

| Bagian | Status |
|---|---|
| Fondasi backend, frontend, dan infra; Docker Compose | Selesai |
| Format respons API standar, request ID, proteksi CSRF | Selesai |
| Masuk dengan email + kata sandi, keluar, cek sesi | Selesai |
| Website publik dengan SEO: landing, Tentang Kami, Harga, Terra, Nexus, API, Blog, Dokumentasi, Keamanan, Kontak | Selesai (Blog berisi artikel contoh; formulir Kontak belum aktif) |
| Daftar akun, lupa kata sandi, masuk dengan Google | Berikutnya |
| Workspace, anggota, dan peran | Belum |
| Kanal Telegram dan mesin percakapan | Belum |
| Penyusun struktur data, data lapangan, peta, ekspor | Belum |
| WhatsApp Cloud API | Belum (menunggu verifikasi bisnis Meta) |
| Paket dan tagihan | Belum |

Urutan lengkap: [roadmap backend](https://gitlab.com/databiota-fredd/backend/-/blob/development/docs/10-roadmap/roadmap.md) dan [roadmap frontend](https://gitlab.com/databiota-fredd/frontend/-/blob/development/docs/10-roadmap/roadmap.md).

## Gambaran teknis

### Arsitektur

```
Browser ──► Caddy (satu domain)
              ├── /api/*       → FastAPI (api)
              ├── /webhooks/*  → FastAPI (api)   ← WhatsApp, Telegram, pembayaran
              └── /*           → Next.js (website publik + dashboard)

FastAPI ──► PostgreSQL   (data utama)
        ──► Redis        (rate limit, antrean arq, event real-time)
        ──► S3-compatible (foto dan suara, menyusul)
Worker arq ──► WhatsApp Cloud API, Telegram Bot API, LLM (menyusul)
```

Prinsip utama:

- **Satu domain, routing per path.** Cookie sesi dipakai bersama oleh Next.js dan FastAPI tanpa CORS.
- **Next.js tidak pernah mengakses database.** Semua data lewat API FastAPI; tipe TypeScript klien di-generate dari OpenAPI backend.
- **Satu format respons** untuk semua endpoint: `{success, message, data, errors, meta}`.
- **Endpoint dan kode dalam Bahasa Inggris**, teks UI dan pesan ke penyuluh dalam Bahasa Indonesia.

### Repositori

Fredd terdiri dari tiga repo GitLab yang di-clone berdampingan dalam satu folder:

| Repo | Isi |
|---|---|
| [backend](https://gitlab.com/databiota-fredd/backend) | API FastAPI, worker, migrasi database, tes |
| [frontend](https://gitlab.com/databiota-fredd/frontend) | Next.js: website publik (SEO) dan dashboard `/app` |
| [infra](https://gitlab.com/databiota-fredd/infra) | Docker Compose, PostgreSQL, Redis, Caddy; nanti deploy dan backup |

```bash
mkdir fredd && cd fredd
git clone https://gitlab.com/databiota-fredd/backend.git
git clone https://gitlab.com/databiota-fredd/frontend.git
git clone https://gitlab.com/databiota-fredd/infra.git
```

### Tech stack

| Lapisan | Teknologi |
|---|---|
| Backend | Python 3.14, FastAPI, Pydantic v2, SQLAlchemy 2 async + asyncpg, Alembic, uv |
| Frontend | Next.js 16 (App Router), React 19, TypeScript, Tailwind CSS 4, openapi-fetch |
| Data | PostgreSQL 17, Redis 8 |
| Auth | Sesi opaque di cookie HttpOnly, hash argon2 untuk kata sandi; Google OAuth menyusul |
| Kualitas | ruff, pyright, pytest (backend); ESLint, TypeScript strict (frontend) |
| Jalankan dan deploy | Docker Compose, Caddy |
| Kanal chat | Telegram Bot API, WhatsApp Cloud API (menyusul) |

Alasan setiap pilihan tercatat di decision log masing-masing repo.

### Menjalankan

Dua cara, keduanya dari folder induk yang berisi ketiga repo:

| Cara | Untuk | Perintah |
|---|---|---|
| **Native** | Coding sehari-hari dengan hot reload | `docker compose -f infra/docker-compose.yml up -d --wait`, lalu jalankan backend dan frontend dengan perintah di README masing-masing |
| **Docker** | Mencoba seluruh aplikasi tanpa memasang Python/Node | `docker compose -f infra/docker-compose.yml --profile app up -d --build --wait`, lalu buka http://localhost:8080 |

### Kontribusi

- Pesan commit mengikuti [commit-conventions.md](https://gitlab.com/databiota-fredd/backend/-/blob/development/docs/00-governance/commit-conventions.md) (Conventional Commits, Bahasa Inggris).
- Dokumentasi mengikuti [documentation-guidelines.md](https://gitlab.com/databiota-fredd/backend/-/blob/development/docs/00-governance/documentation-guidelines.md).
- File `.env`, hasil build, dan data lapangan tidak pernah di-commit.
- Cabang utama adalah `development` (default di GitLab); semua pekerjaan masuk ke sana. `main` berisi commit awal dan hanya diperbarui lewat merge dari `development` ([aturan cabang](https://gitlab.com/databiota-fredd/backend/-/blob/development/docs/00-governance/commit-conventions.md#cabang)).

## Repo ini: backend

API FastAPI yang menjadi satu-satunya pintu ke database. Melayani dashboard (lewat Next.js), webhook kanal chat dan pembayaran, serta worker yang menjalankan percakapan Fredd.

### Endpoint yang sudah ada

| Method | Path | Fungsi |
|---|---|---|
| `GET` | `/api/v1/health` | Cek API, PostgreSQL, dan Redis; 503 bila salah satu mati |
| `POST` | `/api/v1/auth/login` | Masuk dengan email + kata sandi; mengatur cookie `fredd_session` |
| `POST` | `/api/v1/auth/logout` | Keluar dan mencabut sesi |
| `GET` | `/api/v1/auth/me` | Pengguna yang sedang masuk beserta keanggotaan workspace |

Daftar lengkap (termasuk yang direncanakan): [docs/03-api/endpoints.md](docs/03-api/endpoints.md). Format respons dan katalog kode error: [docs/03-api/api-conventions.md](docs/03-api/api-conventions.md).

### Struktur folder

```
app/
  api/          lapisan HTTP: router per fitur di api/v1/<fitur>, middleware, respons standar, error handler
  modules/      logika per fitur: models, schemas, repository, service, errors (mis. modules/auth)
  core/         konfigurasi, keamanan (argon2, token), Redis, rate limit
  db/           base model, sesi database
  main.py       create_app()
alembic/        migrasi database
scripts/        CLI: create_user, export_openapi
tests/          unit/ dan api/, memakai database <db>_test dan Redis db 15
docs/           dokumentasi teknis (Bahasa Indonesia)
openapi.json    kontrak API untuk frontend
```

Arah import: `api → modules → db/core`. Query hanya di repository, `commit()` hanya di service. Alasan dan aturan lengkap: [docs/02-architecture/system-architecture.md](docs/02-architecture/system-architecture.md#struktur-kode).

### Keamanan yang sudah diterapkan

- Kata sandi di-hash dengan argon2; email yang tidak terdaftar tetap melewati hash tiruan agar waktu respons tidak membocorkan akun mana yang ada.
- Sesi berupa token acak di cookie `HttpOnly`, `SameSite=Lax`, dan `Secure` di luar development; database hanya menyimpan hash SHA-256-nya. Masa berlaku 30 hari, diperpanjang saat dipakai.
- Rate limit login per IP dan per IP + email di Redis.
- Proteksi CSRF dengan memeriksa `Origin`/`Referer` pada request yang mengubah data.
- Setiap respons membawa `request_id` (UUID v7) yang sama dengan header `X-Request-ID` untuk pelacakan.

Rincian: [docs/05-security-and-access](docs/05-security-and-access).

### Menjalankan secara native

Prasyarat: [uv](https://docs.astral.sh/uv/) dan Docker (untuk PostgreSQL dan Redis).

```bash
docker compose -f ../infra/docker-compose.yml up -d --wait
cp .env.example .env
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
uv run python -m scripts.create_user --email you@example.com --name "Your Name"   # meminta kata sandi
```

- Health: http://127.0.0.1:8000/api/v1/health
- OpenAPI (hanya development): http://127.0.0.1:8000/api/docs

PostgreSQL dan Redis dari [infra](https://gitlab.com/databiota-fredd/infra) berjalan di port 5433 dan 6380 agar tidak bentrok dengan instalasi lokal. Pakai `127.0.0.1`, bukan `localhost`: Windows mencoba IPv6 dulu, sedangkan container hanya mendengar IPv4.

### Menjalankan dengan Docker

Dari folder induk (cukup Docker):

```bash
docker compose -f infra/docker-compose.yml --profile app up -d --build --wait
```

API tersedia di belakang Caddy: http://localhost:8080/api/v1/health. Migrasi berjalan otomatis. Image adalah build produksi ([Dockerfile](Dockerfile)); ulangi `--build` setelah kode berubah.

### Pengecekan

```bash
uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest
```

Tes butuh container PostgreSQL dan Redis berjalan. Tes membuat dan memigrasi database `<db>_test` sendiri dan memakai Redis db 15, jadi data development tidak tersentuh.

### Kontrak API dan migrasi

```bash
uv run python -m scripts.export_openapi                     # tulis openapi.json; frontend lalu menjalankan npm run api:types
uv run alembic revision --autogenerate -m "add users table" # migrasi baru
```

`openapi.json` dan migrasi di-commit bersama perubahan yang membuatnya.

### Variabel lingkungan

Contoh di [.env.example](.env.example). Yang utama: `DATABASE_URL`, `REDIS_URL`, `APP_BASE_URL` (asal dashboard, untuk cek CSRF), `ALLOWED_ORIGINS`, `ENVIRONMENT`.

### Dokumentasi

[docs/README.md](docs/README.md) berisi peta 16 folder dokumen. Yang paling sering dibuka:

| Topik | Dokumen |
|---|---|
| Gambaran produk | [01-product-and-scope/product-overview.md](docs/01-product-and-scope/product-overview.md) |
| Arsitektur dan struktur kode | [02-architecture/system-architecture.md](docs/02-architecture/system-architecture.md) |
| Konvensi dan daftar endpoint | [03-api](docs/03-api) |
| Model data | [04-database](docs/04-database) |
| Auth, paket, kanal pesan, glosarium | [06-domain-guides](docs/06-domain-guides) |
| Keputusan teknis | [11-decisions/decision-log.md](docs/11-decisions/decision-log.md) |
