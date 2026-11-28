# Voice Lab

Analis atau peneliti lab merekam hasil kerjanya dengan suara lewat bot Telegram/WhatsApp; Fluctuz mengubahnya jadi data terstruktur, menanyakan ulang yang ragu, lalu penyelia mengoreksi dan memverifikasi sebelum data diunduh (CSV/Excel). Keputusan **D18** (cakupan MVP) dan **D7** (STT cloud, penyedia belum dipilih). Rencana: ROADMAP Langkah 12.

## Status

| Langkah | Isi | Status |
|---|---|---|
| 12.1 | Lapisan `app/modules/ai/`: STT + pengambil isian | **Ada** |
| 12.2 | Susun isian suara (`voice_cues`, `unit_aliases`, `settings.input_mode`), uji dengan ucapan (`POST /forms/{id}/voice-test`) | **Ada** |
| 12.3 | Voice note di bot → isian terisi sekaligus, `reports.voice` | **Ada** |
| 12.4 | Halaman Voice data asli: `GET /reports?voice=true`, `GET /reports/{id}.voice` | **Ada** |
| 12.5 | Koreksi nilai (alasan wajib) & verifikasi penyelia, jejak audit | **Ada** |
| 12.6 | Unduh CSV/Excel | Belum |
| 12.7 | Penyedia STT/LLM cloud: OpenAI | **Ada** |

## Mengubah suara jadi teks (`app/modules/ai/speech.py`)

`get_speech_to_text().transcribe(audio, content_type, language="id") -> Transcript(text, language, provider, confidence)`. `STT_PROVIDER=fake` (bawaan) membaca byte audio sebagai teks UTF-8 yang diucapkan, untuk pengembangan, simulator `/devtools`, dan tes. `STT_PROVIDER=openai` mentranskripsi dengan `STT_MODEL` (bawaan `gpt-4o-mini-transcribe`) lewat klien OpenAI bersama (`ai/openai_client.py`), dengan petunjuk kosakata laporan lapangan berbahasa Indonesia; transkripsi dipakai untuk **setiap** pesan suara di chat yang punya topik aktif, bukan hanya topik Voice Lab (lihat [conversation-engine.md](conversation-engine.md#jawaban-yang-dibaca-ai-langkah-127)). Penyedia tidak diatur → `503 speech_unavailable`. Tes mengganti penyedia lewat `speech.override`.

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
| Teks singkat yang kebablasan (ada koma atau > 6 kata, mis. "S-9 asamnya netral tujuh, …") | 0,5 | "Sepertinya ikut terbawa kata lain" |
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
5. Laporan menyimpan `reports.voice` = `{transcript, audio, heard{isian: kata}, confidence{isian: 0–1}}`, ditambah `ai_read{isian: teks}` bila AI ikut membaca (di bawah); `report_values` tetap terisi untuk dashboard.

### Kalimat yang dibaca AI (Langkah 12.7)

Aturan `extract` tetap yang pertama membaca. Bila ada isian **wajib** yang tidak terbaca pasti, atau ada nilai yang ragu, mesin menandai `Step.unread_voice` (kunci isian lisan yang belum pasti). Service meminta model (`answers.get_sentence_reader().read_sentence`, skema JSON ketat per isian) menulis ulang nilai yang diucapkan ke bentuk parser, lalu menjalankan mesin sekali lagi dengan `Inbound.ai_values`.

- Nilai yang sudah terbaca pasti oleh aturan **tidak pernah** diganti model.
- Nilai dari model dibaca ulang dengan aturan yang sama (`read_value`: rentang, satuan, opsi); yang tidak lolos dibuang dan isiannya ditanyakan seperti biasa.
- Yang lolos disimpan di `ConversationState.ai_suggested` dan **dikonfirmasi satu per satu**: balasan "Sepertinya juga: pH *6,8* · Suhu *25 °C*. Saya pastikan satu per satu ya.", lalu saat bot sampai di isian itu ia bertanya "Dicatat *6,8*. Benar?" [Ya] [Ubah] alih-alih pertanyaan biasa. "Ubah" → pertanyaan biasa.
- Kalimat yang jelas ("sampel S-2041, pH 6,8, suhu 25 derajat") tidak memanggil model. Isian opsional yang memang tidak disebut tidak memicu panggilan.
- Hanya bila `LLM_PROVIDER=openai` dan Pengaturan agent `read_free_answers` menyala (bawaan). Gagal/mati = perilaku tanpa AI.
- Contoh uji nyata (gpt-5.4-mini): "sampel S-7, pH-nya kira-kira enam koma delapan, suhunya dua puluh lima" → aturan: sampel; model: pH 6,8, suhu 25. "pH tujuh, suhu tiga puluh fahrenheit" → model tidak mengonversi satuan, suhu ditanyakan.

Pengubah suara gagal (penyedia mati) → pesan tidak hilang; bot menjawab "Pesan suara belum bisa saya dengar. Coba kirim ulang, atau ketik hasilnya." Kalimat tanpa isian yang dikenali di langkah suara → contoh kalimat + hitungan gagal (3x → bantuan admin seperti alur chat).

**Mencoba tanpa Telegram:** simulator `/devtools` punya tombol "🎤 Kirim sebagai pesan suara": isi kotak pesan menjadi kata-kata pesan suara (penyedia `fake` membacanya kembali).

## API halaman Voice (Langkah 12.4)

Voice adalah laporan yang diisi dari pesan suara, jadi memakai endpoint laporan (tanpa `/voice` terpisah):

- `GET /reports?voice=true` → hanya laporan bersumber suara (`voice=false` → hanya chat); tiap baris membawa `transcript`.
- `GET /reports/{id}` → bagian `voice` (null untuk laporan chat): `transcript`, `audio_url` + `audio_expires_at` (URL bertanda tangan seperti foto), dan `fields[]` (`key`, `label`, `heard`, `confidence`, `confident`) dalam urutan versi struktur.

`reports.voice` disimpan dengan `NULL` SQL untuk laporan chat; filter memeriksa `jsonb_typeof = 'object'` sehingga baris lama dengan JSON `null` tetap terhitung sebagai bukan suara.

## Koreksi dan verifikasi (Langkah 12.5)

Berlaku untuk semua laporan (bukan hanya Voice), sehingga antrean tinjauan 5.3 nanti tinggal memperluasnya.

- **Koreksi** (`POST /reports/{id}/corrections`, reviewer ke atas): penyelia mengetik nilai yang benar ("26 derajat") dan alasannya. Nilai dibaca dengan `extraction.read_value` (aturan yang sama dengan suara); satuan lain dari satuan isian ditolak ("Satuannya harus °C."). Laporan menyimpan nilai baru; `report_corrections` menyimpan nilai lama, baru, alasan, dan siapa; `audit_logs` mencatat `report.corrected`.
- **Verifikasi** (`POST /reports/{id}/verify`): mengunci laporan (koreksi berikutnya `409`), audit `report.verified`.
- Belum: edit transkrip (desain Alur Voice 6–7), tanda tangan PIN, tolak/minta konfirmasi analis (5.3).

