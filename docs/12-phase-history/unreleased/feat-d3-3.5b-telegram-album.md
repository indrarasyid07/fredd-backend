## Album foto Telegram dijawab sekali

- Telegram mengirim tiap foto album sebagai pesan terpisah. Worker kini menunggu sampai album tenang 1,5 detik (paling lama 6 detik) sebelum memproses chat, lalu memproses semua foto album dalam satu putaran.
- Album yang dikirim saat bot meminta foto mendapat satu balasan ("Foto ke-3 diterima…"), bukan satu balasan per foto.
- Foto album yang melebihi `max` isian tetap ikut isian itu: diabaikan dengan satu pemberitahuan, tidak dianggap jawaban untuk pertanyaan berikutnya.
