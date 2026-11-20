## Daftar dan detail laporan

- `GET /reports`: daftar laporan terbaru dahulu dengan cursor dan filter struktur, penyuluh, wilayah, kondisi (termasuk "tanpa kondisi"), perlu tinjauan, dan rentang waktu.
- `GET /reports/{id}`: semua isian dengan label dari versi struktur saat laporan dibuat (laporan lama tetap terbaca setelah struktur diubah), teks jawaban siap tampil, lokasi, wilayah, alasan perlu ditinjau, dan foto dengan tautan sementara dari penyimpanan.
