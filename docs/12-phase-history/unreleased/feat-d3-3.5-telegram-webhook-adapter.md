## Webhook dan adapter Telegram

- `POST /webhooks/telegram`: verifikasi secret token, batas ukuran, simpan sekali per update, proses di worker (job `conversations.process` dengan kunci per chat).
- Adapter Telegram (httpx): kirim pesan HTML + tombol inline, jawab tombol, keluar dari grup; hanya chat privat; pesan diedit dan perpindahan live location tidak mengubah jawaban.
- Pesan keluar `pending → sent / uncertain / failed`; bot diblokir → penyuluh `unreachable`.
- Chat yang belum bergabung dibalas cara bergabung tanpa membuat data di organisasi mana pun.
- Worker kini memuat semua model (sebelumnya job yang menyentuh tabel ber-foreign key gagal).
- Env baru: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_SECRET`.
