# Messaging Channels

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

- Layar "Hubungkan Kanal" WhatsApp diganti alur **Embedded Signup** Meta (login Facebook → pilih WABA → pilih nomor).
- **Jendela layanan 24 jam.** Teks bebas dan tombol hanya boleh dikirim dalam 24 jam sejak pesan terakhir penyuluh (`conversations.last_inbound_at`). Di luar itu adapter otomatis memakai template. Template yang perlu didaftarkan dan disetujui Meta:

| Template | Kategori | Isi |
|---|---|---|
| `fluctuz_intro` | utility | Perkenalan saat struktur dipublikasikan |
| `fluctuz_invite` | utility | Undangan + tautan verifikasi |
| `fluctuz_resume` | utility | "Laporan {1} berhenti di langkah {2}. Lanjutkan?" + tombol |
| `fluctuz_reminder` | utility | Pengingat laporan rutin |

- **Batas format:** reply buttons maks 3, list message maks 10 baris.
- **Media:** URL unduhan dari Meta cepat kedaluwarsa; worker langsung mengunduh ke S3.
- **Status webhook** (sent, delivered, read, failed) datang 2–3 kali per pesan keluar. Tidak masuk antrean; hanya `failed` yang memperbarui `messages.delivery_status` dan memicu activity event.
- **Biaya:** Meta menagih per pesan template terkirim (contoh harga reseller Indonesia, utility ~Rp366/pesan per Oktober 2026). Cek rate card resmi Meta sebelum menyusun anggaran. Verifikasi bisnis Meta butuh waktu; mulai sejak minggu pertama.

## Telegram: Bot API

- Admin membuat bot di @BotFather dan menempel token (alur desain sudah benar).
- Backend memanggil `getMe` (uji koneksi) lalu `setWebhook` ke `/webhooks/telegram/{channel_id}` dengan `secret_token` acak.
- Tidak ada jendela 24 jam, tetapi penyuluh harus menekan Start dulu sebelum bot bisa mengirim pesan; tautan undangan memakai `t.me/<bot>?start=<invite_token>` untuk sekaligus memverifikasi.
- Setiap tombol inline yang ditekan dijawab `answerCallbackQuery` agar tombol tidak terus berputar.
- Batas ~30 pesan/detik per bot; pengiriman massal (pengumuman) lewat antrean.

## Pesan gagal

Pesan keluar yang gagal dicoba ulang maks 3 kali dengan backoff. Setelah itu muncul di Integrasi Kanal › Aktivitas koneksi dan di daftar "Susul yang gagal".
