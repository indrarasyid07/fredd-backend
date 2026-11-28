## Peta dan dashboard per sektor

- `GET /dashboard/map`: kabupaten berwarna (ambang kondisi atau nilai terbanyak isian pilihan), ≤ 2.000 titik terbaru, legenda; sektor kesehatan hanya per wilayah (≥ 5 laporan).
- `GET /dashboard/boundaries`: batas kabupaten yang disederhanakan, di-cache sehari.
- `GET /dashboard/forms/{id}` membawa sektor, templat, ada/tidaknya isian lokasi, dan KPI struktur (periode sebelumnya, penyuluh melapor, kelengkapan, perlu ditinjau).
