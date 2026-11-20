# Conversation Engine

Modul `conversations/`. Menjalankan satu `form_version` sebagai percakapan dengan satu penyuluh, sama untuk WhatsApp dan Telegram.

## Prinsip

- **Deterministik dulu.** Urutan pertanyaan, aturan, dan validasi ditentukan kode. LLM hanya dipakai sebagai fallback di titik tertentu, dan hasil tebakannya selalu dikonfirmasi ke penyuluh.
- **Satu pertanyaan per pesan**, dengan penanda kemajuan (`3/5`).
- **Tidak ada jawaban yang hilang.** Setiap jawaban valid langsung masuk `draft_answers`.

## State

```
idle → joining → identifying → choosing_form → asking(step) → confirming_summary → submitted
                                   ↘ needs_help (setelah 3 kali gagal atau pertanyaan di luar alur)
                                   ↘ taken_over (admin membalas)
```

`conversations.step` menunjuk `field.key` yang sedang ditanyakan.

## Langkah per pesan masuk

1. Kenali penyuluh dari `chat_contexts` dan `extension_workers` (`phone_e164` / `telegram_chat_id`). Pesan yang berisi **kode gabung** yang dikenali memicu state `joining`: validasi kode, buat atau temukan ikatan, lalu lanjut. Tidak terikat dan bukan kode → balas cara bergabung, berhenti. Lihat [join-codes.md](join-codes.md).
2. Bila ada beberapa struktur aktif, atau penyuluh terikat ke lebih dari satu topik (bisa di organisasi berbeda), tawarkan pilihan berisi nama organisasi dan topik.
3. Validasi jawaban sesuai tipe `field`:

| Tipe | Validasi deterministik | Fallback |
|---|---|---|
| `number` | parser angka Indonesia ("1,5", "1.5", "satu setengah", "2 ha"), `min`/`max` | LLM bila parser gagal → konfirmasi |
| `choice` | cocok persis/alias/fuzzy dengan `options` atau `reference_data.aliases` | LLM → konfirmasi "Maksud Anda Padi?" |
| `text` | panjang min/maks | – |
| `photo` | jumlah min/maks, ukuran, skor buram (variansi tepi via Pillow) | – |
| `location` | pesan lokasi kanal, `max_accuracy_m` | – |
| `date` | parser tanggal Indonesia ("kemarin", "12/11") | LLM → konfirmasi |
| suara | speech-to-text → diperlakukan sebagai teks → konfirmasi | – |

4. Valid → simpan ke `draft_answers`, reset `failed_attempts`, terapkan `rules`, tentukan pertanyaan berikutnya.
5. Tidak valid → balas alasan + contoh ("Tulis angka, contoh: 1,5"), `failed_attempts += 1`. Pada 3 → tawarkan "Lewati" (bila tidak wajib) atau "Minta bantuan admin" → status `needs_help`, muncul di antrean Aktivitas Agent.
6. Semua isian terjawab → kirim ringkasan dengan pilihan "Kirim sekarang" / "Ubah jawaban".
7. Kirim → buat `reports` dalam satu transaksi bersama update `conversations.status = submitted`, salin kolom filter, terapkan aturan `review_above` → `needs_review`, balas kode laporan.

## Mesin murni (Langkah 3.3)

`engine/machine.py`: `handle(state, pesan, ctx) → Step(state, replies, effects)`, tanpa database dan kanal. `ConversationState` berbentuk JSON (status, `topic_id`, `step`, `answers`, `required_by_rules`, `review_reasons`, `failed_attempts`, `pending`, `editing`). `EngineContext` dimuat service per pesan: sapaan ("Pak Budi"), hari ini di zona workspace, topik yang terikat, `FormDefinition` topik aktif, alias satuan.

- **Efek** dijalankan service: `ClaimCode` (teks berbentuk kode; di tengah laporan hanya bila berformat `XXXX-XXXX`/berawalan `gabung`/`kode`/`/start`, agar nama 8 huruf tidak salah baca; status tidak diubah sehingga kode tak dikenal tidak menghapus progres), `SelectTopic` (lalu service memanggil `start`), `SubmitReport` (jawaban, `needs_review`, alasan; lalu `report_saved(code)`), `NeedsHelp`.
- **Bertanya:** satu pertanyaan per pesan berawalan "3/5"; pilihan tunggal ≤ 10 jadi tombol, lebih banyak/beberapa pilihan jadi daftar bernomor; isian tidak wajib diberi tombol "Lewati"; lokasi meminta tombol bagikan lokasi.
- **Konfirmasi tebakan:** angka yang ditulis dengan kata ("Dicatat *1,5 ha*. Benar?") dan pilihan salah ketik ("Maksud Anda *Sehat*?"); jawaban baru di tengah konfirmasi dibaca sebagai jawaban.
- **Gagal:** alasan + contoh, lalu pertanyaan diulang; kali ke-3 menawarkan "Lewati" (bila tidak wajib) dan "Minta bantuan admin" → `needs_help` (bot diam sampai admin).
- **Aturan:** dihitung ulang dari semua jawaban setiap kali ada jawaban (mengubah jawaban juga membatalkan efek aturan); `require` membuat isian wajib dan menanyakan ulang yang sempat dilewati; `needs_review` dan `review_above` menjadi alasan tinjauan (`rule:<i>`, `review_above:<key>`).
- **Media:** foto/video/berkas dikumpulkan sampai `max` atau "selesai" (minimal `min`); suara untuk pertanyaan teks belum dibaca (menunggu STT).
- **Ringkasan:** "Kirim sekarang" → `SubmitReport`; "Ubah jawaban" → pilih isian → tanya ulang → kembali ke ringkasan. "lanjut" mengulang pertanyaan saat ini, "mulai ulang" mengosongkan draf, "mulai" setelah terkirim membuka laporan baru (memilih topik bila lebih dari satu). `taken_over`: bot diam.
- `engine/simulator.py`: `FakeChannel` + `Simulator` (service tiruan di memori) untuk tes dan simulator chat (3.9).

## Kata perintah resmi (Langkah 3.0)

Diputuskan 20 November 2026 (B-XXX). Tidak peka huruf besar/kecil, spasi berlebih diabaikan, garis miring di depan boleh (`/lanjut`). Perintah dikenali di semua state kecuali `taken_over` (bot diam; pesan diteruskan ke admin) dan `joining` (yang berlaku tombol konfirmasi). Di tengah pertanyaan teks, kata perintah yang **persis** sama (seluruh pesan) dibaca sebagai perintah, bukan jawaban.

| Perintah | Alias | Perilaku | Konfirmasi |
|---|---|---|---|
| `mulai` | `/start` tanpa kode, `lapor`, `laporan baru` | Mulai laporan baru. Ada draf → tawarkan [Lanjutkan] [Mulai ulang]. Lebih dari satu topik → pilih topik dulu | – |
| `lanjut` | `lanjutkan` | Ulangi pertanyaan terakhir dari draf. Tanpa draf → seperti `mulai` | – |
| `mulai ulang` | `ulang dari awal`, `/ulang` | Kosongkan draf, mulai dari isian pertama versi yang sama | Ya, karena jawaban hilang |
| `topik` | `ganti topik` | Tampilkan topik yang terikat (organisasi · topik) untuk dipilih. Draf topik lama tetap tersimpan. Hanya satu topik → sebutkan topiknya | – |
| `batal` | `batalkan` | Buang draf yang sedang diisi, kembali ke `idle` | Ya |
| `bantuan` | `tolong`, `help`, `minta bantuan` | Daftar perintah singkat + tombol [Minta bantuan admin] (→ `needs_help`) | – |
| `berhenti` | `stop`, `keluar` | Opt-out (wajib menurut kebijakan WhatsApp): lepas **semua** ikatan chat ini, lihat di bawah | Ya |

Kata `ya/tidak` tetap dibaca sebagai jawaban konfirmasi (`parse_yes_no`), bukan perintah. `selesai` hanya berarti "cukup" saat mengumpulkan foto.

**`berhenti`.** Bot bertanya "Berhenti menerima pesan dari Fluctuz untuk semua topik di chat ini? Draf yang belum terkirim akan dibuang." [Ya, berhenti] [Batal]. Setelah "Ya": semua `form_assignments` aktif chat itu menjadi `left`, penyuluh yang tidak punya topik lain menjadi `left`, `chat_contexts` dikosongkan, draf dibuang, `next_reminder_at` dihapus, audit `extension_worker.opted_out`. Balasan terakhir: "Anda tidak akan menerima pesan lagi. Untuk bergabung kembali, kirim kode dari admin Anda." Laporan yang sudah terkirim tidak dihapus. Bergabung lagi cukup dengan mengirim kode (ikatan dihidupkan lagi).

**Foto sebelum `mulai`.** Pesan sambutan mengajak "Kirim foto lahan atau ketik *mulai*". Foto (atau album) yang dikirim saat `idle` dengan satu topik aktif memulai laporan baru: foto disimpan sebagai jawaban **isian foto pertama** (urutan definisi), lalu bot menanyakan isian lain mulai dari isian pertama yang belum terjawab. Batas `max` isian itu tetap berlaku (kelebihan diabaikan dengan pemberitahuan). Struktur tanpa isian foto → laporan tetap dimulai, foto diabaikan dengan pemberitahuan "Topik ini tidak meminta foto". Lebih dari satu topik → bot menanyakan topik dulu, foto disimpan sementara di draf dan dipakai setelah topik dipilih. Ada draf yang belum selesai → foto diperlakukan sebagai jawaban pertanyaan saat ini (bila isian foto) atau bot menawarkan [Lanjutkan] [Mulai ulang].

## Pengurai jawaban (Langkah 3.2)

`app/modules/conversations/engine/parsers.py`: fungsi murni tanpa I/O; mengembalikan `None` bila jawaban tidak terbaca dengan yakin (mesin lalu bertanya ulang dengan contoh, tidak menebak).

| Fungsi | Membaca | Catatan |
|---|---|---|
| `parse_number(text, units=)` | `1,5` · `1.5` · `1.500` (ribuan) · `1.500,75` · `Rp 1.250.000,-` · `2 ha` · `2ha` · `sekitar 2 hektar` · `3/4` · `1 1/2` · `satu setengah` · `dua koma lima` · `dua ratus lima puluh` · `satu juta dua ratus ribu` | Koma = desimal; titik + tepat 3 angka = ribuan, selain itu desimal. Satuan dikembalikan sebagai kode (`ha`, `kg`, `quintal`, `rupiah`, `person`...); alias tambahan dari data rujukan lewat `units`. Gagal: `banyak`, `1-2`, `2 atau 3`, `dua tiga` |
| `parse_date(text, today=)` | `hari ini` · `kemarin` · `kemarin lusa` · `2 hari lalu` · `seminggu lalu` · nama hari (hari itu atau sebelumnya) · `12/11` · `12/11/26` · `2026-11-12` · `12 nov 2026` · `tgl 3 agustus` | Laporan tentang masa lalu: tanggal-bulan yang jatuh di masa depan berarti tahun lalu; masa depan (`minggu depan`) gagal. `today_in(tz)` memberi hari ini di zona workspace |
| `parse_choice(text, options)` | nomor urut (`2`, `no 2`) · label/nilai/alias persis (`pari` → Padi) · frasa dengan kata pengisi (`sehat semua`, `terserang hama`) · salah ketik (`pdi`) | Salah ketik lewat **rapidfuzz** (`ratio` ≥ 80, selisih ≥ 5 dari pesaing) ditandai `needs_confirmation` → mesin bertanya "Maksud Anda Padi?". Ambigu → gagal |
| `parse_multi_choice` | `padi, jagung dan cengek` · `1, 3` | Mengembalikan pilihan unik + bagian yang tidak dikenali |
| `parse_yes_no` | `ya/iya/ok/sudah/siap` · `tidak/tdk/gak/belum/bukan` | Campuran → gagal |

Tes: tabel kasus + tes properti **hypothesis** (bilangan bulat berpemisah ribuan, desimal berkoma, tanggal penuh) + **time-machine** untuk batas hari di zona waktu.

## Pilihan jawaban di kanal

| Jumlah pilihan | WhatsApp | Telegram |
|---|---|---|
| ≤ 3 | Reply buttons | Inline keyboard |
| 4–10 | List message | Inline keyboard |
| > 10 | Minta ketik, cocokkan dengan alias/fuzzy | Minta ketik, cocokkan dengan alias/fuzzy |

## Draf dan pengingat

- Penyuluh berhenti di tengah → `next_reminder_at = last_inbound_at + 24 jam`, digeser ke luar `quiet_hours` dalam `workspace.timezone`.
- Cron mengirim pengingat yang jatuh tempo. Di WhatsApp ini selalu di luar jendela 24 jam, jadi wajib template (lihat [messaging-channels.md](messaging-channels.md)).
- Balasan "lanjut" melanjutkan dari `step` terakhir; "mulai ulang" mengosongkan draf.

## Takeover

- Admin mengambil alih (`taken_over_by` diisi lewat UPDATE bersyarat). Selama itu pesan penyuluh tetap disimpan dan ditampilkan ke admin, tetapi Fluctuz tidak membalas.
- Worker membaca ulang status takeover tepat sebelum mengirim, agar balasan Fluctuz tidak menyela admin.
- "Kembalikan ke Fluctuz" melanjutkan dari `step` saat ini.

## Pesan keluar tanpa dobel (Langkah 3.0, ada sejak 3.5/3.9a)

Setiap balasan dicatat dulu sebagai baris `messages` keluar `pending` (dalam transaksi yang sama dengan pemrosesan pesan masuk), baru dikirim ke kanal. Hasil kirim: `sent` + `external_id`; timeout → `uncertain` dan **tidak** dikirim ulang otomatis (pesan mungkin sudah sampai); galat lain → `failed`; `403` (bot diblokir) → penyuluh `unreachable`. `deliver` mengunci baris (`FOR UPDATE SKIP LOCKED`) dan hanya mengirim baris yang masih `pending`, sehingga dua worker tidak mengirim pesan yang sama. Pesan yang dibuat di luar pemrosesan chat (mis. persetujuan admin, 4.6) memakai job `conversations.deliver` dengan aturan yang sama. Kirim ulang manual untuk `failed`/`uncertain` ada di Langkah 7.2.

## Antrean kirim yang adil (rancangan Langkah 3.0, dibangun di 7.3)

Satu bot dipakai semua organisasi, jadi batas kirim kanal (Telegram ±30 pesan/detik per bot dan 1 pesan/detik per chat; WhatsApp sesuai tier nomor) dibagi bersama. Rancangan:

| Jalur | Isi | Aturan |
|---|---|---|
| **Interaktif** | Balasan atas pesan penyuluh, konfirmasi bergabung, kabar persetujuan admin, pesan admin saat takeover | Selalu didahulukan; tidak dibatasi kuota organisasi, hanya batas kanal per chat |
| **Proaktif** | Pengingat draf, pengumuman/broadcast, pesan terjadwal | Antrean terpisah; token bucket Redis **per organisasi** (`send-budget:{workspace_id}`) dengan jatah per menit sesuai paket, plus batas global per bot; jatuh tempo di jam tenang ditunda |

Pekerja kirim mengambil dari jalur interaktif lebih dulu, lalu proaktif secara round-robin antar organisasi, sehingga satu organisasi yang mengirim pengumuman besar tidak menunda balasan organisasi lain. Kuota harian per paket (D12/9.1) dihitung dari jalur proaktif.

## Urutan pemrosesan

**Ada (3.5):** `process_chat_job(channel_id, chat_id)` mengambil kunci Redis `chat-lock:{channel_id}:{chat_id}` (`SET NX`, 120 dtk); job lain untuk chat yang sama langsung keluar, dan pemegang kunci memeriksa ulang pesan baru setelah melepasnya. Pesan diurutkan `channel_sent_at`, lalu `update_id` Telegram (tanggal Telegram hanya sampai detik). Balasan dicatat sebagai baris keluar `pending` dalam transaksi yang sama dengan `processed_at`, lalu dikirim satu per satu: `sent` + `external_id`, `uncertain` saat timeout (tidak dikirim ulang otomatis), atau `failed` (403 → penyuluh `unreachable`). Chat tanpa ikatan hanya dibalas cara bergabung (satu kali per rombongan pesan) dan tidak membuat apa pun di organisasi mana pun; klaim kode menyusul di 3.6, alur laporan di 3.7.


Satu job Taskiq per chat (B-XXX). Job mengambil kunci Redis `chat:{channel_id}:{chat_id}` (hanya satu pemroses per chat; job lain untuk chat yang sama keluar tanpa kerja), membaca semua pesan `processed_at IS NULL` urut `channel_sent_at`, memprosesnya satu per satu, lalu memeriksa ulang pesan baru sebelum melepas kunci. Ini menjamin "Ya" lalu "Ubah" diproses sesuai urutan kirim.
