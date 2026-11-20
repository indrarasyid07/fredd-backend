## Buat ulang kode gabung dan daftar bot bersama

- `POST /forms/{id}/join-code/rotate` (admin): kode lama dicabut, kode baru dengan pengaturan yang sama; penyuluh yang sudah bergabung tetap terhubung; tercatat di audit log.
- `GET /bots`: bot WhatsApp dan Telegram platform (nama, nomor/username, tautan, tersedia atau belum) untuk layar Kanal dan Bagikan kode.
