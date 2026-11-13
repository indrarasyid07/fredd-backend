# Agent Guidelines (Backend)

Untuk AI coding agent (Claude Code, Cursor, dll.) yang bekerja di `backend/`.

## Baca dulu

1. [system-architecture.md](../02-architecture/system-architecture.md)
2. [api-conventions.md](../03-api/api-conventions.md)
3. [glossary.md](../06-domain-guides/glossary.md)
4. Dokumen domain yang relevan dengan tugas.

## Aturan

- Nama kode, endpoint, tabel, dan kolom dalam Bahasa Inggris sesuai glosarium. Teks untuk pengguna dalam Bahasa Indonesia.
- Ikuti struktur domain dan [aturan lapisan](../02-architecture/system-architecture.md#aturan-lapisan): `router.py` → `service.py` → `models.py`. Router tidak query database langsung; service tidak mengenal objek HTTP; `core/` tidak import domain.
- Semua respons JSON memakai [format standar](../03-api/api-conventions.md#format-respons) lewat `ok()` dan `AppError`; jangan membuat bentuk respons sendiri dan jangan memakai `204`.
- Kode error baru ditambahkan ke katalog di `api-conventions.md` (bila umum) atau dokumen domainnya, dengan pesan Bahasa Indonesia di `core/errors.py`.
- Async di seluruh jalur I/O. Library sinkron dijalankan lewat `run_in_threadpool`.
- Setiap query data tenant difilter `workspace_id` dari sesi.
- Jangan menambah dependency tanpa mencatatnya di [decision log](../11-decisions/decision-log.md).
- Perubahan skema = migrasi Alembic baru; jangan mengubah migrasi yang sudah di-merge.
- Logika baru yang berisiko (parser, aturan, auth, penulisan data) disertai tes.
- Jangan pernah mencatat token, kredensial kanal, atau isi pesan lengkap ke log.
- Jalankan `ruff check`, `ruff format`, `pyright`, `pytest` sebelum selesai.
