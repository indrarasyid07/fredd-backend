# System Architecture

## Komponen

```
Browser ──► Caddy (fredd.id)
              ├── /api/*       → FastAPI (api)
              ├── /webhooks/*  → FastAPI (api)
              └── /*           → Next.js (website publik + dashboard)

FastAPI api ──► PostgreSQL
            ──► Redis (antrean arq, pub/sub event)
            ──► Object storage S3-compatible (foto, suara)
arq worker  ──► sama seperti api + WhatsApp Cloud API, Telegram Bot API, LLM
```

Satu domain, berbasis path. Cookie sesi dipakai bersama oleh Next.js dan FastAPI tanpa CORS. Next.js tidak pernah mengakses database; semua data lewat FastAPI.

## Tech stack

| Bagian | Pilihan | Alasan singkat |
|---|---|---|
| Runtime | Python 3.13+ (dev memakai 3.14), `uv` | Cepat, lockfile tunggal |
| Framework | FastAPI + Pydantic v2 | Async, OpenAPI otomatis untuk klien TypeScript |
| Database | PostgreSQL 17 | JSONB untuk struktur dan jawaban, transaksi kuat |
| ORM & migrasi | SQLAlchemy 2.0 async + asyncpg, Alembic | Standar ekosistem |
| Antrean & cron | Redis + arq | Asyncio-native, cocok untuk beban I/O (kirim pesan, LLM) |
| Penyimpanan berkas | S3-compatible (Cloudflare R2 / MinIO) | Murah, URL bertanda tangan |
| HTTP keluar | httpx | Satu klien untuk WhatsApp, Telegram, LLM |
| Realtime | Server-Sent Events + Redis pub/sub | Satu arah sudah cukup; balasan admin lewat POST |
| Auth | Google OAuth (authlib), sesi di Postgres | Sesi bisa dicabut dari halaman Keamanan |
| Ekspor | openpyxl | Excel dari Data Lapangan |
| Deploy | Docker Compose | `api`, `worker`, `web`, `postgres`, `redis`, `caddy` |

Alasan lengkap tiap pilihan ada di [decision log](../11-decisions/decision-log.md).

## Struktur kode

```
backend/
├── src/fredd/
│   ├── main.py
│   ├── config.py          # pydantic-settings
│   ├── database.py
│   ├── worker.py          # WorkerSettings arq: job + cron
│   ├── auth/              # Google OAuth, sessions, roles
│   ├── workspaces/        # settings, members, member invites, audit log
│   ├── forms/             # forms (struktur data), versions, fields, rules, pilots
│   ├── reference_data/    # regions, commodities, farmer groups, units
│   ├── extension_workers/ # penyuluh, invites, phone/chat ID verification
│   ├── channels/          # whatsapp.py, telegram.py, webhooks router
│   ├── conversations/     # conversation engine, drafts, takeover
│   ├── reports/           # field reports, photos, follow-ups, export
│   ├── analytics/         # dashboard aggregates
│   ├── ai/                # LLM, speech-to-text, photo checks
│   └── events/            # SSE + Redis pub/sub
├── migrations/
├── tests/
└── pyproject.toml
```

Setiap domain berisi `router.py`, `schemas.py`, `models.py`, `service.py`, `dependencies.py`. Router tidak menyentuh database langsung; logika ada di `service.py`. Padanan nama Indonesia ↔ Inggris ada di [glosarium](../06-domain-guides/glossary.md).

## Alur pesan masuk

```
Webhook WA/TG ──► POST /webhooks/{channel}
                   1. verifikasi tanda tangan
                   2. parse: hanya pesan masuk; status "failed" langsung update tabel messages
                   3. simpan pesan mentah (unik per external_id, jadi aman dikirim ulang)
                   4. enqueue job process_conversation dengan _job_id="conversation:{id}"
                   5. balas 200 segera
                          │
worker arq ◄──────────────┘
   process_conversation(id):
   ├─ ambil semua pesan belum diproses, urut menurut waktu kanal
   ├─ media → unduh ke S3, cek buram, transkripsi suara
   ├─ diambil alih admin? tandai diproses, jangan balas
   ├─ mesin percakapan: validasi → aturan → pertanyaan berikutnya
   ├─ tulis activity_event + publish ke Redis events:{workspace_id}
   ├─ baca ulang status takeover tepat sebelum mengirim
   └─ kirim lewat adapter kanal (template bila jendela 24 jam WA sudah lewat)
```

Satu job per percakapan (bukan per pesan) menjamin pesan diproses berurutan tanpa kunci terpisah. Pesan yang masuk saat job berjalan diambil di putaran berikutnya karena job dijadwalkan ulang setelah selesai bila masih ada pesan baru.

Detail mesin percakapan: [conversation-engine.md](../06-domain-guides/conversation-engine.md). Detail kanal: [messaging-channels.md](../06-domain-guides/messaging-channels.md).

## Pekerjaan terjadwal (cron arq, tiap 5 menit)

- Kirim pengingat draf yang jatuh tempo (di luar jam tenang, zona waktu workspace).
- Kirim ulang pesan keluar yang gagal (maks 3 kali, backoff).
- Hapus data melewati masa retensi (percakapan 12 bulan, foto 24 bulan).
