# Changelog

Catatan per fase, terbaru di atas.

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
