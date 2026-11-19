# Roadmap

Urutan pengerjaan backend. Frontend berjalan paralel (lihat `fredd-frontend/docs/10-roadmap/roadmap.md`).

| Fase | Isi | Selesai bila |
|---|---|---|
| 0. Fondasi | Scaffold FastAPI, Postgres, Alembic, arq, Docker Compose, CI; daftar & masuk (email + Google), workspace Perorangan/Organisasi, anggota, peran | Admin bisa login dan mengundang anggota |
| 1. Telegram + mesin percakapan | Adapter Telegram, webhook, mesin percakapan dengan satu struktur dari seed, draf, pengingat | Penyuluh uji mengisi laporan lengkap di Telegram |
| 2. Struktur data | Penyusun struktur berversi, data rujukan, validasi, uji, pilot, publikasi | Struktur dibuat dari dashboard dan dipakai di Telegram |
| 3. Data lapangan | Laporan, foto ke S3, filter, peta, detail, tindak lanjut, ekspor Excel | Dashboard menampilkan data nyata |
| 4. WhatsApp | Cloud API, Embedded Signup, template, jendela 24 jam | Alur sama berjalan di WhatsApp |
| 5. Pemantauan | Aktivitas agen, SSE, takeover, analitik | Admin bisa ambil alih percakapan |
| 5b. Paket & tagihan | Tabel paket, langganan, kuota, checkout dan webhook penyedia pembayaran | Workspace bisa naik ke Plus/Starter dan kuota ditegakkan |
| 6. Fitur AI & tambahan | STT, insight, Tanya Fluctuz, laporan terjadwal | Sesuai kesepakatan scope |
| 7. Artikel (blog) | Peran platform, artikel dengan status dan jadwal, kategori, unggah gambar, API publik, revalidasi web; berdiri sendiri, bisa paralel setelah Fase 0 ([articles.md](../06-domain-guides/articles.md)) | Staf konten menerbitkan artikel dari dashboard dan muncul di `/blog` |

Proses verifikasi bisnis Meta dimulai di Fase 0 karena bisa memakan waktu berminggu-minggu.
