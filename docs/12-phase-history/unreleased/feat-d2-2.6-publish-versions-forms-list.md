## Publikasi struktur data

- `POST /forms/{id}/publish` (admin): draf menjadi versi terbit dan status `active`; ditolak bila pemeriksaan otomatis masih menemukan masalah. `POST /forms/{id}/archive` (admin). Keduanya tercatat di audit log.
- Daftar dan detail form menyertakan nomor versi aktif dan waktu terbit.
