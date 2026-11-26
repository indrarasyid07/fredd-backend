# Struktur data (forms)

Struktur data = daftar isian yang ditanyakan Fluctuz satu per satu di chat, plus aturan JIKA/MAKA. Dokumen ini adalah **kontrak antarmuka 2** (TEAM-WORKFLOW): mesin percakapan (Domain 3) dan laporan (Domain 4) membaca `FormDefinition`; perubahan bentuknya di-review pemilik kedua domain itu.

Kode: `app/modules/forms/` (`schemas.py` = `FormDefinition`, `service.py` = antarmuka untuk domain lain). Endpoint `/forms` menyusul di Langkah 2.3; sampai saat itu `FormDefinition` diterbitkan di `openapi.json` lewat `include_schemas` di `app/main.py` agar frontend bisa generate tipenya.

## Tabel

- `forms`: satu per struktur data. `status` `draft → pilot → active → archived`. `current_version_id` = versi terbit yang dipakai percakapan baru (kosong sampai publikasi pertama).
- `form_versions`: definisi bernomor (`version` 1, 2, ...). `published_at` kosong = **draf** yang masih bisa diubah, paling banyak satu per form (indeks unik parsial). Setelah dipublikasikan tidak pernah diubah, karena laporan menunjuk versinya. Mengubah struktur yang sudah terbit = membuat draf versi berikutnya.
- Kedua tabel membawa `workspace_id`; setiap query difilter dengannya.

## Wizard dan draf (Langkah 2.3)

- `POST /forms` membuat form `draft` dengan versi 1 sebagai draf; `PATCH /forms/{id}` adalah autosave wizard: `name`, `description`, `definition` (mengganti seluruh definisi draf), `settings` (mengganti seluruh pengaturan). Form tanpa versi draf → `409 form_not_editable`. Penyimpanan bersamaan untuk form yang sama diproses bergantian (kunci baris), yang terakhir menang.
- Draf disimpan sebagai **`DraftFormDefinition`**: bentuknya sama dengan `FormDefinition` dan bentuk tetap diperiksa (tipe, pola `key`, properti tak dikenal), tetapi label/pertanyaan boleh kosong, isian boleh 0, dan aturan antar-isian belum diperiksa. Kelengkapan diperiksa `FormDefinition` saat validasi/publikasi (2.5/2.6).
- `forms.settings` (`FormSettings`): `template_code`, `sector_code`, `province_id` + `regency_ids` (wilayah kerja dari `reference_data`: provinsi platform dan, opsional, kab/kota di dalamnya; kosong = seluruh provinsi; id lain → `422 unknown_region` dengan `field` bertitik), `commodities`, `frequency` (`daily`/`weekly`/`event`), `input_mode` (lihat di bawah). `agent_style`, `voice_to_text`, dan `blur_retry` masih ada di skema agar draf lama tetap terbaca, tetapi **tidak dipakai bot**: gaya bicara dan pesan suara diatur sekali per organisasi di [Pengaturan agent](conversation-engine.md#pengaturan-agent), dan foto buram diberi catatan AI untuk peninjau, bukan diminta ulang.
- Katalog template (`GET /form-templates`): tabel platform `form_template_sectors` dan `form_templates`, seed `templates`. Isian awal tetap diturunkan wizard dari `description` template.

## Publikasi dan arsip (Langkah 2.6)

- `POST /forms/{id}/publish` (admin): menjalankan pemeriksaan yang sama dengan `validate`; bila masih ada masalah → `422 form_has_problems` (pesan menyebut jumlahnya). Bila lolos, definisi draf disimpan ulang dalam bentuk `FormDefinition` yang dinormalkan, `published_at`/`published_by_user_id` diisi, `forms.current_version_id` menunjuk versi itu, status `active`, dan dicatat di audit log (`form.publish`, `{name, version}`). Versi terbit tidak pernah diubah; setelah publikasi form tidak punya draf, jadi `PATCH` → `409 form_not_editable` sampai struktur dibuka lagi (lihat di bawah).
- `POST /forms/{id}/archive` (admin): status `archived`, audit `form.archive`, idempoten. Form arsip tidak bisa diubah (`409 form_archived`) atau dipublikasikan. Laporan yang sudah ada tetap.
- `FormOut` menyertakan `current_version` dan `published_at` untuk daftar struktur.

## Mengubah struktur yang sudah aktif

- `POST /forms/{id}/draft` (form_editor) membuat draf versi berikutnya (nomor tertinggi yang pernah dipakai + 1) yang isinya salinan versi aktif. Draf itu diubah lewat autosave `PATCH /forms/{id}`, diperiksa dengan `validate`, dan diterbitkan dengan `publish` seperti draf pertama. Bila draf sudah terbuka, draf itu yang dikembalikan (idempoten). Form diarsipkan → `409 form_archived`. Audit `form.draft_opened` (`from_version`, `version`).
- Selama draf terbuka, status form tetap `active` dan percakapan memakai `current_version_id` seperti biasa; `FormOut` menunjukkan keduanya (`current_version` dan `draft_version`).
- Setelah draf terbit: laporan **berikutnya** memakai versi baru; laporan yang sedang diisi selesai dengan versinya (`conversations.form_version_id`, lihat [conversation-engine.md](conversation-engine.md#alur-laporan-di-chat-langkah-37)); laporan lama tetap menunjuk versi saat dibuat. Kode gabung dan penyuluh yang sudah bergabung tidak berubah.
- `DELETE /forms/{id}/draft` (form_editor) membuang draf; versi aktif tidak berubah. Audit `form.draft_discarded`. Form yang belum pernah terbit hanya punya draf itu → `409 draft_is_only_version` (arsipkan bila tidak dipakai). Menghapus draf aman: laporan dan percakapan hanya menunjuk versi terbit.
- Dasbor: tombol "Ubah" di daftar Struktur Data membuka wizard pada draf baru; "Lanjutkan perubahan" / "Buang perubahan" saat draf terbuka; langkah 7 menjadi "Terbitkan vN".

## Pemeriksaan otomatis (Langkah 2.5)

`POST /forms/{id}/validate` memeriksa draf dan **selalu menjawab 200** (masalah adalah data, bukan permintaan yang gagal): `{valid, errors[], warnings[]}`, tiap item `{code, message, field}` dengan `field` bertitik relatif terhadap definisi (`fields.2.question`, `fields.3.options.1.label`, `rules.0.then.require`; kosong = seluruh struktur). Semua masalah dilaporkan sekaligus (`find_problems` di `schemas.py`, di atas `DraftFormDefinition`): isian kosong (`no_fields`, `label_required`, `question_required`, `option_label_required`), plus semua aturan `FormDefinition` di bawah, termasuk `duplicate_field_label` dan `duplicate_option_label` (kunci dibuat dari label, jadi label kembar tidak tertangkap oleh pemeriksaan kunci). Peringatan tidak menghalangi publikasi: `no_condition_field` (tidak ada isian berperan `condition`). Label pilihan di draf juga boleh kosong.

## `FormDefinition`

```
{ "fields": [FieldDefinition, ...1–50], "rules": [Rule, ...0–50] }
```

`key` isian dan `value` pilihan: Inggris, `^[a-z][a-z0-9_]*$`, ≤ 50 karakter, stabil (dipakai `reports.answers` dan analitik). `label`, `question`, label pilihan: Bahasa Indonesia. Properti yang tidak dikenal ditolak.

### Tipe isian (12)

| `type` | UI wizard | `min`/`max` berarti | Cara menjawab (`answer_modes`) |
|---|---|---|---|
| `short_text` | Teks pendek | – | `type`, `voice` |
| `long_text` | Teks panjang | – | `type`, `voice` |
| `number` | Angka | nilai | `type`, `range`, `voice` |
| `single_choice` | Pilihan tunggal | – | `type`, `choose`, `voice` |
| `multi_choice` | Beberapa pilihan | jumlah pilihan | `type`, `choose`, `voice` |
| `datetime` | Tanggal & jam | – | `type`, `pick` |
| `location` | Lokasi GPS | – | `name`, `map`, `live`, `voice` |
| `photo` | Foto | jumlah foto | `send`, `camera` |
| `video` | Video | jumlah video | `send`, `camera` |
| `voice` | Pesan suara | – | `send` |
| `document` | Struk / dokumen | jumlah berkas | `photo`, `file` |
| `signature` | Tanda tangan | – | `draw` |

`answer_modes` kosong = semua cara untuk tipe itu boleh.

### Properti isian

| Properti | Berlaku untuk | Arti |
|---|---|---|
| `required` (bawaan `true`) | semua | Wajib dijawab sebelum laporan selesai |
| `min`, `max` | lihat tabel tipe | Batas nilai atau jumlah; `min ≤ max`; jumlah tidak boleh negatif |
| `review_above` | `number` | Jawaban di atas nilai ini masuk antrean tinjauan |
| `unit` | `number` | Satuan tampilan (`ha`, `kg`, `Rp`) |
| `options` | `single_choice`, `multi_choice` (wajib ≥ 2, ≤ 30, `value` unik) | `{value, label, color?}`; `color` `#RRGGBB` dipakai peta |
| `max_accuracy_m` | `location` | Titik dengan akurasi lebih buruk diminta ulang |
| `voice_cues` | jenis yang bisa diucapkan (teks, angka, pilihan, tanggal) | Voice Lab (12.2): sebutan lain isian saat diucapkan ("sampel", "kode sampel"); maks. 10 × 60 karakter; jenis lain → `voice_cues_not_allowed` |
| `unit_aliases` | `number` | Voice Lab (12.2): kata yang diucapkan untuk satuannya ("derajat" untuk °C); jenis lain → `unit_aliases_not_allowed` |
| `role` | lihat bawah | Arti isian bagi dashboard |

### Peran isian (`role`)

`condition` dan `area` paling banyak satu isian per struktur; `status` dan `measure` boleh lebih dari satu (D17, Langkah 4.7).

| `role` | Syarat | Dipakai untuk |
|---|---|---|
| `condition` | `single_choice`, nilai pilihan hanya `healthy`, `attention`, `infected` (D2, B-052) | `reports.condition`, warna peta, KPI kondisi |
| `area` | `number`, `unit` kosong atau `ha` | `reports.area_ha`, total luas |
| `status` | `single_choice` atau `multi_choice` (kode masalah `status_not_choice`) | Widget komposisi bawaan di dashboard per struktur (mis. status sampel, jenis penyakit) |
| `measure` | `number` (kode masalah `measure_not_number`) | Widget angka bawaan (rata-rata, jumlah, terendah, tertinggi; mis. pH, suhu, ekor ternak, Rp) |

Peran hanya **petunjuk tata letak**: semua jawaban pilihan dan angka, berperan atau tidak, disalin ke `report_values` saat laporan dibuat, sehingga widget bisa diarahkan ke isian mana pun.

### Aturan JIKA/MAKA (`rules`)

```json
{ "if": { "field": "condition", "equals": "infected" }, "then": { "require": "photos", "needs_review": false } }
```

- `if.field` harus isian yang ada. Untuk isian pilihan, `equals` harus salah satu `value`-nya; untuk `multi_choice` artinya "termasuk pilihan ini".
- `then` butuh minimal satu tindakan: `require` (isian lain menjadi wajib, bukan isian pemicunya sendiri) dan/atau `needs_review: true` (laporan masuk antrean tinjauan).

## Galat validasi

Definisi yang tidak valid menghasilkan `422 validation_error` dengan **satu item `errors[]` per masalah**, `field` bertitik relatif terhadap body (mis. `definition.fields.2.options`). Kode berikut tidak boleh diubah setelah dipakai frontend:

| `code` | Arti |
|---|---|
| `duplicate_field_key` / `duplicate_field_label` | Dua isian memakai `key` / nama yang sama |
| `no_fields` / `label_required` / `question_required` / `option_label_required` | Belum ada isian / nama isian, pertanyaan, atau nama pilihan kosong (pemeriksaan 2.5) |
| `options_too_few` / `options_not_allowed` / `duplicate_option` / `duplicate_option_label` | Pilihan kurang dari 2 / ada di isian bukan pilihan / `value` ganda / nama pilihan ganda |
| `bounds_not_allowed` / `invalid_range` / `negative_count` | `min`/`max` di tipe yang tidak memakainya / `min > max` / jumlah negatif |
| `review_above_not_allowed` / `unit_not_allowed` / `accuracy_not_allowed` | Properti di tipe yang salah |
| `invalid_answer_mode` | Cara menjawab tidak berlaku untuk tipenya, atau ganda |
| `duplicate_role` / `condition_not_single_choice` / `area_not_number` / `invalid_condition_value` / `invalid_area_unit` | Pelanggaran syarat peran |
| `unknown_field` / `unknown_option` / `empty_rule_action` / `self_reference` | Aturan merujuk isian/pilihan yang tidak ada, tanpa tindakan, atau mewajibkan pemicunya sendiri |

Galat bentuk (tipe salah, properti tidak dikenal, pola `key`) memakai kode umum dari [api-conventions.md](../03-api/api-conventions.md).

## Antarmuka untuk domain lain (`forms.service`)

| Fungsi | Hasil |
|---|---|
| `get_version_definition(db, workspace_id, version_id, published_only=True)` | `VersionDefinition(form_id, version_id, version, published, definition)`; draf dianggap tidak ada kecuali `published_only=False` (langkah Uji di wizard) |
| `get_form(db, workspace_id, form_id)` | `Form`, atau `FormNotFound` (404) untuk form workspace lain |
| `create_form(db, workspace_id, user_id, name, definition, description=None)` | Form `draft` dengan versi 1 sebagai draf; juga untuk fixture tes domain lain |

`FormDefinition.field_with_role("condition")` dan `.field(key)` membantu mesin dan laporan menemukan isian. Contoh definisi untuk tes: `tests/form_definitions.py` (`crop_survey()`).

## Mode masukan (`settings.input_mode`, Voice Lab 12.2)

`chat` (bawaan): bot menanyakan isian satu per satu. `voice`: satu pesan suara mengisi banyak isian sekaligus dan hanya nilai yang ragu ditanyakan ulang (alur bot di Langkah 12.3). Admin mencoba kalimat dengan `POST /forms/{id}/voice-test` (panel "Uji dengan ucapan" di wizard).
