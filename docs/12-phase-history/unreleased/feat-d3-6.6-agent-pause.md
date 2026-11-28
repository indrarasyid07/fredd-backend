## Jeda agent

- `POST /agent/pause` dan `/agent/resume` (admin), `GET /agent/status`: admin menghentikan sementara Fluctuz untuk seluruh organisasi. Pesan penyuluh tetap tersimpan; setiap penyuluh diberi tahu sekali bahwa agent sedang dijeda; pengingat dan aturan ambil alih ikut berhenti. Setelah dilanjutkan, penyuluh meneruskan dari pertanyaan terakhir.
