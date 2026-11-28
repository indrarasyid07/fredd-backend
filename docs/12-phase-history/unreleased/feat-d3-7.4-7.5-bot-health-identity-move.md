## Ketahanan bot dan pindah akun penyuluh

- Retensi: pesan chat dihapus setelah 12 bulan dan foto laporan setelah 24 bulan (bisa diatur per workspace); laporannya tetap ada.
- Kesehatan bot diperiksa tiap 5 menit (webhook Telegram, pesan tertahan, kiriman gagal, worker); masalah ditulis sebagai peringatan di log. `python -m scripts.bot_health` untuk pemeriksaan manual.
- Secret webhook bisa diganti tanpa bot mati (dua nilai diterima selama rotasi). Runbook baru: `docs/07-operations/runbook-bot.md`.
- `POST /extension-workers/{id}/move-identity`: penyuluh yang ganti HP atau akun Telegram dipindahkan ke akun barunya; riwayat, topik, draf, dan laporannya tetap utuh.
