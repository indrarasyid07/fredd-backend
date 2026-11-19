# Documentation Guidelines

Berlaku untuk `fredd-backend/docs`, `fredd-frontend/docs`, dan `fredd-infra/docs`.

## Bahasa

| Hal | Bahasa |
|---|---|
| Isi dokumen | Bahasa Indonesia |
| Nama file dan folder | Inggris, `kebab-case` |
| Kode, endpoint API, **path URL dan route**, nama tabel/kolom, nama variabel | Inggris |
| Teks yang dilihat pengguna (UI, pesan chat ke penyuluh) | Bahasa Indonesia |
| Istilah domain | Lihat [glosarium](../06-domain-guides/glossary.md) untuk padanan Inggrisnya |

## Path dan endpoint selalu Bahasa Inggris

Semua path, baik endpoint API (`/api/v1/auth/password/forgot`) maupun route halaman web (`/login/forgot-password`), ditulis dalam Bahasa Inggris, `kebab-case`, huruf kecil. Ini berlaku juga untuk tautan yang dikirim lewat email, nama parameter query (`?token=`), dan segmen dinamis.

- Yang Bahasa Indonesia hanya teks yang dilihat pengguna (label, judul, pesan).
- Padanan istilah domain mengikuti [glosarium](../06-domain-guides/glossary.md): `extension-workers` (penyuluh), `forms` (struktur data), `reports` (laporan).
- Contoh: `/login/register`, bukan `/login/daftar`; `/app/incoming-reports`, bukan `/app/laporan-masuk`.
- Path yang sudah dipakai di tautan email atau dipublikasikan tidak diganti diam-diam; catat perubahannya di [decision log](../11-decisions/decision-log.md).

## Struktur

- Nomor folder tetap. Folder baru hanya ditambah lewat keputusan di [decision log](../11-decisions/decision-log.md).
- Satu topik per file. Nama file menjelaskan isinya secara umum (`data-model.md`), bukan status atau waktu (`keputusan-stack-v2.md`).
- Dokumen yang tidak berlaku dipindah ke `99-archive/` dengan catatan pengganti di baris pertama, bukan dihapus.

## Commit

Pesan commit di ketiga repo mengikuti [commit-conventions.md](commit-conventions.md).

## Merawat

- Perubahan arsitektur, stack, atau konvensi dicatat di `11-decisions/decision-log.md`.
- Selesai satu fase, tambahkan entri di `12-phase-history/changelog.md`.
- Diagram ditulis dengan Mermaid di dalam Markdown agar bisa di-diff.
- Versi library tidak ditulis di dokumen. Sumber kebenarannya `pyproject.toml` / `package.json`.
