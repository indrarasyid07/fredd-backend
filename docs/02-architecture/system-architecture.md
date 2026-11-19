# System Architecture

## Komponen

```
Browser ──► Caddy (fluctuz.id)
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

> **Status:** diterapkan sejak irisan 1 auth (keputusan B-021 s.d. B-026). Folder fitur lain dibuat saat fiturnya dikerjakan.

### Pohon folder

```
fredd-backend/
├── app/
│   ├── main.py                      # buat app: middleware, exception handler, pasang router
│   ├── worker.py                    # entry worker arq: daftar job + cron dari modules/*/jobs.py
│   │
│   ├── api/                         # SEMUA yang berbau HTTP; tidak ada logika bisnis
│   │   ├── router.py                # merangkai v1, webhooks, (devtools) ke app
│   │   ├── cookies.py               # set, hapus, baca cookie sesi
│   │   ├── deps.py                  # dependency HTTP bersama: get_db, get_current_user, require_role, require_feature
│   │   ├── responses.py             # ApiResponse[T], ApiErrorResponse, ok()
│   │   ├── errors.py                # exception handler → format respons standar
│   │   ├── middleware/
│   │   │   ├── request_id.py
│   │   │   └── csrf.py
│   │   ├── v1/                      # API untuk dashboard & website (cookie sesi), berversi
│   │   │   ├── router.py            # include semua folder fitur di bawah /api/v1
│   │   │   ├── system/              # /health
│   │   │   ├── auth/                # /auth/*
│   │   │   ├── workspaces/          # /workspace, /members, /audit-logs
│   │   │   ├── billing/             # /billing/*
│   │   │   ├── forms/               # /forms/*, /form-templates
│   │   │   ├── reference_data/      # /reference-data/*
│   │   │   ├── extension_workers/   # /extension-workers/*
│   │   │   ├── reports/             # /reports/*
│   │   │   ├── conversations/       # /conversations/*, /activity, /agent/*
│   │   │   ├── channels/            # /channels/*
│   │   │   ├── analytics/           # /analytics/* (baca saja)
│   │   │   ├── exports/             # /exports/* (job ekspor Excel/PDF)
│   │   │   ├── events/              # /events (SSE)
│   │   │   └── public/              # /public/leads (website tanpa login)
│   │   └── webhooks/                # pihak luar, tanpa versi, auth = tanda tangan
│   │       ├── router.py            # /webhooks/*
│   │       ├── whatsapp.py
│   │       ├── telegram.py
│   │       └── payments.py
│   │
│   ├── modules/                     # logika bisnis per fitur; TIDAK mengenal HTTP
│   │   ├── auth/
│   │   ├── workspaces/
│   │   ├── billing/
│   │   ├── forms/
│   │   ├── reference_data/
│   │   ├── extension_workers/
│   │   ├── reports/
│   │   ├── conversations/           # mesin percakapan
│   │   ├── channels/                # adapter WhatsApp/Telegram (klien keluar)
│   │   ├── analytics/
│   │   ├── exports/
│   │   ├── leads/
│   │   └── ai/                      # LLM, speech-to-text, cek foto
│   │
│   ├── core/                        # dipakai semua lapisan; tanpa logika bisnis, tanpa HTTP
│   │   ├── config.py                # Settings dari env
│   │   ├── errors.py                # AppError dasar; modules melemparnya, api/errors.py mengubahnya jadi respons
│   │   ├── security.py              # hash kata sandi, token
│   │   ├── logging.py               # log JSON + request_id
│   │   ├── redis.py                 # klien Redis bersama
│   │   ├── rate_limit.py
│   │   ├── storage.py               # object storage (S3) saat dipakai
│   │   └── time.py                  # now_utc(), konversi zona waktu workspace
│   │
│   ├── db/
│   │   ├── base.py                  # Base + naming convention + mixin (id UUID v7, timestamps)
│   │   ├── session.py               # engine, sessionmaker, get_session
│   │   └── models.py                # import semua modules/*/models.py (dipakai Alembic autogenerate)
│   │
│   └── devtools/                    # hanya development: Developer Test Console & halaman prototipe
│       ├── router.py                # dipasang di /devtools bila ENVIRONMENT=development
│       └── templates/
│
├── alembic/
│   ├── env.py
│   └── versions/                    # YYYY-MM-DD_<slug>_<rev>.py
├── fixtures/                        # data statis (JSON/CSV): wilayah, komoditas, template, demo
├── scripts/                         # seed.py, create_user.py, export_openapi.py
├── tests/
│   ├── conftest.py
│   ├── unit/                        # cermin app/: modules/, core/ — tanpa database/HTTP
│   ├── api/                         # cermin app/api/: v1/<fitur>/, webhooks/ — lewat httpx + database tes
│   └── integration/                 # alur lintas fitur: webhook → percakapan → laporan → analitik
├── docs/
├── pyproject.toml
└── Dockerfile
```

Folder fitur dibuat saat fiturnya mulai dikerjakan, bukan lebih awal. Pohon di atas adalah peta lengkap tujuannya.

### Kenapa `api/v1/` dibagi per fitur, bukan per role

Pilihan yang dipertimbangkan:

| Opsi | Contoh | Masalah untuk Fluctuz |
|---|---|---|
| Per role | `v1/admin/`, `v1/editor/`, `v1/reviewer/` | Ketiga peran memakai endpoint yang **sama** dengan izin berbeda (`GET /reports` dipakai semua peran). Endpoint harus diduplikasi atau dipisah secara sembarang. Peran juga berubah per paket (Gratis hanya 1 pengguna, Growth punya "beberapa admin") |
| Per aktor | `v1/dashboard/`, `v1/penyuluh/` | Penyuluh **tidak memakai REST API**; mereka lewat WhatsApp/Telegram yang masuk sebagai webhook. Folder `penyuluh/` akan kosong atau salah tempat |
| **Per fitur** (dipilih) | `v1/forms/`, `v1/reports/` | Satu fitur = satu folder, cermin 1:1 dengan `modules/`. Peran ditegakkan lewat dependency, bukan lewat folder |

Pembagian berdasarkan **siapa pemanggilnya** tetap ada, tetapi di tingkat atas, karena di sana kontrak dan cara autentikasinya memang berbeda:

| Folder | Pemanggil | Autentikasi | Versi |
|---|---|---|---|
| `api/v1/` | Frontend (dashboard dan website) | Cookie sesi; `public/` dan sebagian `billing/` tanpa login | Ya, `/api/v1` |
| `api/webhooks/` | Meta, Telegram, penyedia pembayaran | Tanda tangan per penyedia | Tidak, URL didaftarkan ke pihak luar |
| `devtools/` | Developer | Hanya aktif di development | Tidak |

Peran pengguna (`admin`, `form_editor`, `reviewer`) dan fitur paket ditegakkan di endpoint:

```python
@router.post("/{form_id}/publish", dependencies=[Depends(require_role("admin"))])
@router.get("/export", dependencies=[Depends(require_role("form_editor")), Depends(require_feature("export"))])
```

### Isi folder fitur di `api/v1/`

```
api/v1/forms/
├── __init__.py          # from .router import router
├── router.py            # APIRouter fitur; include sub-router bila ada
├── versions.py          # (opsional) sub-resource: /forms/{id}/versions
├── pilots.py            # (opsional) sub-resource: /forms/{id}/pilot
└── deps.py              # (opsional) dependency khusus fitur, mis. get_form_or_404
```

| Aturan | Isi |
|---|---|
| Isi file endpoint | Hanya: baca input, panggil `modules.<fitur>.service`, atur cookie/header, kembalikan `ok(...)` |
| Memecah file | Bila `router.py` melewati ~300 baris atau ada sub-resource yang jelas (`versions`, `rules`, `pilot`), pecah per sub-resource. Satu fitur tetap satu folder |
| Prefix & tag | Ditulis di `api/v1/router.py` saat include, bukan di file fitur, agar peta URL terlihat di satu tempat |
| Schema | Tidak ada `schemas.py` di `api/`; request/response memakai `modules/<fitur>/schemas.py` agar bentuk data tidak dobel |

### Isi folder fitur di `modules/`

```
modules/forms/
├── __init__.py          # __all__ = ["service", "schemas", "errors"]: antarmuka publik modul
├── models.py            # tabel SQLAlchemy
├── schemas.py           # Pydantic: request, response, DTO
├── repository.py        # SEMUA query database modul ini
├── service.py           # logika bisnis + batas transaksi
├── errors.py            # kode error modul (turunan core.errors.AppError) + pesan Indonesia
├── constants.py         # (opsional) enum, batas
├── jobs.py              # (opsional) job/cron arq untuk modul ini
└── engine/              # (opsional) sub-paket untuk logika besar, mis. conversations/engine/
```

| File | Boleh | Tidak boleh |
|---|---|---|
| `models.py` | Definisi tabel, relasi, index | Logika bisnis, query |
| `schemas.py` | Bentuk data dan validasi field | Akses database |
| `repository.py` | Query `select/insert/update` lewat `AsyncSession`, termasuk SQL eksplisit untuk agregasi | `commit()`, logika bisnis, memanggil modul lain |
| `service.py` | Logika bisnis, memanggil repository modul sendiri dan **service** modul lain, `commit()`/`rollback()`, melempar `AppError` | Query langsung, objek HTTP (`Request`, cookie) |
| `jobs.py` | Fungsi job arq tipis yang memanggil service | Logika bisnis sendiri |

**Repository wajib** untuk semua akses database (B-023). Alasannya: query untuk dashboard, peta, dan analitik dipakai ulang di banyak tempat; service bisa dites dengan repository palsu; dan semua SQL yang berat ada di satu tempat yang mudah dioptimasi.

**Batas transaksi di service.** Satu panggilan service = satu unit kerja. Repository tidak pernah `commit()`. Pola:

```python
# app/modules/auth/service.py
async def login(
    db: AsyncSession, email: str, password: str, *, ip: str, user_agent: str | None
) -> tuple[str, MeResponse]:
    user = await repository.get_user_by_email(db, email.strip().lower())
    if user is None or not verify_password(password, user.password_hash):
        raise errors.InvalidCredentials()
    token = new_token()
    await repository.create_session(
        db, user_id=user.id, token_hash=hash_token(token), ip=ip, user_agent=user_agent
    )
    await db.commit()
    return token, await build_me(db, user)
```

### Aturan lapisan dan arah import

```
api/       ──▶ modules/ ──▶ db/, core/
devtools/  ──▶ modules/
worker.py  ──▶ modules/*/jobs.py ──▶ modules/*/service.py
```

| Dari | Boleh import | Tidak boleh import |
|---|---|---|
| `api/` | `modules/*` (service, schemas, errors), `api/*`, `core/` | `modules/*/repository` atau `models` secara langsung |
| `modules/<a>/` | Isi modulnya sendiri, `service`/`schemas` modul lain, `db/`, `core/` | `api/`, `repository`/`models` modul lain |
| `core/`, `db/` | Library pihak ketiga, `core/` | `api/`, `modules/` (kecuali `db/models.py` yang hanya mengumpulkan model untuk Alembic) |

Siklus import antar modul diselesaikan dengan memindahkan bagian bersama ke modul yang lebih dasar. Urutan dasar → atas: `auth` → `workspaces` → `billing` → `forms` / `reference_data` / `extension_workers` → `conversations` / `reports` → `analytics` / `exports`. Modul atas boleh memanggil modul bawah, tidak sebaliknya. Kebutuhan sebaliknya diselesaikan lewat event/job, bukan import.

### Konvensi Python

| Hal | Aturan |
|---|---|
| Paket | `app` (bukan library; `pyproject.toml` memakai `[tool.uv] package = false`) |
| Import | Absolut: `from app.modules.forms import service as forms_service`; tidak memakai import relatif lintas folder |
| Antarmuka modul | `__init__.py` modul mendefinisikan `__all__`; yang tidak ada di `__all__` dianggap internal |
| Ukuran file | Pecah file di atas ~300–500 baris berdasarkan tanggung jawab, bukan sekadar panjang |
| Async | Semua I/O async (`AsyncSession`, httpx, redis.asyncio); library sinkron (openpyxl, Pillow) lewat `run_in_threadpool` atau di worker |
| Tipe | Semua fungsi publik bertipe; pyright mode standar tanpa error |
| Tanggal dan waktu | Selalu timezone-aware UTC (`core.time.now_utc()`); konversi ke zona workspace hanya untuk tampilan dan jadwal |

### Penamaan

| Hal | Aturan | Contoh |
|---|---|---|
| Folder fitur | `snake_case` jamak, sama di `api/v1/` dan `modules/` | `extension_workers`, `reference_data` |
| URL | `kebab-case` jamak | `/api/v1/extension-workers` |
| Schema request | `<Aksi><Resource>Request` | `LoginRequest`, `CreateFormRequest` |
| Schema respons | `<Resource>Response`, bagian kecil `<Resource>Out` | `MeResponse`, `UserOut` |
| Fungsi endpoint | Nama aksi | `login`, `get_me`, `list_reports`, `publish_form` |
| Fungsi service | Kata kerja + objek | `publish_form_version`, `create_session` |
| Fungsi repository | `get_*`, `list_*`, `create_*`, `update_*`, `delete_*`, `count_*` | `get_user_by_email`, `list_reports_for_map` |
| Job arq | `<kata kerja>_<objek>_job` | `process_conversation_job`, `send_reminders_job` |
| Model / tabel | Kelas tunggal PascalCase; tabel jamak `snake_case` | `class Session` → `sessions` |
| Kode error | `snake_case` Inggris; kelas `PascalCase` di `errors.py` | `InvalidCredentials` → `invalid_credentials` |

### Merangkai router

```python
# app/api/v1/router.py
from fastapi import APIRouter
from app.api.v1 import auth, system  # tiap folder fitur mengekspor `router`

router = APIRouter(prefix="/api/v1")
router.include_router(system.router, tags=["system"])
router.include_router(auth.router, prefix="/auth", tags=["auth"])
# router.include_router(forms.router, prefix="/forms", tags=["forms"])


# app/api/router.py
def mount(app: FastAPI, settings: Settings) -> None:
    app.include_router(v1.router)
    app.include_router(webhooks.router, prefix="/webhooks")
    if settings.environment == "development":
        app.include_router(devtools.router, prefix="/devtools", include_in_schema=False)
```

### Versi API

- `api/v1/` dibekukan setelah ada klien di produksi. Perubahan yang merusak kontrak dibuat di `api/v2/` hanya untuk folder fitur yang berubah; `api/v2/router.py` meng-include router v1 untuk fitur yang tidak berubah.
- `modules/` tidak berversi: v1 dan v2 memakai service yang sama, perbedaan bentuk diselesaikan di schema respons.
- Menambah field baru di respons atau endpoint baru **bukan** perubahan yang merusak dan tetap di v1.

### Devtools

- Isi: Developer Test Console (mencoba endpoint dan alur chat penyuluh tanpa WhatsApp/Telegram sungguhan) dan halaman prototipe.
- Dipasang hanya bila `ENVIRONMENT=development`, di `/devtools`, tidak masuk OpenAPI.
- Hanya memanggil `modules/*/service`, tidak punya logika bisnis sendiri.
- Tes `tests/api/test_devtools_disabled.py` memastikan `/devtools` mengembalikan 404 di `staging` dan `production`.

### Pertimbangan data (data engineering)

Fluctuz pada dasarnya pipeline data: pesan chat masuk → jawaban terstruktur → laporan → agregat dashboard dan ekspor. Struktur di atas memisahkan tahap-tahapnya:

| Tahap | Tempat | Aturan |
|---|---|---|
| Ingest mentah | `api/webhooks/` → `modules/conversations` (`messages`) | Disimpan apa adanya sebelum diproses; idempoten per `external_id`; tidak pernah diubah (append-only) |
| Normalisasi | `modules/conversations` → `modules/reports` | Jawaban divalidasi dan disalin ke kolom terstruktur (kondisi, wilayah, lokasi); `form_version_id` dicatat agar data lama tetap bisa ditafsirkan |
| Agregasi | `modules/analytics` | **Hanya membaca**; query agregat di `analytics/repository.py`. Bila berat, pakai materialized view yang di-refresh job (`analytics/jobs.py`) |
| Ekspor | `modules/exports` | Diproses di worker sebagai job (`POST /exports` → id job, `GET /exports/{id}` → status + URL file), bukan di request HTTP |
| Kejadian | `activity_events`, `audit_logs` | Append-only, untuk log aktivitas dan jejak audit |

Konsekuensi untuk kode: modul analitik dan ekspor tidak menulis ke tabel fitur lain; perubahan definisi struktur tidak mengubah laporan lama; dan setiap angka di dashboard bisa ditelusuri ke laporan sumbernya.

### Tes

| Folder | Isi | Butuh |
|---|---|---|
| `tests/unit/modules/<fitur>/` | Service dengan repository palsu, parser, aturan | Tidak ada database |
| `tests/unit/core/` | Hash kata sandi, token, rate limit (Redis palsu) | – |
| `tests/api/v1/<fitur>/` | Endpoint lewat `httpx.AsyncClient`: status, format respons, izin per peran | Postgres + Redis tes |
| `tests/api/webhooks/` | Tanda tangan, idempotensi | Postgres + Redis tes |
| `tests/integration/` | Alur lintas fitur | Postgres + Redis tes |

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
