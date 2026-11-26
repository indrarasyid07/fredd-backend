## Struktur data aktif bisa diubah

- `POST /forms/{id}/draft` (form_editor): membuka struktur aktif untuk diubah. Dibuat draf versi baru (nomor berikutnya) yang isinya salinan versi aktif, lalu diubah lewat autosave `PATCH /forms/{id}` seperti biasa dan diterbitkan dengan `POST /forms/{id}/publish`. Bila draf sudah terbuka, draf itu yang dikembalikan. Audit `form.draft_opened`.
- `DELETE /forms/{id}/draft` (form_editor): membuang perubahan yang belum diterbitkan; versi aktif tidak berubah. Ditolak (`409 draft_is_only_version`) untuk struktur yang belum pernah diaktifkan. Audit `form.draft_discarded`.
- Selama draf dibuka, penyuluh tetap memakai versi aktif. Setelah diterbitkan, laporan berikutnya memakai versi baru; laporan yang sedang diisi selesai dengan versi lama, dan laporan lama tetap menunjuk versi saat dibuat. Kode gabung tidak berubah.
- Dasbor: tombol "Ubah" di daftar Struktur Data untuk struktur aktif, "Lanjutkan perubahan" dan "Buang perubahan" bila draf versi baru terbuka. Langkah terakhir wizard menjadi "Terbitkan vN".
- Perbaikan: membuka kembali draf yang dimulai dari kosong tidak lagi menyimpannya dengan template "00".
