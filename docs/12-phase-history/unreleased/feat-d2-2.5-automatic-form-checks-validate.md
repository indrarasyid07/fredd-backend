## Pemeriksaan otomatis struktur data

- `POST /forms/{id}/validate`: semua masalah draf sekaligus dengan path bertitik per isian (isian/pertanyaan/pilihan kosong, nama kembar, aturan ke isian yang tidak ada, dan aturan `FormDefinition` lain); tanpa isian kondisi menjadi peringatan.
- Label pilihan di draf boleh kosong sementara (autosave tidak gagal).
