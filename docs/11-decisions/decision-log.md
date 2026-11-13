# Decision Log

Format: satu baris per keputusan; keputusan yang diganti ditandai, tidak dihapus.

| No | Tanggal | Keputusan | Alasan | Status |
|---|---|---|---|---|
| B-001 | 2026-11-13 | Backend FastAPI (Python) | Ditetapkan klien/tim; async, OpenAPI otomatis untuk klien TypeScript | Diterima |
| B-002 | 2026-11-13 | PostgreSQL + SQLAlchemy 2.0 async + Alembic | JSONB untuk struktur berversi dan jawaban; transaksi kuat | Diterima |
| B-003 | 2026-11-13 | Redis + arq untuk antrean dan cron | Semua job berupa I/O; arq asyncio-native dan memakai kode yang sama dengan API. Celery: dukungan async lemah | Diusulkan |
| B-004 | 2026-11-13 | WhatsApp Business Cloud API resmi, bukan QR / perangkat tertaut | Jalur tidak resmi melanggar ToS dan berisiko nomor diblokir; tombol, daftar, template hanya stabil di API resmi | Diusulkan, menunggu persetujuan biaya |
| B-005 | 2026-11-13 | Adapter kanal tipis di atas httpx, tanpa aiogram / python-telegram-bot | Mesin percakapan harus sama untuk dua kanal; framework bot membawa FSM sendiri | Diusulkan |
| B-006 | 2026-11-13 | Sesi server-side + cookie httpOnly, bukan JWT | Halaman Keamanan butuh sesi yang bisa dicabut | Diusulkan |
| B-007 | 2026-11-13 | Tanpa PostGIS di v1 | Wilayah sudah diketahui dari penyuluh; lat/lng biasa cukup. Tambah bila perlu kueri spasial | Diusulkan |
| B-008 | 2026-11-13 | Endpoint, JSON, tabel, kode dalam Bahasa Inggris; UI dan chat Bahasa Indonesia | Konsisten dengan bahasa kode dan tooling; glosarium menjaga istilah domain | Diterima |
| B-009 | 2026-11-13 | Satu job antrean per percakapan | Menjamin urutan pesan tanpa kunci terpisah | Diusulkan |
| B-010 | 2026-11-13 | Satu domain berbasis path (`/api` → FastAPI, sisanya → Next.js) | Cookie sesi bersama tanpa CORS | Diusulkan |
| B-011 | 2026-11-13 | Prefix API `/api/v1` | Murah sekarang, mahal ditambahkan belakangan | Diusulkan |
| B-012 | 2026-11-13 | Multi-tenant SaaS: workspace Perorangan/Organisasi dengan paket dan kuota | Halaman Upgrade di desain | Diterima |
| B-013 | 2026-11-13 | Masuk dengan email + kata sandi (argon2id) dan Google; wajib SSO opsi per workspace | Pendaftaran mandiri untuk paket Gratis | Diusulkan |
| B-014 | 2026-11-13 | Checkout hosted penyedia pembayaran; status langganan hanya dari webhook bertanda tangan | Tidak menyimpan data kartu; redirect browser bisa dipalsukan | Diusulkan |
| B-015 | 2026-11-13 | Laporan di atas kuota tetap disimpan, ditandai `over_quota` | Data lapangan tidak boleh hilang | Diusulkan |
| B-016 | 2026-11-14 | Satu format respons untuk semua endpoint JSON: `success`, `message`, `data`, `errors[]`, `meta` | Frontend membaca satu pola; error per field bisa ditempel ke input | Diterima |
| B-017 | 2026-11-14 | Tidak memakai `204 No Content`; aksi tanpa data → `200` + `data: null` | 204 tidak boleh punya body, jadi tidak bisa memakai format standar | Diterima |
| B-018 | 2026-11-14 | `argon2-cffi` untuk hash kata sandi | Implementasi argon2id teruji; `hashlib.scrypt` bawaan butuh memori jauh lebih besar per login | Diusulkan |
| B-019 | 2026-11-14 | Aturan lapisan router → service → models dan folder `core/` tanpa import domain | Endpoint dan struktur folder rapi dan bisa ditebak | Diterima |
| B-020 | 2026-11-14 | Auth dibangun dalam 4 irisan; irisan 1 login + CLI create-user | Login bisa dites tanpa menunggu pengirim email dan OAuth Google | Diterima |
