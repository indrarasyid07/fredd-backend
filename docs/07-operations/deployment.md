# Deployment

Layanan, reverse proxy, database, backup, dan observabilitas diatur di [fredd-infra/docs](https://github.com/indrarasyid07/fredd-infra/blob/development/docs/README.md):

- Topologi dan layanan: [infrastructure-architecture.md](https://github.com/indrarasyid07/fredd-infra/blob/development/docs/02-architecture/infrastructure-architecture.md)
- Deploy, Caddy, observabilitas: [infra deployment](https://github.com/indrarasyid07/fredd-infra/blob/development/docs/07-operations/deployment.md)
- Postgres, Redis, backup, restore: [database-operations.md](https://github.com/indrarasyid07/fredd-infra/blob/development/docs/04-database/database-operations.md)
- Development lokal: [local-development.md](https://github.com/indrarasyid07/fredd-infra/blob/development/docs/06-domain-guides/local-development.md)

Dokumen ini hanya berisi hal yang khusus aplikasi backend.

## Proses


| Proses | Perintah |
|---|---|
| API | `uvicorn app.main:app --proxy-headers` |
| Worker | `arq app.worker.WorkerSettings` |
| Migrasi (sekali per deploy) | `alembic upgrade head` |

## Image Docker

[`Dockerfile`](../../Dockerfile): `python:3.14-slim` + uv 0.13.7, dependensi dari `uv.lock` (`uv sync --locked --no-dev`), user non-root `fluctuz`, health check ke `/api/v1/health`. `.dockerignore` mengecualikan `.env`, `.venv`, cache, `docs/`, dan `tests/`.

Satu image dipakai untuk `api` dan `migrate` (dan `worker` nanti) dengan command berbeda. Env diberikan oleh compose, bukan file `.env` di dalam image. Menjalankan secara lokal: lihat [local-development](https://github.com/indrarasyid07/fredd-infra/blob/development/docs/06-domain-guides/local-development.md).

## Konfigurasi (env)

| Variabel | Keterangan |
|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://…` |
| `REDIS_URL` | |
| `APP_BASE_URL` | `https://fluctuz.id` (untuk Origin check, callback OAuth, webhook) |
| `ALLOWED_ORIGINS` | Origin tambahan yang lolos cek CSRF, dipisah koma; development: `http://localhost:3000,http://localhost:8080` |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | |
| `ENCRYPTION_KEYS` | Daftar kunci Fernet dipisah koma, terbaru di depan |
| `META_APP_ID`, `META_APP_SECRET`, `META_VERIFY_TOKEN` | WhatsApp Cloud API |
| `S3_ENDPOINT`, `S3_BUCKET`, `S3_ACCESS_KEY`, `S3_SECRET_KEY` | |
| `LLM_*`, `STT_*` | Menunggu pilihan penyedia |
| `ENVIRONMENT` | `development` / `staging` / `production` |

## Waktu dan zona waktu

- Server dan database berjalan di UTC; semua kolom `timestamptz`.
- Jam tenang, jam operasional, dan jadwal dihitung dengan `ZoneInfo(workspace.timezone)` (default `Asia/Jakarta`).
- Cron arq tidak memakai jam lokal: berjalan tiap 5 menit dan memproses yang sudah jatuh tempo.

## Migrasi

`alembic upgrade head` dijalankan sebagai job `migrate` sebelum `api` dan `worker` start (satu kali per deploy, bukan oleh setiap replika). Migrasi yang menghapus kolom atau tabel ditulis dua tahap agar rollback aplikasi tetap aman.

## Observabilitas aplikasi

- Log JSON ke stdout; jangan mencatat token, kredensial kanal, atau isi pesan lengkap.
- `GET /api/v1/health` memeriksa Postgres dan Redis (200 / 503).
- Metrik yang diekspos worker: panjang antrean arq, umur job tertua, pesan keluar gagal per jam.
