## Persetujuan penyuluh

- `GET /extension-workers` (reviewer): daftar penyuluh workspace dengan filter `status` dan cursor; tiap baris menyertakan topik terbaru dan kode gabung yang dipakai.
- `POST /extension-workers/{id}/approve` (admin): penyuluh yang menunggu menjadi aktif dan langsung diberi tahu lewat chat, dengan konfirmasi "Ya, tetap / Bukan, ganti" seperti bergabung otomatis.
- `POST /extension-workers/{id}/block` (admin): permintaan ditolak tanpa pesan ke penyuluh.
- Job baru `conversations.deliver` untuk mengirim pesan yang dibuat di luar pemrosesan chat.
