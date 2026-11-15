# Changelog

Catatan per fase, terbaru di atas.

## 2026-11-15 · Cabang

- `development` menjadi cabang utama dan default di GitLab; `main` berisi commit awal dan diperbarui lewat merge dari `development` ([commit-conventions](../00-governance/commit-conventions.md#cabang)). Semua tautan lintas repo kini mengarah ke `development`.

## 2026-11-14 · Standar commit

- `00-governance/commit-conventions.md`: format, type, scope, aturan subject/body/footer, larangan (atribusi AI, referensi file desain, rahasia, data pribadi), dan contoh.

## 2026-11-14 · Irisan 1 auth: login

- Scaffold dipindah ke struktur `app/` (api, modules, core, db) dan `alembic/`; Python minimal 3.14.
- Format respons standar, handler error, middleware request ID dan CSRF.
- Modul auth: tabel `users` dan `sessions`, login, logout, `/me`, rate limit Redis, argon2id; skrip `create_user` dan `export_openapi`.
- 27 tes (unit, API, format respons, CSRF); diuji di browser dan mode Docker.

## 2026-11-14 · Struktur folder backend

- Struktur target `app/` (api, modules, core, db, devtools) + `alembic/`, `fixtures/`, `scripts/` menggantikan `src/fredd/` per domain (B-021).
- `api/v1/` dikelompokkan per fitur, bukan per role; alasan, isi folder, aturan lapisan, konvensi Python, penamaan, versi API, devtools, pertimbangan data engineering, dan susunan tes ditulis di `02-architecture/system-architecture.md` (B-022 s.d. B-026).
- Auth guide, API conventions, testing, deployment, seeding, dan agent guide memakai path baru. Kode belum dipindah.

## 2026-11-14 · Rancangan auth dan format respons

- Format respons standar untuk semua endpoint (`success`, `message`, `data`, `errors[]`, `meta`) dan katalog kode error di `03-api/api-conventions.md`.
- Panduan auth (`06-domain-guides/auth.md`): 4 irisan, irisan 1 (login, logout, me) dirinci sampai schema, alur, sesi, rate limit, CSRF, tabel, letak kode, dan tes.
- `02-architecture/system-architecture.md`: struktur folder lengkap, isi folder domain, aturan lapisan, penamaan, cara merangkai router.

## 2026-11-13 · Paket dan desain V.1

- Acuan desain: Login Register V.1, Dashboard V.1, Struktur Data Baru V.1, Penyuluh V.1, Upgrade.
- Halaman Upgrade: Fredd menjadi SaaS multi-tenant dengan paket dan kuota; dokumen baru `06-domain-guides/billing-and-plans.md`.
- Auth: email + kata sandi ditambah di samping Google; model data, endpoint, model keamanan, glosarium, dan roadmap diperbarui.

## 2026-11-13 · Docker

- `Dockerfile` dan `.dockerignore`; backend bisa dijalankan native (uv) atau sebagai image lewat `infra` profile `app`.

## 2026-11-13 · Folder infra

- Compose dev pindah ke `infra/docker-compose.yml`; bagian layanan, Caddy, backup, dan observabilitas di `07-operations` dipindah ke `infra/docs`.

## 2026-11-13 · Scaffold

- FastAPI (Python 3.14 lokal, `requires-python >=3.13`), uv, SQLAlchemy async, Alembic (template async), pydantic-settings.
- `GET /api/v1/health` memeriksa Postgres dan Redis; satu tes, ruff, pyright lulus.
- Docker Compose dev: Postgres 17 (5433), Redis 8 (6380).
- Belum: auth Google, arq worker, domain modul, compose produksi.

## 2026-11-13 · Perencanaan

- Meninjau canvas desain Fredd (57 artboard).
- Menyusun arsitektur, model data, konvensi API (Bahasa Inggris), model keamanan, mesin percakapan, dan kanal.
- Frontend berubah dari usulan React + Vite menjadi Next.js karena ada website publik yang butuh SEO.
- Belum ada kode.
