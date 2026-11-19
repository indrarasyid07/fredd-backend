# Messaging Channels

> **Diubah 17 November 2026 (B-048):** seluruh platform memakai satu bot WhatsApp dan satu bot Telegram; organisasi dan topik dibedakan dengan kode gabung. Lihat [join-codes.md](join-codes.md). Bagian di bawah yang menyebut penghubungan kanal per organisasi, token yang ditempel admin, atau undangan lewat nomor sudah tidak berlaku dan ditandai.

Modul `channels/`. Dua adapter tipis di atas httpx dengan satu antarmuka; tanpa framework bot.

```python
class Channel(Protocol):
    async def send_text(self, chat_id: str, text: str) -> str: ...
    async def send_choices(self, chat_id: str, text: str, options: list[Choice]) -> str: ...
    async def send_template(self, chat_id: str, template: str, params: list[str]) -> str: ...
    async def download_media(self, media_id: str) -> bytes: ...
    def parse_webhook(self, payload: dict) -> WebhookBatch: ...  # messages + status updates
```

## WhatsApp: Cloud API resmi

Desain canvas memakai pindai QR (perangkat tertaut). Itu jalur tidak resmi (Baileys / whatsapp-web.js): melanggar ToS dan berisiko nomor diblokir, terutama untuk pesan proaktif seperti pengingat. Fluctuz memakai **WhatsApp Business Cloud API** (langsung ke Meta atau lewat BSP).

Konsekuensi:

- ~~Layar "Hubungkan Kanal" WhatsApp diganti alur Embedded Signup Meta.~~ Tidak berlaku: satu nomor dan satu WABA dimiliki Fluctuz. Admin organisasi tidak menghubungkan apa pun; mereka membagikan kode gabung.
- **Jendela layanan 24 jam.** Teks bebas dan tombol hanya boleh dikirim dalam 24 jam sejak pesan terakhir penyuluh (`conversations.last_inbound_at`). Di luar itu adapter otomatis memakai template. Template yang perlu didaftarkan dan disetujui Meta:

| Template | Kategori | Isi |
|---|---|---|
| `fluctuz_intro` | utility | Perkenalan saat struktur dipublikasikan |
| ~~`fluctuz_invite`~~ | - | Dihapus: penyuluh yang memulai chat dengan kode, jadi tidak ada pesan undangan dari bisnis |
| `fluctuz_resume` | utility | "Laporan {1} berhenti di langkah {2}. Lanjutkan?" + tombol |
| `fluctuz_reminder` | utility | Pengingat laporan rutin |

- **Batas format:** reply buttons maks 3, list message maks 10 baris.
- **Media:** URL unduhan dari Meta cepat kedaluwarsa; worker langsung mengunduh ke S3.
- **Status webhook** (sent, delivered, read, failed) datang 2–3 kali per pesan keluar. Tidak masuk antrean; hanya `failed` yang memperbarui `messages.delivery_status` dan memicu activity event.
- **Biaya:** Meta menagih per pesan template terkirim (contoh harga reseller Indonesia, utility ~Rp366/pesan per Oktober 2026). Cek rate card resmi Meta sebelum menyusun anggaran. Verifikasi bisnis Meta butuh waktu; mulai sejak minggu pertama.

## Telegram: Bot API

- Satu bot milik Fluctuz dibuat operator di @BotFather; token disimpan sebagai rahasia lingkungan, bukan per organisasi.
- Operator memanggil `getMe` lalu `setWebhook` sekali ke `/webhooks/telegram` dengan `secret_token` acak.
- Tidak ada jendela 24 jam, tetapi penyuluh harus menekan Start dulu; tautan kode gabung `t.me/<bot>?start=<kode>` sekaligus memulai dan mengikat penyuluh ke topik.
- Setiap tombol inline yang ditekan dijawab `answerCallbackQuery` agar tombol tidak terus berputar.
- Batas ~30 pesan/detik per bot; pengiriman massal (pengumuman) lewat antrean.

### Yang sudah ada (Langkah 3.5)

- `POST /webhooks/telegram` (`app/api/webhooks/telegram.py`): mati (404) tanpa `TELEGRAM_WEBHOOK_SECRET`; header `X-Telegram-Bot-Api-Secret-Token` dibandingkan dengan `hmac.compare_digest` (salah → 401); body > 256 KB → 413; JSON rusak tetap 200 (agar Telegram tidak mengirim ulang selamanya). Update disimpan lalu job `conversations.process` diantrekan; tidak ada pemrosesan di dalam request.
- Adapter `app/modules/channels/telegram.py`: `parse_update` murni, `TelegramClient` (httpx, `sendMessage` dengan `parse_mode=HTML`, `answerCallbackQuery`, `leaveChat`). Galat dan log tidak pernah memuat URL (berisi token); logger `httpx` dinaikkan ke WARNING.
- Filter (3.5a): hanya chat privat. Pesan grup diabaikan, bot keluar (`leaveChat`) bila dimasukkan ke grup. `edited_message` tidak mengubah jawaban (balasan: kirim ulang sebagai pesan baru). Live location: hanya posisi awal; perpindahannya (edit) diabaikan. Stiker/kontak/polling → jenis `other`. `my_chat_member` → `kicked` = penyuluh memblokir bot → `extension_workers.status = unreachable` di semua organisasinya.
- `external_id`: masuk `update:<update_id>` (idempoten per bot), keluar `message:<chat_id>:<message_id>` (id pesan Telegram unik per chat).
- Tombol: `callback_data` ≤ 64 byte (lebih → galat saat kirim); ≤ 3 tombol pendek satu baris, selain itu satu tombol per baris. `ask_location` → keyboard balasan "📍 Kirim lokasi" (dirapikan di 3.8 bila digabung dengan tombol inline).
- Payload contoh di `tests/fixtures/webhooks/telegram/` (dibentuk dari Bot API; ganti dengan rekaman bot dev saat tersedia).

## Pesan gagal

Pesan keluar yang gagal dicoba ulang maks 3 kali dengan backoff. Setelah itu muncul di Integrasi Kanal › Aktivitas koneksi dan di daftar "Susul yang gagal".
