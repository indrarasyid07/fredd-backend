# Voice Lab

Analis atau peneliti lab merekam hasil kerjanya dengan suara lewat bot Telegram/WhatsApp; Fluctuz mengubahnya jadi data terstruktur, menanyakan ulang yang ragu, lalu penyelia mengoreksi dan memverifikasi sebelum data diunduh (CSV/Excel). Keputusan **D18** (cakupan MVP) dan **D7** (STT cloud, penyedia belum dipilih). Rencana: ROADMAP Langkah 12.

## Status

| Langkah | Isi | Status |
|---|---|---|
| 12.1 | Lapisan `app/modules/ai/`: STT + pengambil isian | **Ada** |
| 12.2 | Susun isian suara (`voice_cues`, `unit_aliases`, `settings.input_mode`), uji dengan ucapan (`POST /forms/{id}/voice-test`) | **Ada** |
| 12.3 | Voice note di bot → isian terisi sekaligus, `reports.voice` | **Ada** |
| 12.4 | Halaman Voice data asli: `GET /reports?voice=true`, `GET /reports/{id}.voice` | **Ada** |
| 12.5–12.6 | Koreksi & verifikasi, unduh | Belum |
| 12.7 | Penyedia STT/LLM cloud | Menunggu D7 |

## Mengubah suara jadi teks (`app/modules/ai/speech.py`)

`get_speech_to_text().transcribe(audio, content_type, language="id") -> Transcript(text, language, provider, confidence)`. `STT_PROVIDER=fake` (bawaan) membaca byte audio sebagai teks UTF-8 yang diucapkan, untuk pengembangan, simulator `/devtools`, dan tes. Penyedia lain belum ada → `503 speech_unavailable`. Tes mengganti penyedia lewat `speech.override`.

## Mengambil isian (`app/modules/ai/extraction.py`)

`extract(teks, struktur, cues=..., today=...) -> Extraction(values, missing)`.

1. **Penanda** tiap isian: label, kunci (`room_temp` → "room temp"), sebutan lain dari admin (`voice_cues`, Langkah 12.2), dan `cues` tambahan dari pemanggil. Sebutan satuan per isian (`unit_aliases`, mis. "derajat" untuk °C) berarti persis satuan isian itu. Penanda yang lebih panjang menang atas yang lebih pendek di dalamnya ("suhu ruang" sebelum "suhu"); tiap isian memakai kemunculan pertamanya.
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

## Alur di bot (Langkah 12.3)

Berlaku untuk topik yang strukturnya `settings.input_mode = "voice"`; topik `chat` tidak berubah.

1. Setelah "Ya, tetap", bot mengajak: "Kirim *pesan suara* berisi hasilnya, atau ketik *mulai*".
2. **Pesan suara** (atau kalimat yang diketik) saat belum ada laporan langsung memulai laporan: worker menyimpan audio ke penyimpanan (jalur foto 3.8), lalu `speech.get_speech_to_text().transcribe` mengisi `messages.payload.transcript`; mesin membaca transkrip dengan `extract`. `mulai` → bot meminta satu kalimat dengan contoh dari isian (`step = "__voice__"`).
3. Nilai **yakin** langsung menjadi jawaban; balasan "Tercatat: … · …" dan, bila ada, "Perlu dipastikan: Suhu (\"25 ml\")".
4. Isian wajib yang tidak disebut dan nilai yang ragu ditanyakan **satu per satu** dengan alur chat biasa (urutan isian); jawabannya boleh suara lagi. Isian opsional ditawarkan dengan "Lewati". Lalu ringkasan → Kirim.
5. Laporan menyimpan `reports.voice` = `{transcript, audio, heard{isian: kata}, confidence{isian: 0–1}}`; `report_values` tetap terisi untuk dashboard.

Pengubah suara gagal (penyedia mati) → pesan tidak hilang; bot menjawab "Pesan suara belum bisa saya dengar. Coba kirim ulang, atau ketik hasilnya." Kalimat tanpa isian yang dikenali di langkah suara → contoh kalimat + hitungan gagal (3x → bantuan admin seperti alur chat).

**Mencoba tanpa Telegram:** simulator `/devtools` punya tombol "🎤 Kirim sebagai pesan suara": isi kotak pesan menjadi kata-kata pesan suara (penyedia `fake` membacanya kembali).

## API halaman Voice (Langkah 12.4)

Voice adalah laporan yang diisi dari pesan suara, jadi memakai endpoint laporan (tanpa `/voice` terpisah):

- `GET /reports?voice=true` → hanya laporan bersumber suara (`voice=false` → hanya chat); tiap baris membawa `transcript`.
- `GET /reports/{id}` → bagian `voice` (null untuk laporan chat): `transcript`, `audio_url` + `audio_expires_at` (URL bertanda tangan seperti foto), dan `fields[]` (`key`, `label`, `heard`, `confidence`, `confident`) dalam urutan versi struktur.

`reports.voice` disimpan dengan `NULL` SQL untuk laporan chat; filter memeriksa `jsonb_typeof = 'object'` sehingga baris lama dengan JSON `null` tetap terhitung sebagai bukan suara.

