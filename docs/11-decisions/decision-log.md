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
| B-018 | 2026-11-14 | `argon2-cffi` untuk hash kata sandi | Implementasi argon2id teruji; `hashlib.scrypt` bawaan butuh memori jauh lebih besar per login | Diterima |
| B-019 | 2026-11-14 | Aturan lapisan router → service → models dan folder `core/` tanpa import domain | Endpoint dan struktur folder rapi dan bisa ditebak | Diganti B-021 s.d. B-024 |
| B-020 | 2026-11-14 | Auth dibangun dalam 4 irisan; irisan 1 login + CLI create-user | Login bisa dites tanpa menunggu pengirim email dan OAuth Google | Diterima |
| B-021 | 2026-11-14 | Struktur `app/` berlapis: `api/` (HTTP), `modules/` (logika bisnis per fitur), `core/`, `db/`, `devtools/`, ditambah `alembic/`, `fixtures/`, `scripts/` | Usulan pengguna; logika bisnis tanpa HTTP bisa dipakai bersama oleh API, worker antrean, dan CLI | Diterima |
| B-022 | 2026-11-14 | Di dalam `api/v1/` dikelompokkan per fitur, cermin 1:1 dengan `modules/`; pemisahan per pemanggil hanya di tingkat atas (`api/v1`, `api/webhooks`, `devtools`) | Peran memakai endpoint yang sama dengan izin berbeda dan berubah per paket; penyuluh tidak memakai REST API | Diterima |
| B-023 | 2026-11-14 | `repository.py` wajib untuk semua akses database; `commit()` hanya di service | Query dashboard/analitik dipakai ulang, service bisa dites dengan repository palsu, SQL berat terkumpul | Diterima |
| B-024 | 2026-11-14 | Schema Pydantic request/response di `modules/<fitur>/schemas.py`, tidak ada `schemas.py` di `api/` | Satu sumber bentuk data, tidak dobel | Diterima |
| B-025 | 2026-11-14 | `devtools/` hanya dipasang di development (`/devtools`), dengan tes 404 di staging/produksi | Alat developer tidak boleh terbuka di produksi | Diterima |
| B-026 | 2026-11-14 | Alur data: ingest mentah append-only, normalisasi ke kolom terstruktur, analitik hanya membaca, ekspor lewat job worker | Data lapangan bisa ditelusuri dan diolah ulang; query berat tidak membebani request | Diterima |
| B-027 | 2026-11-14 | `request_id` memakai UUID v7 bawaan Python, bukan ULID | Sama-sama unik dan urut waktu, tanpa dependency tambahan | Diterima |
| B-028 | 2026-11-14 | `AppError` dasar di `core/errors.py`; handler HTTP di `api/errors.py`; cookie sesi di `api/cookies.py` | Modules bisa melempar error tanpa import `api/`; menghindari import melingkar | Diterima |
| B-029 | 2026-11-14 | Python minimal 3.14 | UUID v7 dan sintaks generic baru dipakai; image Docker sudah 3.14 | Diterima |
| B-030 | 2026-11-14 | Tes memakai database `<db>_test` dan Redis db 15 yang dibuat otomatis; tiap tes di-rollback | Data development tidak pernah tersentuh | Diterima |
| B-031 | 2026-11-14 | Pesan commit mengikuti Conventional Commits dalam Bahasa Inggris, tanpa baris atribusi AI/alat dan tanpa referensi ke file desain ([commit-conventions](../00-governance/commit-conventions.md)) | Riwayat yang seragam dan bermakna tanpa bergantung pada alat yang dipakai | Diterima |
| B-032 | 2026-11-15 | `development` jadi cabang utama dan default di GitLab; `main` hanya berisi commit awal dan diperbarui lewat merge dari `development` | Pekerjaan harian terpusat di satu cabang; `main` baru bergerak saat ada rilis yang disengaja | Diterima |
| B-033 | 2026-11-15 | Artikel blog disimpan di database dan dikelola dari dashboard, bukan MDX di repo; Markdown disimpan mentah dan dirender hanya di web | Konten diubah tanpa deploy dan oleh non-developer; Markdown mentah menjaga pindah editor tanpa migrasi data | Diusulkan |
| B-034 | 2026-11-15 | Artikel milik platform: tanpa `workspace_id`, diatur `users.platform_role` (`content_author`, `content_editor`) yang hanya bisa diberikan lewat CLI | Admin workspace pelanggan tidak boleh menerbitkan di blog Fredd; menghindari eskalasi lewat API | Diusulkan |
| B-035 | 2026-11-15 | Aksi status artikel (kirim, terbitkan, jadwalkan, tarik, arsipkan) berupa endpoint terpisah, bukan `PATCH status`; simpan memakai `version` (kunci optimistis) | Tiap transisi punya aturan peran, validasi kelengkapan, dan audit sendiri; dua penyunting tidak diam-diam menimpa | Diusulkan |
| B-036 | 2026-11-15 | Gambar artikel diunggah lewat backend (cek magic bytes, hapus EXIF, ke WebP dua rendisi; tanpa SVG/GIF) dan disimpan di awalan bucket **publik** | Isi berkas harus diperiksa; URL bertanda tangan merusak `og:image` dan cache | Diusulkan |
| B-037 | 2026-11-15 | Setelah terbit/jadwal, backend memanggil rute internal Next.js (`/internal/revalidate`, rahasia bersama, tidak terbuka dari internet) lewat job arq; cache 10 menit sebagai jaring pengaman | Halaman tetap statis dan cepat tetapi tidak basi lama | Diusulkan |
| B-038 | 2026-11-15 | Artikel tidak pernah dihapus permanen lewat API setelah terbit (hanya diarsipkan); slug terkunci setelah terbit pertama | URL yang sudah diindeks tidak boleh hilang atau berganti diam-diam | Diusulkan |
