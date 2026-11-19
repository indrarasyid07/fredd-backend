## Mesin percakapan murni

- `conversations/engine/machine.py`: state machine yang menanyakan isian satu per satu, mengonfirmasi tebakan, menjalankan aturan JIKA/MAKA dan batas tinjauan, menawarkan bantuan setelah 3 kali gagal, ringkasan dengan ubah jawaban, lanjut/mulai ulang, diam saat diambil alih.
- Efek (klaim kode, pilih topik, simpan laporan, minta bantuan) dijalankan service; `FakeChannel` + `Simulator` untuk tes alur penuh tanpa database.
