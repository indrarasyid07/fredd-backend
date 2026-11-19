# Seed Data

Perintah: `uv run python -m scripts.seed <set>`, membaca data dari `fixtures/`. Idempoten (aman dijalankan berulang).

| Set | Isi | Lingkungan |
|---|---|---|
| `reference` | Wilayah **seluruh Indonesia**: 38 provinsi, 514 kab/kota, 7.285 kecamatan dengan kode Kemendagri, centroid, dan batas (MultiPolygon); 25 komoditas dengan alias lokal ("pari" → padi, "sampeu" → ubi kayu); 11 satuan (ha, kg, kuintal, ...). Berkas: `fixtures/reference/` | semua |
| `templates` | Template struktur: Survei Kondisi Tanaman, Pantau Hama & Penyakit, Catatan Panen | semua |
| `demo` | Workspace "Fluctuz Indonesia", 4 anggota (satu per peran), 12 penyuluh di 6 kabupaten, ~150 laporan 14 hari terakhir dengan foto contoh | development, staging |

Sumber data wilayah: [cahyadsn/wilayah_boundaries](https://github.com/cahyadsn/wilayah_boundaries) (MIT, sesuai Kepmendagri No 300.2.2-2430 Tahun 2025), diubah ke `fixtures/reference/regions.geojson.gz` (GeoJSON `[lng, lat]`, 5 desimal, ±3 MB); atribusi dan lisensi di `fixtures/reference/LICENSE-regions.txt`. Kode resmi disimpan di `reference_data.code` agar bisa dicocokkan dengan data instansi. Desa/kelurahan (±84 ribu, ±341 MB mentah) belum termasuk; menyusul lewat skrip impor terpisah.

```bash
uv run python -m scripts.seed reference   # ±20 detik; aman diulang (upsert per kode)
```

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

Setelah masuk, pindah ke "Fluctuz Indonesia" dari menu akun (bawaannya workspace Perorangan). Set `templates`, serta penyuluh dan laporan di `demo` (Langkah 4.1), belum dibuat.

Data demo tidak boleh berisi nomor HP sungguhan; pakai rentang `+62 811-0000-xxxx`.
