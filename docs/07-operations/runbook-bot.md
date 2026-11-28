# Runbook bot bersama (Telegram)

Langkah 7.4. Satu bot Telegram dipakai semua organisasi, jadi gangguan di sini mengenai semua instansi. Periksa dulu kesehatan bot:

```bash
uv run python -m scripts.bot_health   # exit 1 bila ada masalah
```

Worker juga memeriksa tiap 5 menit (`conversations.check_bot_health`) dan menulis log `WARNING bot health: …` per masalah; pasang alert di platform log pada teks itu. Ambang ada di `app/modules/conversations/health.py`.

| Masalah di `problems` | Arti |
|---|---|
| `telegram webhook URL is not set` | Webhook terhapus (mis. bot dipakai polling di tempat lain) |
| `telegram holds N pending updates` | Telegram tidak bisa menyerahkan pesan ke kita |
| `telegram webhook error: …` | Telegram mendapat galat dari webhook dalam 15 menit terakhir |
| `outgoing message pending for Ns` | Balasan tertahan: worker macet atau batas kirim (7.3) penuh |
| `N sends failed in the last hour` | Banyak kiriman gagal setelah dicoba ulang (7.2) |
| `worker heartbeat missing or stale` | Worker atau scheduler berhenti |

## Webhook mati

1. Lihat `webhook.last_error_message` dari `scripts.bot_health`. 401 → secret tidak cocok (lihat rotasi). 5xx/timeout → API tidak sehat: cek `GET /api/v1/health`, log API, Caddy.
2. URL kosong → pasang lagi dengan `setWebhook` (URL `https://<domain>/webhooks/telegram`, `secret_token` = `TELEGRAM_WEBHOOK_SECRET`). **Jangan** menjalankan `scripts.telegram_poll` dengan token staging/produksi: polling menghapus webhook.
3. Setelah pulih, Telegram mengirim ulang update yang tertahan (`pending_update_count` turun). Pesan disimpan idempoten, jadi update ganda tidak membuat pesan dobel.

## Antrean macet

1. `worker heartbeat missing or stale` → pastikan proses `taskiq worker` dan **tepat satu** `taskiq scheduler` berjalan (deployment.md).
2. `outgoing.pending` naik terus padahal worker hidup → cek Redis (batas kirim 7.3 memakai Redis; bila Redis mati batas dilewati, tidak memblokir).
3. Pesan `failed` menumpuk → cek `GET /channels/logs?status=failed` per organisasi; `failure=blocked` normal, `network`/`other` berarti gangguan Telegram atau jaringan server.

## Token bot bocor

1. Di @BotFather: `/revoke` token, buat token baru.
2. Ganti `TELEGRAM_BOT_TOKEN` di env server, restart API dan worker.
3. Pasang ulang webhook dengan token baru (`setWebhook`), sekalian ganti secret (lihat di bawah).
4. Catat di log insiden; periksa `audit_logs` dan log kanal untuk aktivitas aneh.

## Rotasi secret webhook

Tanpa downtime, karena API menerima dua nilai selama transisi:

1. Set `TELEGRAM_WEBHOOK_SECRET_PREVIOUS` = secret lama, `TELEGRAM_WEBHOOK_SECRET` = secret baru; deploy.
2. `setWebhook` dengan `secret_token` baru.
3. Setelah `scripts.bot_health` bersih beberapa menit, kosongkan `TELEGRAM_WEBHOOK_SECRET_PREVIOUS` dan deploy lagi.

## Bot diblokir massal

Banyak `failure=blocked` (penyuluh menjadi `unreachable`) dalam waktu singkat biasanya berarti pesan terasa spam:

1. Cek log aktivitas: apakah satu organisasi mengirim banyak pengingat? Jatah per organisasi ada di `send_limits.PROACTIVE_PER_MINUTE` (7.3); turunkan sementara bila perlu.
2. Hentikan sementara pengingat dengan menonaktifkan job `conversations.send_draft_reminders` (scheduler) bila sumbernya pengingat.
3. Hubungi admin organisasi terkait. Penyuluh `unreachable` aktif lagi begitu mereka menulis ke bot.

## Retensi

Cron `conversations.apply_retention` tiap malam 02:30 UTC menghapus pesan > 12 bulan dan foto laporan > 24 bulan (per workspace: `workspaces.settings.retention`), maksimal 1.000 baris per jenis per workspace per malam. Laporannya sendiri tidak dihapus.
