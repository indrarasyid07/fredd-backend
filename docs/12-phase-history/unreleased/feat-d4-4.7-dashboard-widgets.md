## Data widget dashboard per struktur

- Setiap jawaban isian pilihan dan angka kini juga disimpan sebagai nilai tersendiri, termasuk dari laporan lama, sehingga dashboard bisa menghitung isian apa pun (status sampel, pH, jumlah ternak, pengeluaran) tanpa membaca isi laporan satu per satu.
- `GET /dashboard/forms/{form_id}`: jumlah laporan, tren 7 hari, sebaran setiap isian pilihan, dan rata-rata/jumlah/terendah/tertinggi setiap isian angka untuk satu struktur.
- Peran isian baru `status` (pilihan) dan `measure` (angka) menandai isian yang tampil di dashboard secara bawaan; keduanya boleh dipakai lebih dari sekali.
