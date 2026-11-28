## Admin bisa mengambil alih percakapan

- `POST /conversations/{id}/takeover`, `/messages`, `/release`: admin mengambil alih chat penyuluh, membalas langsung lewat kanal penyuluh, lalu mengembalikannya ke Fluctuz. Dua admin bersamaan: yang kedua mendapat 409.
- Selama diambil alih, pesan penyuluh tetap tersimpan dan Fluctuz tidak membalas (status dicek ulang tepat sebelum mengirim).
- Saat dikembalikan, Fluctuz menanyakan lagi isian yang terbuka dan jatah percobaan diatur ulang. Takeover tanpa balasan admin selama 4 jam kembali otomatis dan dicatat di log Aktivitas.
- Percakapan kini mencatat `last_inbound_at` (pesan terakhir penyuluh) dan menampilkan sisa jendela 24 jam WhatsApp.
