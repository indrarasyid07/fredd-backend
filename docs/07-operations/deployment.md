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
| Worker | `taskiq worker app.worker:broker` (bisa beberapa replika) |
| Scheduler cron | `taskiq scheduler app.worker:scheduler` (**tepat satu**) |
| Migrasi (sekali per deploy) | `alembic upgrade head` (membuat extension `postgis`; butuh Postgres dengan PostGIS, mis. image `postgis/postgis:17-3.5` atau Neon) |
| Data rujukan (setelah migrasi `reference_data` pertama, dan saat data wilayah diperbarui) | `python -m scripts.seed reference` |

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
| `STORAGE_ENABLED` | `true` = foto chat ke penyimpanan objek S3-compatible (MinIO/R2/S3); `false` = disk lokal `MEDIA_DIR` (hanya tes & uji cepat) |
| `STORAGE_ENDPOINT_URL`, `STORAGE_BUCKET`, `STORAGE_REGION` | Bucket **privat**; MinIO/R2 memakai endpoint sendiri |
| `STORAGE_ACCESS_KEY`, `STORAGE_SECRET_KEY` | Rahasia; hanya di env server |
| `STORAGE_KEY_PREFIX` | Awalan kunci objek, bawaan `fluctuz/` (bucket boleh dipakai bersama aplikasi lain) |
| `STORAGE_PRESIGN_EXPIRY_SECONDS` | Umur URL bertanda tangan (dipakai mulai Langkah 5.1) |
| `MEDIA_DIR` | Folder media saat `STORAGE_ENABLED=false`, bawaan `var/media` |
| `LLM_*`, `STT_*` | Menunggu pilihan penyedia |
| `ENVIRONMENT` | `development` / `staging` / `production` |

## Waktu dan zona waktu

- Server dan database berjalan di UTC; semua kolom `timestamptz`.
- Jam tenang, jam operasional, dan jadwal dihitung dengan `ZoneInfo(workspace.timezone)` (default `Asia/Jakarta`).
- Cron Taskiq tidak memakai jam lokal: berjalan tiap 5 menit dan memproses yang sudah jatuh tempo.

## Migrasi

`alembic upgrade head` dijalankan sebagai job `migrate` sebelum `api` dan `worker` start (satu kali per deploy, bukan oleh setiap replika). Migrasi yang menghapus kolom atau tabel ditulis dua tahap agar rollback aplikasi tetap aman.

## Observabilitas aplikasi

- Log JSON ke stdout; jangan mencatat token, kredensial kanal, atau isi pesan lengkap.
- `GET /api/v1/health` memeriksa Postgres dan Redis (200 / 503).
- Metrik yang diekspos worker: panjang antrean Taskiq, umur job tertua, pesan keluar gagal per jam.
