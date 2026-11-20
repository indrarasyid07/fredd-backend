# Seed Data

Perintah: `uv run python -m scripts.seed <set>`, membaca data dari `fixtures/`. Idempoten (aman dijalankan berulang).

| Set | Isi | Lingkungan |
|---|---|---|
| `reference` | Wilayah **seluruh Indonesia**: 38 provinsi, 514 kab/kota, 7.285 kecamatan dengan kode Kemendagri, centroid, dan batas (MultiPolygon); 25 komoditas dengan alias lokal ("pari" → padi, "sampeu" → ubi kayu); 11 satuan (ha, kg, kuintal, ...). Berkas: `fixtures/reference/` | semua |
| `templates` | Katalog template wizard: 8 sektor (pertanian, peternakan, perikanan, kehutanan, infrastruktur, kesehatan, keuangan, riset) dengan pilihan cepat per sektor, 25 template. Berkas: `fixtures/templates/form_templates.json`; `python -m scripts.seed templates` | semua |
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

Setelah masuk, pindah ke "Fluctuz Indonesia" dari menu akun (bawaannya workspace Perorangan).

**Data lapangan (Langkah 4.1, `scripts/demo_field.py`, fixture `fixtures/demo/field.json`).** Set `demo` juga mengisi "Fluctuz Indonesia" dengan:

- Struktur **"Survei Kondisi Tanaman"** terbit (lokasi, nama petani, komoditas, luas lahan berperan `area` dengan `review_above` 50 ha, kondisi berperan `condition`, foto, catatan). Struktur aktif bernama sama yang sudah ada dipakai ulang bila punya isian lokasi, `condition`, dan `area`.
- **12 penyuluh fiktif** di 12 kecamatan dari 6 kabupaten Jawa Barat (Cianjur, Garut, Sukabumi, Bandung Barat, Subang, Purwakarta), separuh Telegram separuh WhatsApp, nomor `+62 811-0000-0101` s.d. `-0112`, aktif dan terkonfirmasi, masing-masing dengan topik struktur itu.
- **±150 laporan 14 hari terakhir** (lebih banyak di hari-hari terakhir, jam kerja 06.30–17.30 WIB, tidak ada yang di masa depan): titik di sekitar kecamatan penyuluh (wilayah dari titik), kondisi ±58/27/15%, luas 0,2–3 ha dengan sesekali > 50 ha (perlu ditinjau), foto dari 4 contoh di `fixtures/demo/photos/` yang disimpan sekali di `workspaces/<id>/demo/`. Hari ini hanya 9 penyuluh yang melapor, sehingga dashboard punya "belum lapor".

Butuh set `reference` lebih dulu (tanpa wilayah, data lapangan dilewati dengan pesan). Acak tetapi dapat diulang (seed tetap); tanggal relatif terhadap hari ini. Dijalankan ulang: struktur dan penyuluh dipakai lagi, laporan **tidak** ditambah bila penyuluh demo sudah punya laporan.

Data demo tidak boleh berisi nomor HP sungguhan; pakai rentang `+62 811-0000-xxxx`.
