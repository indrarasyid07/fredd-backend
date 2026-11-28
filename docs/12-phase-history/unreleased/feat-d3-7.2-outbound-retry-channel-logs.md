## Kirim ulang pesan gagal dan log kanal

- Pesan keluar yang gagal karena jaringan atau gangguan Telegram dicoba ulang otomatis 3 kali (jeda 1, 5, 15 menit). Pesan yang mungkin sudah sampai (timeout), bot yang diblokir, dan pesan yang ditolak tidak dicoba ulang.
- `GET /channels/logs` (admin): log pesan masuk dan keluar organisasi tanpa isi pesan, kontak disamarkan; `status=failed` untuk daftar "Susul yang gagal".
- `POST /channels/logs/{id}/resend` (admin): kirim ulang pesan yang gagal.
