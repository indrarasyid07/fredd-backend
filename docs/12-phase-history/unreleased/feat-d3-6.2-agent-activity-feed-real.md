## Log Aktivitas Agent dan antrean "Perlu bantuan admin"

- Tabel baru `activity_events`: setiap laporan yang masuk lewat chat dan setiap percakapan yang diteruskan ke admin dicatat dalam transaksi chat yang sama.
- `GET /activity` (peninjau ke atas): log aktivitas terbaru di atas, bisa difilter per jenis kejadian.
- `GET /conversations?status=needs_help` dan `GET /conversations/{id}` (peninjau ke atas): antrean percakapan yang butuh admin beserta alasannya, dan 50 pesan terakhir satu percakapan.
