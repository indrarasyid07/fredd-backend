# Glossary

Padanan istilah domain (Bahasa Indonesia, dipakai di UI dan percakapan) dengan nama di kode, API, dan database (Bahasa Inggris). Dipakai juga oleh frontend.

| Istilah UI | Nama di kode | Keterangan |
|---|---|---|
| Workspace | `workspace` | Satu instansi/organisasi |
| Anggota | `member` | Pengguna dashboard |
| Administrator | `admin` | Peran |
| Editor Struktur | `form_editor` | Peran |
| Peninjau | `reviewer` | Peran |
| Penyuluh | `extension_worker` | Petugas lapangan yang melapor lewat chat |
| Struktur data | `form` | Kumpulan isian + aturan |
| Versi struktur | `form_version` | Tidak berubah setelah dipublikasikan |
| Isian / parameter | `field` | Satu pertanyaan dalam struktur |
| Aturan JIKA/MAKA | `rule` | Logika antar-isian |
| Data rujukan | `reference_data` | Wilayah, komoditas, kelompok tani, satuan |
| Wilayah | `region` | Kabupaten/kecamatan/desa |
| Komoditas | `commodity` | Padi, Jagung, Cabai, … |
| Kelompok tani | `farmer_group` | |
| Kanal | `channel` | WhatsApp atau Telegram; satu bot bersama untuk seluruh platform (B-048) |
| Kode gabung | `join_code` | Kode otomatis per struktur data yang dikirim penyuluh ke bot untuk bergabung, contoh `K7M2-9QXA` |
| Ikatan | `binding` | Hubungan identitas chat penyuluh dengan organisasi dan topik lewat kode gabung |
| Percakapan | `conversation` | Sesi pengisian satu struktur oleh satu penyuluh |
| Draf | `draft_answers` | Jawaban sementara sebelum dikirim |
| Ambil alih | `takeover` | Admin membalas langsung, Fluctuz berhenti sementara |
| Kembalikan ke Fluctuz | `release` | Akhir takeover |
| Laporan / Data lapangan | `report` | Hasil pengisian yang sudah dikirim |
| Kode laporan | `report.code` | `LP-2411-0248` |
| Perlu ditinjau | `needs_review` | Dipicu aturan, mis. luas > 50 ha |
| Tindak lanjut | `follow_up` | |
| Kondisi tanaman: Sehat / Perlu perhatian / Terserang | `healthy` / `needs_attention` / `infested` | |
| Aktivitas Agent | `activity` / `activity_event` | Log kejadian |
| Perlu bantuan admin | `needs_help` | Status percakapan |
| Pilot | `pilot` | Publikasi ke sebagian penyuluh |
| Publikasi | `publish` | |
| Jam tenang | `quiet_hours` | Pengingat tidak dikirim |
| Jam operasional | `operating_hours` | |
| Pengingat | `reminder` | |
| Undangan | `invite` | Tidak dipakai untuk penyuluh sejak B-048 (diganti kode gabung); tetap dipakai untuk anggota tim (`/members/invites`) |
| Prospek (form landing page) | `lead` | |
| Paket | `plan` | Gratis, Plus, Starter, Growth, Enterprise |
| Artikel | `article` | Tulisan blog; jenis `post` atau `external` (liputan media) |
| Kategori artikel | `article_category` | |
| Penulis konten / Editor konten | `content_author` / `content_editor` | Peran platform (`users.platform_role`), bukan peran workspace |
| Terjadwal | `scheduled` | Status artikel dengan tanggal terbit di masa depan |
| Langganan | `subscription` | |
| Kuota | `quota` / `limits` | Anggota, formulir aktif, laporan per bulan |
| Perorangan / Organisasi | `personal` / `organization` | Tipe workspace |
| Formulir (di halaman Upgrade) | `form` | Sama dengan struktur data |
