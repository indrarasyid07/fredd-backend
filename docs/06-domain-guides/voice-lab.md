# Voice Lab

Analis atau peneliti lab merekam hasil kerjanya dengan suara lewat bot Telegram/WhatsApp; Fluctuz mengubahnya jadi data terstruktur, menanyakan ulang yang ragu, lalu penyelia mengoreksi dan memverifikasi sebelum data diunduh (CSV/Excel). Keputusan **D18** (cakupan MVP) dan **D7** (STT cloud, penyedia belum dipilih). Rencana: ROADMAP Langkah 12.

## Status

| Langkah | Isi | Status |
|---|---|---|
| 12.1 | Lapisan `app/modules/ai/`: STT + pengambil isian | **Ada** |
| 12.2 | Susun isian suara, uji dengan ucapan | Belum |
| 12.3 | Voice note di bot → isian terisi sekaligus | Belum |
| 12.4–12.6 | Halaman Voice data asli, koreksi & verifikasi, unduh | Belum |
| 12.7 | Penyedia STT/LLM cloud | Menunggu D7 |

## Mengubah suara jadi teks (`app/modules/ai/speech.py`)

`get_speech_to_text().transcribe(audio, content_type, language="id") -> Transcript(text, language, provider, confidence)`. `STT_PROVIDER=fake` (bawaan) membaca byte audio sebagai teks UTF-8 yang diucapkan, untuk pengembangan, simulator `/devtools`, dan tes. Penyedia lain belum ada → `503 speech_unavailable`. Tes mengganti penyedia lewat `speech.override`.

## Mengambil isian (`app/modules/ai/extraction.py`)

`extract(teks, struktur, cues=..., today=...) -> Extraction(values, missing)`.

1. **Penanda** tiap isian: label, kunci (`room_temp` → "room temp"), dan contoh ucapan dari admin (`cues`, Langkah 12.2). Penanda yang lebih panjang menang atas yang lebih pendek di dalamnya ("suhu ruang" sebelum "suhu"); tiap isian memakai kemunculan pertamanya.
2. Kata antara penanda dan penanda berikutnya dibaca sesuai jenis isian: angka (`parse_number` + satuan lab), pilihan tunggal/ganda (`parse_choice`, `parse_multi_choice`), tanggal (`parse_date`), teks apa adanya. Kata pengisi ("-nya", "adalah", "sebesar", ":") diabaikan.
3. Jenis lokasi dan media tidak diambil dari suara.

| Kondisi | Keyakinan | Alasan ragu (`doubt`) |
|---|---|---|
| Angka + satuan sesuai isian | 0,95 | – |
| Angka tanpa satuan | 0,85 | – |
| Pilihan/tanggal terbaca pasti | 0,9 | – |
| Teks | 0,75 | – |
| Pilihan mirip ("Mirip pilihan lain") | 0,5 | ya |
| Angka di luar `min`/`max` | 0,5 | "Di luar batas isian" |
| Satuan terdengar berbeda | 0,4 | "Satuan yang terdengar bukan …" |
| Tidak terbaca | 0 | ya (nilai `null`) |

Di bawah `CONFIDENT` (0,7) nilai **selalu** ditanyakan ulang ke analis (12.3). `missing` = isian wajib yang tidak disebut sama sekali. Setiap nilai menyimpan `heard` (kata yang didengar) untuk menandai transkrip di halaman Voice.
