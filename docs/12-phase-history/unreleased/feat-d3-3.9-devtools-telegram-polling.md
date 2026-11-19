## Mencoba bot tanpa Telegram, dan bot dev tanpa URL publik

- `/devtools`: simulator chat di browser (hanya development) yang memakai jalur pesan yang sama dengan webhook Telegram.
- `python -m scripts.telegram_poll`: menjalankan bot development lewat `getUpdates`; menolak bot yang memakai webhook dan lingkungan selain development.
- Antarmuka `BotApi` untuk klien bot (Telegram, simulator, tes).
