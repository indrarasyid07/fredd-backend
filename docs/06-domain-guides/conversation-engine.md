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

## Urutan pemrosesan

Satu job Taskiq per chat (B-XXX). Job mengambil kunci Redis `chat:{channel_id}:{chat_id}` (hanya satu pemroses per chat; job lain untuk chat yang sama keluar tanpa kerja), membaca semua pesan `processed_at IS NULL` urut `channel_sent_at`, memprosesnya satu per satu, lalu memeriksa ulang pesan baru sebelum melepas kunci. Ini menjamin "Ya" lalu "Ubah" diproses sesuai urutan kirim.
