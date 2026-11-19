## Data rujukan: wilayah Indonesia dengan PostGIS

- PostGIS + GeoAlchemy2; tabel `reference_data` (wilayah, komoditas, kelompok tani, satuan) dengan centroid dan batas wilayah.
- Seed `reference`: 38 provinsi, 514 kab/kota, 7.285 kecamatan (kode Kemendagri, batas disederhanakan), 25 komoditas dengan alias lokal, 11 satuan.
- `GET /reference-data` (filter `type`, `parent_id`, `level`, `q`, `geometry=true`) dan `GET /reference-data/locate?lat=&lng=` (kecamatan, kab/kota, provinsi dari titik GPS).
- CI memakai image `postgis/postgis:17-3.5`.
