## Kode gabung otomatis

- Tabel `join_codes`; setiap struktur data mendapat kode saat dibuat (struktur lama lewat migrasi).
- `GET/PATCH /forms/{id}/join-code`: kode, status, persetujuan, batas, `claimable`, tautan WhatsApp/Telegram.
- Env baru opsional: `TELEGRAM_BOT_USERNAME`, `WHATSAPP_PUBLIC_NUMBER`.
