# Changelog

Catatan per fase, terbaru di atas.

## 2026-11-18 · Akun demo dengan peran berbeda (Langkah 1.7)

- `scripts.seed demo` kini juga membuat workspace Organisasi "Fluctuz Indonesia" dengan Dina (`admin`), Fajar (`form_editor`), dan Rani (`reviewer`); idempoten lewat `settings.seed_key`. Service `workspaces.seed_organization` (khusus seed).
- 2 tes baru (total 88).

## 2026-11-18 · Nilai kondisi tanaman (keputusan D2)

- Satu set nilai di semua dokumen: `healthy` / `attention` / `infected` (B-052). Glosarium, `data-model.md`, dan contoh di `api-conventions.md` disamakan; kode backend belum memakai nilai ini.

## 2026-11-18 · Penjaga peran (Langkah 1.4)

- `require_role(min_role)` dan alias `ReviewerMember`, `EditorMember`, `AdminMember` di `app/api/deps.py`; peran kurang → `403 forbidden`, workspace lain tetap 404. Antarmuka 1 (TEAM-WORKFLOW) lengkap.
- Mixin `WorkspaceOwned` dan helper `in_workspace()` di `app/db/base.py` untuk tabel milik tenant.
- Fixture tes bersama: `organization`, `add_member()`, `sign_in()`.
- B-006 (sesi, bukan JWT) diterima. 14 tes baru (total 86); `openapi.json` tidak berubah.

## 2026-11-18 · Workspace aktif dan peran nyata (Langkah 1.3)

- `/auth/me` kini mengisi `memberships` (hanya yang disetujui; Perorangan dulu). Bentuk `MeResponse` tidak berubah, jadi `openapi.json` tetap.
- Header `X-Workspace-Id` memilih workspace aktif; dependency `CurrentMember` (`app/api/deps.py`) memvalidasinya. Kode error baru `workspace_required` (400) dan `workspace_not_found` (404) (B-051).
- Tes bisa memakai `TEST_DATABASE_URL` agar tetap di Postgres lokal saat `DATABASE_URL` menunjuk pooler bersama (Neon).
- 10 tes baru (total 72).

## 2026-11-18 · Workspaces dan anggota (Langkah 1.1–1.2)

- Modul `workspaces`: tabel `workspaces` dan `members` (migrasi `773a0a432ada`). Satu workspace Perorangan per user dijaga database; Organisasi tidak dibatasi (B-049, keputusan D13).
- Workspace Perorangan paket Gratis dengan user sebagai `admin` dibuat otomatis saat verifikasi email, login Google, login, dan `create_user` (B-050). Migrasi juga membuatkannya untuk user yang sudah terverifikasi.
- Belum ada endpoint baru; `openapi.json` tidak berubah. `memberships` di `/auth/me` menyusul di Langkah 1.3.
- 11 tes baru (total 63).

## 2026-11-16 · Rancangan dashboard

- Ditambahkan [dashboard.md](../06-domain-guides/dashboard.md): definisi tiap angka, endpoint `summary`, `reports/map`, `reports/{id}`, `reports/count`, ekspor, event SSE, kolom dan tabel tambahan, performa, tes wajib, dan irisan. `GET /reports/export` diganti `POST /reports/exports`. Keputusan B-044 s.d. B-047. Hanya dokumen; belum ada kode.

## 2026-11-16 · Irisan 2-4 auth: daftar, lupa kata sandi, Google

- Endpoint `register`, `verify-email` (+ `resend`), `password/forgot`, `password/reset`, dan `google/login` + `callback`; tabel `auth_tokens` dan `users.organization` (migrasi mengisi `email_verified_at` akun lama).
- Login kini menolak email yang belum terverifikasi (`403 email_not_verified`). Pesan batas percobaan tidak lagi menyebut "masuk".
- Pengirim email SMTP (`core/mail.py`) dan `httpx` pindah dari dependency dev ke dependency utama. Variabel baru: `SMTP_*`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`.
- 21 tes baru (total 48). Layar web 02-06 belum dibangun ([auth.md](../06-domain-guides/auth.md)).

## 2026-11-15 · Rancangan artikel (blog)

- Ditambahkan [articles.md](../06-domain-guides/articles.md): artikel dikelola dari dashboard oleh staf Fluctuz (peran platform), dengan status draf sampai terbit/jadwal, kategori, unggah gambar, revisi, API publik, dan revalidasi web. Endpoint, model data, keamanan, roadmap (Fase 7), glosarium, dan keputusan B-033 s.d. B-038 diperbarui. Hanya dokumen; belum ada kode.

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

- Struktur target `app/` (api, modules, core, db, devtools) + `alembic/`, `fixtures/`, `scripts/` menggantikan `src/fluctuz/` per domain (B-021).
- `api/v1/` dikelompokkan per fitur, bukan per role; alasan, isi folder, aturan lapisan, konvensi Python, penamaan, versi API, devtools, pertimbangan data engineering, dan susunan tes ditulis di `02-architecture/system-architecture.md` (B-022 s.d. B-026).
- Auth guide, API conventions, testing, deployment, seeding, dan agent guide memakai path baru. Kode belum dipindah.

## 2026-11-14 · Rancangan auth dan format respons

- Format respons standar untuk semua endpoint (`success`, `message`, `data`, `errors[]`, `meta`) dan katalog kode error di `03-api/api-conventions.md`.
- Panduan auth (`06-domain-guides/auth.md`): 4 irisan, irisan 1 (login, logout, me) dirinci sampai schema, alur, sesi, rate limit, CSRF, tabel, letak kode, dan tes.
- `02-architecture/system-architecture.md`: struktur folder lengkap, isi folder domain, aturan lapisan, penamaan, cara merangkai router.

## 2026-11-13 · Paket dan desain V.1

- Acuan desain: Login Register V.1, Dashboard V.1, Struktur Data Baru V.1, Penyuluh V.1, Upgrade.
- Halaman Upgrade: Fluctuz menjadi SaaS multi-tenant dengan paket dan kuota; dokumen baru `06-domain-guides/billing-and-plans.md`.
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

- Meninjau canvas desain Fluctuz (57 artboard).
- Menyusun arsitektur, model data, konvensi API (Bahasa Inggris), model keamanan, mesin percakapan, dan kanal.
- Frontend berubah dari usulan React + Vite menjadi Next.js karena ada website publik yang butuh SEO.
- Belum ada kode.
