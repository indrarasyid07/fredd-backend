## Foto dan lokasi dari chat

- Foto, video, dan berkas yang dikirim penyuluh disalin ke penyimpanan Fluctuz (MinIO/S3, atau disk lokal saat pengembangan) di bawah organisasi topiknya; laporan menyimpan rujukan berkas itu, bukan rujukan Telegram.
- Berkas diperiksa sebelum disimpan: maksimal 20 MB dan isinya harus benar-benar foto (JPEG, PNG, WebP). Selain itu bot meminta kirim ulang.
- Pesan dari chat yang belum bergabung tidak pernah diunduh.
- Foto (atau album) yang dikirim sebelum `mulai` memulai laporan dan menjadi jawaban isian foto pertama; dengan beberapa topik, foto disimpan dulu sampai topik dipilih.
- Foto yang dikirim saat bot menanyakan isian teks memunculkan pilihan [Lanjutkan] [Mulai ulang].
