# Seed Data

Perintah: `uv run python -m scripts.seed <set>`, membaca data dari `fixtures/`. Idempoten (aman dijalankan berulang).

| Set | Isi | Lingkungan |
|---|---|---|
| `reference` | Wilayah Jawa Barat (kabupaten/kota, kecamatan), komoditas umum (padi, jagung, cabai, singkong, kopi) beserta alias lokal ("pari" → padi), satuan (ha, kg, ton) | semua |
| `templates` | Template struktur: Survei Kondisi Tanaman, Pantau Hama & Penyakit, Catatan Panen | semua |
| `demo` | Workspace "Fluctuz Indonesia", 4 anggota (satu per peran), 12 penyuluh di 6 kabupaten, ~150 laporan 14 hari terakhir dengan foto contoh | development, staging |

Sumber data wilayah: kode wilayah Kemendagri (Permendagri terbaru); simpan kode resmi di `reference_data` agar bisa dicocokkan dengan data instansi.

## Status

Baru set `demo` bagian akun dan workspace yang ada: `uv run python -m scripts.seed demo` membuat tiga user dari `fixtures/demo/users.json` (hanya development; kata sandi dipublikasikan di berkas itu), masing-masing dengan workspace Perorangan, lalu memasukkan mereka ke workspace Organisasi **"Fluctuz Indonesia"** dengan peran berbeda (Langkah 1.7). Workspace itu dikenali lewat `settings.seed_key = "demo"`, jadi menjalankan ulang tidak membuat duplikat dan mengembalikan peran ke nilai di fixture.

| Email | Nama | Kata sandi |
|---|---|---|
| `dina@contoh.id` | Dina Admin | `rahasia123` |
| `fajar@contoh.id` | Fajar Editor Form | `rahasia123` |
| `rani@contoh.id` | Rani Reviewer | `rahasia123` |

| Akun | Peran di "Fluctuz Indonesia" |
|---|---|
| `dina@contoh.id` | `admin` |
| `fajar@contoh.id` | `form_editor` |
| `rani@contoh.id` | `reviewer` |

Setelah masuk, pindah ke "Fluctuz Indonesia" dari menu akun (bawaannya workspace Perorangan). Set `reference` dan `templates`, serta penyuluh dan laporan di `demo` (Langkah 4.1), belum dibuat.

Data demo tidak boleh berisi nomor HP sungguhan; pakai rentang `+62 811-0000-xxxx`.
