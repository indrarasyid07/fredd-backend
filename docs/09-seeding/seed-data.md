# Seed Data

Perintah: `uv run python -m scripts.seed <set>`, membaca data dari `fixtures/`. Idempoten (aman dijalankan berulang).

| Set | Isi | Lingkungan |
|---|---|---|
| `reference` | Wilayah Jawa Barat (kabupaten/kota, kecamatan), komoditas umum (padi, jagung, cabai, singkong, kopi) beserta alias lokal ("pari" → padi), satuan (ha, kg, ton) | semua |
| `templates` | Template struktur: Survei Kondisi Tanaman, Pantau Hama & Penyakit, Catatan Panen | semua |
| `demo` | Workspace "Fredd Indonesia", 4 anggota (satu per peran), 12 penyuluh di 6 kabupaten, ~150 laporan 14 hari terakhir dengan foto contoh | development, staging |

Sumber data wilayah: kode wilayah Kemendagri (Permendagri terbaru); simpan kode resmi di `reference_data` agar bisa dicocokkan dengan data instansi.

Data demo tidak boleh berisi nomor HP sungguhan; pakai rentang `+62 811-0000-xxxx`.
