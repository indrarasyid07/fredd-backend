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

Satu folder per domain bisnis, dengan nama file yang sama di setiap domain. Folder domain baru dibuat saat domainnya mulai dikerjakan, bukan lebih awal.

```
backend/
├── src/fredd/
│   ├── main.py              # buat app: middleware, exception handler, router /api/v1
│   ├── config.py            # Settings (pydantic-settings, dari env)
│   ├── database.py          # engine, Base (naming convention), get_session
│   ├── cli.py               # perintah CLI (mis. create-user)
│   ├── worker.py            # WorkerSettings arq: job + cron (saat antrean dipakai)
│   ├── core/                # lintas domain, tanpa logika bisnis
│   │   ├── responses.py     # ApiResponse[T], ApiErrorResponse, ok()
│   │   ├── errors.py        # AppError + semua exception handler
│   │   ├── request_id.py    # middleware X-Request-ID
│   │   ├── csrf.py          # middleware cek Origin
│   │   ├── rate_limit.py    # rate limit berbasis Redis
│   │   ├── security.py      # hash kata sandi, token
│   │   └── redis.py         # klien Redis bersama
│   ├── system/              # health, info versi
│   ├── auth/                # login, sesi, daftar, reset, Google
│   ├── workspaces/          # workspace, anggota, undangan anggota, audit log
│   ├── billing/             # paket, langganan, kuota, pembayaran
│   ├── forms/               # struktur data, versi, isian, aturan, pilot
│   ├── reference_data/      # wilayah, komoditas, kelompok tani, satuan
│   ├── extension_workers/   # penyuluh, undangan, verifikasi
│   ├── channels/            # adapter whatsapp.py, telegram.py, router webhook
│   ├── conversations/       # mesin percakapan, draf, ambil alih
│   ├── reports/             # laporan, foto, tindak lanjut, ekspor
│   ├── analytics/           # agregat dashboard
│   ├── ai/                  # LLM, speech-to-text, cek foto
│   └── events/              # SSE + Redis pub/sub
├── migrations/
│   └── versions/            # YYYY-MM-DD_<slug>_<rev>.py
└── tests/
    ├── conftest.py          # client tes, database per tes (rollback), user/sesi siap pakai
    ├── core/                # tes format respons, error handler, CSRF
    └── <domain>/            # satu folder per domain, cermin struktur src
```

Padanan nama Indonesia ↔ Inggris ada di [glosarium](../06-domain-guides/glossary.md).

### Isi folder domain

| File | Isi | Wajib |
|---|---|---|
| `router.py` | Endpoint FastAPI (`APIRouter`) | Bila domain punya endpoint |
| `schemas.py` | Model Pydantic untuk request dan respons | Bila ada router |
| `models.py` | Model SQLAlchemy (tabel) | Bila domain punya tabel |
| `service.py` | Logika bisnis dan query | Ya |
| `dependencies.py` | Dependency FastAPI yang dipakai domain lain (mis. `get_current_user`) | Hanya bila ada |
| `constants.py` | Nilai tetap domain (enum, batas) | Hanya bila ada |

Domain yang membesar boleh memecah `service.py` per subtopik (mis. `forms/versions.py`, `forms/rules.py`), tetapi router tetap satu per domain.

### Aturan lapisan

| Lapisan | Boleh | Tidak boleh |
|---|---|---|
| `router.py` | Membaca request (body, query, cookie, header), memanggil `service`, mengatur cookie/header, membungkus hasil dengan `ok()` | Query database, logika bisnis, menyusun format respons sendiri |
| `service.py` | Logika bisnis, query lewat `AsyncSession`, memanggil service domain lain, melempar `AppError` | Mengenal objek HTTP (`Request`, `Response`, cookie) |
| `models.py` | Definisi tabel dan relasi | Logika bisnis |
| `schemas.py` | Bentuk input/output API, validasi field | Akses database |
| `dependencies.py` | Mengambil sesi, user, workspace dari request | Logika bisnis selain otorisasi |
| `core/` | Utilitas lintas domain | Import dari folder domain mana pun |

Arah import: `router → service → models`; domain boleh memakai `service` atau `dependencies` domain lain, tidak boleh memakai `router` domain lain. Siklus import antar domain diselesaikan dengan memindahkan bagian bersama ke domain yang lebih dasar (mis. `auth` → `workspaces`, bukan sebaliknya).

### Penamaan

| Hal | Aturan | Contoh |
|---|---|---|
| Schema request | `<Aksi><Resource>Request` | `LoginRequest`, `CreateFormRequest` |
| Schema respons / bagian respons | `<Resource>Response`, `<Resource>Out` | `MeResponse`, `UserOut` |
| Fungsi router | Nama aksi, `snake_case` | `login`, `get_me`, `list_reports`, `publish_form` |
| Fungsi service | Kata kerja + objek | `authenticate`, `create_session`, `publish_form_version` |
| Model SQLAlchemy | Tunggal, PascalCase; tabel jamak `snake_case` | `class Session` → `sessions` |
| Kode error | `snake_case` Inggris | `invalid_credentials` |
| Pesan untuk pengguna | Bahasa Indonesia, kalimat lengkap dengan titik | "Email atau kata sandi salah." |

### Merangkai router

```python
# main.py
api = APIRouter(prefix="/api/v1")
api.include_router(system_router)                                    # /api/v1/health
api.include_router(auth_router, prefix="/auth", tags=["auth"])       # /api/v1/auth/...
api.include_router(forms_router, prefix="/forms", tags=["forms"])    # /api/v1/forms/...

app.include_router(api)
app.include_router(webhooks_router, prefix="/webhooks")              # tanpa /api/v1
```

Prefix dan tag ditulis di `main.py`, bukan di router domain, supaya seluruh peta URL terlihat di satu tempat.

### Contoh endpoint

```python
# auth/router.py
@router.post("/login", response_model=ApiResponse[MeResponse],
             responses={401: {"model": ApiErrorResponse}, 429: {"model": ApiErrorResponse}})
async def login(body: LoginRequest, request: Request, response: Response,
                db: AsyncSession = Depends(get_session)) -> ApiResponse[MeResponse]:
    token, me = await service.login(db, body.email, body.password,
                                    ip=client_ip(request), user_agent=request.headers.get("user-agent"))
    set_session_cookie(response, token)
    return ok(me, message="Berhasil masuk.")
```

Format respons dan katalog error: [api-conventions.md](../03-api/api-conventions.md#format-respons).

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
