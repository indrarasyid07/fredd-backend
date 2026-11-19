## Antrean dan worker

- Taskiq + Redis streams menggantikan rencana arq: `app/core/queue.py` (broker, retry dengan backoff), `app/worker.py` (worker + scheduler cron), cron `system.heartbeat` tiap menit (`worker:heartbeat`).
- Email verifikasi, reset kata sandi, dan undangan dikirim lewat job `email.send` dengan retry; permintaan tidak pernah gagal karena email.
- `QUEUE_INLINE=true` (tes dan lokal) menjalankan job langsung tanpa worker. Dependency baru: taskiq, taskiq-redis.
