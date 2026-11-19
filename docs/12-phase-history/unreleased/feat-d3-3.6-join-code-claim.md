## Bergabung lewat kode di bot Telegram

- Penyuluh mengirim kode (atau membuka tautan `t.me/<bot>?start=<kode>`), lalu terikat ke organisasi dan topik pemilik kode, dengan konfirmasi "Ya, tetap / Bukan, ganti" dan kalimat persetujuan data.
- Kode topik lain: pilihan "Pindah / Tambah topik / Batal". Persetujuan manual, kode dijeda/penuh/kedaluwarsa, topik belum dibuka, dan penyuluh diblokir dibalas sesuai.
- Rate limit tebakan: 5 kode salah per jam, lalu bot diam untuk chat itu. Klaim dan keluar topik tercatat di audit log.
- Pesan dari chat yang sudah bergabung (masuk dan keluar) kini menjadi milik organisasi dan percakapan topik aktifnya; chat tanpa topik tetap tanpa organisasi.
- Env baru opsional: `PRIVACY_POLICY_URL`.
