# Product Overview

Sumber: artifact canvas desain "Fluctuz" (halaman Login Register, Dashboard, Pengelolaan, Dashboard V.1, AI Agent Build, Struktur Data Baru).

## Apa itu Fluctuz

Fluctuz adalah agen AI yang mengumpulkan laporan lapangan dari penyuluh pertanian lewat chat WhatsApp dan Telegram. Admin instansi menyusun **struktur data** (daftar isian + aturan), Fluctuz menanyakannya ke penyuluh satu pertanyaan per pesan, memvalidasi jawaban, lalu menyimpan laporan yang tampil di dashboard (tabel, peta, galeri, analitik).

Fluctuz dijual sebagai SaaS dengan paket: Perorangan (Gratis, Plus) dan Organisasi (Starter, Growth, Enterprise). Lihat [billing-and-plans.md](../06-domain-guides/billing-and-plans.md).

Acuan desain: halaman canvas Login Register V.1, Dashboard V.1, Struktur Data Baru V.1, Penyuluh V.1, dan Upgrade.

## Aktor

| Aktor | Kanal | Peran |
|---|---|---|
| Admin / Editor / Peninjau | Dashboard web | Menyusun struktur, mengelola penyuluh dan kanal, meninjau laporan, mengambil alih percakapan |
| Penyuluh | WhatsApp / Telegram | Mengisi laporan dari lapangan |
| Fluctuz (agen) | Backend | Menjalankan percakapan, validasi, pengingat, ringkasan |
| Pengunjung publik | Website | Membaca landing page, mendaftar |

## Alur utama admin

1. **Persiapan:** siapkan data rujukan (wilayah, komoditas, kelompok tani, satuan). Kanal sudah tersedia (satu bot WhatsApp dan satu Telegram untuk semua); penyuluh bergabung dengan mengirim kode gabung topik ([join-codes.md](../06-domain-guides/join-codes.md)).
2. **Rancang:** informasi dasar, susun isian (teks, angka, pilihan, foto, lokasi, tanggal), aturan JIKA/MAKA dan validasi.
3. **Uji:** pemeriksaan otomatis, uji di akun sendiri.
4. **Pilot:** 2–3 penyuluh di satu wilayah, ukur tingkat selesai.
5. **Publikasi:** struktur menjadi versi aktif, pesan perkenalan dikirim.
6. **Berjalan:** pantau dashboard dan aktivitas agen, ambil alih percakapan, ubah struktur (membuat versi baru).

## Alur utama penyuluh

Mulai → Fluctuz mengenali dari nomor/chat ID → satu pertanyaan per pesan (penanda 3/5) → validasi (koreksi dengan contoh; setelah 3 kali gagal tawarkan lewati atau bantuan admin) → ringkasan → kirim → ID laporan. Bila sinyal hilang, jawaban tersimpan sebagai draf dan Fluctuz mengingatkan nanti di luar jam tenang.

## Ruang lingkup v1 (usulan)

Inti:

- Website publik (landing page) untuk SEO dan pendaftaran.
- Daftar dan masuk dengan email + kata sandi atau Google; peran Admin, Editor Struktur, Peninjau.
- Paket dan kuota (Gratis, Plus, Starter, Growth), checkout lewat penyedia pembayaran.
- Kanal Telegram, lalu WhatsApp Cloud API setelah verifikasi bisnis Meta.
- Penyusun struktur berversi + data rujukan.
- Mesin percakapan dengan draf dan pengingat.
- Data Lapangan: tabel, peta, detail, ekspor Excel.
- Aktivitas agen dan ambil alih percakapan.

Bisa menyusul setelah v1 (kecuali sudah dijanjikan ke klien):

- Halaman metrik pilot khusus (pilot cukup = publikasi ke sebagian penyuluh).
- Laporan terjadwal PDF/Excel.
- Insight Fluctuz, Tanya Fluctuz, perkiraan kondisi dari foto.
- Jawaban lewat pesan suara.
- Galeri foto sebagai tampilan terpisah.

## Pertanyaan terbuka

1. ~~Cara masuk dashboard~~: diputuskan email + kata sandi dan Google (B-013).
2. Pemilik akun Meta Business untuk WhatsApp (klien atau Fluctuz) dan anggaran biaya per pesan.
3. ~~Satu instansi atau multi-tenant~~: multi-tenant dengan paket per workspace (B-012).
4. Penyedia LLM dan speech-to-text.
5. Hosting dan syarat lokasi data (harus di Indonesia atau tidak).
6. Sumber tile peta (PMTiles sendiri atau penyedia berbayar).
7. Canvas V.1 menambah konsep baru yang belum ada di model data: folder proyek, antrean tinjauan (lolos otomatis / perlu ditinjau / diminta ulang), pemeriksaan otomatis per laporan, kualitas data penyuluh, peran koordinator wilayah, tautan undangan bersama berkuota, serta menu Spatial dan Sensors. Rincian: `frontend/docs/06-domain-guides/ui/README.md`.
8. ~~Layar ganda ("copy") di canvas~~: tidak relevan, acuan desain hanya halaman V.1 dan Upgrade.
9. Penyedia pembayaran, faktur/PPN, dan perilaku saat kuota habis (lihat [billing-and-plans.md](../06-domain-guides/billing-and-plans.md#pertanyaan-terbuka)).
