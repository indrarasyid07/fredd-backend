# Bot Bersama dan Kode Gabung

Status: **Diputuskan sebagian (17 November 2026)**. Tiga keputusan pemilik produk dicatat di [Keputusan pemilik produk](#keputusan-pemilik-produk); sisanya di [pertanyaan terbuka](#pertanyaan-terbuka). Keputusan: [B-048](../11-decisions/decision-log.md). Dampak ke layar: [frontend join-codes.md](https://github.com/indrarasyid07/fredd-frontend/blob/development/docs/06-domain-guides/ui/join-codes.md).

Dokumen ini **menggantikan** model lama "tiap organisasi menghubungkan WhatsApp dan Telegram sendiri lalu mengundang penyuluh lewat nomor". Bagian lain yang bertentangan ditandai di [Dampak ke dokumen lain](#dampak-ke-dokumen-lain).

## Keputusan pemilik produk

| Pertanyaan | Keputusan |
|---|---|
| Kode per struktur data atau per proyek | **Per struktur data** |
| Kode dikirim sekali atau setiap melapor | **Sekali**, dengan konfirmasi saat bergabung bahwa topik itu menjadi tetap, dan konfirmasi pindah atau tambah bila kemudian mengirim kode lain |
| Penyuluh baru langsung aktif atau perlu persetujuan | **Langsung aktif**. Persetujuan manual tetap ada sebagai pilihan per kode |
| Cara menjalankan pilot (sebagian penyuluh) | **Belum diputuskan**, lihat [pertanyaan terbuka](#pertanyaan-terbuka) |

## Keputusan

1. Seluruh platform memakai **satu bot WhatsApp** (satu nomor Cloud API milik Fluctuz) dan **satu bot Telegram**. Organisasi tidak menempel token, tidak menjalankan Embedded Signup, dan tidak memasang webhook.
2. Cara membedakan organisasi dan topik adalah **kode gabung**. Setiap kali sebuah struktur data (topik) dibuat, sistem membuat satu kode otomatis. Admin tidak mengundang orang satu per satu; admin **menampilkan dan membagikan kode itu**.
3. Penyuluh mengirim kode ke bot. Sistem mengikat (*bind*) identitas chat mereka ke organisasi dan struktur data pemilik kode, lalu percakapan pengisian laporan berjalan seperti biasa. Tanpa terikat, bot tidak menyimpan data apa pun.
4. Karena penyuluh yang memulai chat, jendela layanan 24 jam WhatsApp otomatis terbuka. Template `fluctuz_invite` tidak lagi dipakai.

## Kode gabung

| Aspek | Aturan |
|---|---|
| Pemilik | Satu struktur data (`form`). Proyek hanya mengelompokkan; layar proyek menampilkan kode anak-anaknya |
| Dibuat | Otomatis saat struktur data dibuat (status draf). Kode tidak bisa dipakai sebelum struktur berstatus pilot atau aktif; bot membalas "topik belum dibuka" |
| Format | 8 karakter dari alfabet **30** huruf dan angka tanpa karakter mirip (tanpa `I L O U 0 1`: 22 huruf + 8 angka), ditampilkan `K7M2-9QXA`. Acak kriptografis (`secrets`, ±39 bit), bukan turunan nama topik |
| Pencocokan | Tanpa membedakan huruf besar kecil; spasi dan tanda hubung diabaikan; awalan `gabung` atau `kode` boleh ada |
| Status | `active`, `paused` (sementara berhenti menerima orang baru), `revoked` (tidak bisa dipakai lagi) |
| Pembatas opsional | `expires_at`, `max_uses` |
| Persetujuan | `auto` (siapa pun dengan kode langsung aktif) atau `manual` (masuk antrean persetujuan admin) |
| Buat ulang | Kode lama menjadi `revoked`, kode baru dibuat. Penyuluh yang sudah terikat **tetap terikat**; hanya orang baru yang butuh kode baru |
| Satu aktif | Satu struktur hanya punya satu kode `active` pada satu waktu |

## Alur penyuluh

**WhatsApp.** Admin menampilkan kode, tautan, dan QR. Tautan berbentuk `https://wa.me/<nomor Fluctuz>?text=<kode>` sehingga chat terbuka dengan kode terisi. Penyuluh cukup menekan Kirim. Memindai QR, mengetik kode manual, atau menempelkan kode ke chat yang sudah ada sama-sama bisa.

**Telegram.** Tautan `https://t.me/<bot>?start=<kode tanpa tanda hubung>` mengirim `/start <kode>`. Telegram membatasi payload 64 karakter `A-Z a-z 0-9 _ -`; kode kita masuk.

Urutan di sisi sistem:

1. Webhook menerima pesan; sistem mencari `chat_contexts` untuk identitas chat itu.
2. Pesan berisi kode yang dikenali → cek status, `expires_at`, `max_uses`, kuota penyuluh paket organisasi.
3. Buat atau temukan `extension_workers` untuk (`workspace_id`, identitas chat), tambahkan `form_assignments`, naikkan `use_count`, catat `activity_events` (`worker_joined`) dan event realtime.
4. `approval_mode = auto` → balas sambutan dan mulai percakapan. `manual` → status `pending_approval`, balas "Permintaan terkirim ke admin", dan admin melihatnya di Penyuluh › Menunggu persetujuan.
5. Bot meminta **konfirmasi**: "Laporan Anda akan masuk ke topik ini seterusnya. Sudah benar?" dengan tombol **Ya, tetap** dan **Bukan, ganti**. "Bukan, ganti" melepas ikatan baru dan meminta kode lain. Setelah dikonfirmasi, pesan berikutnya tidak perlu kode.
6. Penyuluh yang sudah terikat lalu mengirim kode topik lain: bot bertanya "Pindah ke topik ini, atau tambahkan tanpa melepas yang lama?" dengan tombol **Pindah ke {topik}**, **Tambah topik**, dan **Batal**. Pindah mengubah ikatan aktif dan menandai ikatan lama `left`; tambah membuat ikatan kedua dan memicu aturan di [Satu orang, banyak topik](#satu-orang-banyak-topik).

Contoh pesan (Bahasa Indonesia, mengikuti [chat-ux.md](https://github.com/indrarasyid07/fredd-frontend/blob/development/docs/06-domain-guides/ui/chat-ux.md)):

| Situasi | Balasan |
|---|---|
| Berhasil, otomatis | "Halo Pak Budi! Anda bergabung di **Dinas Pertanian Cianjur · Survei Kondisi Tanaman**. Laporan Anda akan masuk ke topik ini seterusnya. Sudah benar?" [Ya, tetap] [Bukan, ganti] |
| Setelah "Ya, tetap" | "Siap. Saya Fluctuz, asisten yang membantu mencatat laporan lapangan. Kirim foto lahan atau ketik *mulai* untuk melapor." |
| Kode topik lain dari penyuluh yang sudah terikat | "Kode ini untuk **Dinas Peternakan Garut · Catatan Ternak**. Pindah ke topik ini, atau tambahkan tanpa melepas yang lama?" [Pindah ke Catatan Ternak] [Tambah topik] [Batal] |
| Menunggu persetujuan | "Permintaan Anda sudah dikirim ke admin Dinas Pertanian Cianjur. Saya kabari di sini setelah disetujui." |
| Kode tidak dikenal | "Kode tidak dikenali. Periksa kode dari admin Anda, contoh: K7M2-9QXA." |
| Kode dijeda, dicabut, kedaluwarsa, atau penuh | "Kode ini sudah tidak menerima anggota baru. Hubungi admin Anda untuk kode terbaru." |
| Topik belum dibuka | "Survei ini belum dibuka. Coba lagi setelah admin mengaktifkannya." |
| Pesan dari orang yang belum terikat | "Halo! Kirim kode dari admin Anda untuk mulai melapor. Contoh: K7M2-9QXA." |

Pada pesan pertama sistem membaca nama dari profil kanal (WhatsApp `contacts[].profile.name`, Telegram `first_name`) dan bertanya sekali, "Nama Bapak/Ibu untuk laporan ini?", bila struktur memintanya. Admin bisa mengubah nama dan wilayah di halaman Penyuluh.

## Satu orang, banyak topik

Satu nomor atau akun Telegram bisa bergabung ke banyak topik, juga di organisasi berbeda. Setiap pasangan (organisasi, identitas chat) adalah satu `extension_workers`. Aturan routing:

- Terikat ke satu topik aktif → langsung dipakai.
- Terikat ke lebih dari satu → bot menawarkan pilihan topik (nama organisasi dan topik, hanya yang sudah mereka ikuti) di awal laporan baru dan menyimpan pilihan di `chat_contexts`. Kata `topik` atau mengirim kode lain mengganti pilihan.
- Percakapan, laporan, dan foto selalu milik satu `workspace_id`. Organisasi A tidak pernah melihat pesan yang berkaitan dengan organisasi B.

## Model data

Perubahan terhadap [data-model.md](../04-database/data-model.md):

| Tabel | Perubahan |
|---|---|
| `channels` | Menjadi konfigurasi **platform**: `type`, `status`, `display_name`, `phone_number_id` atau `bot_username`. `workspace_id` boleh `NULL` (bot platform); kredensial tidak lagi di tabel ini, tetapi di rahasia lingkungan (lihat [security-model.md](../05-security-and-access/security-model.md)) |
| `join_codes` (baru) | `id`, `workspace_id`, `form_id`, `code` (unik, huruf besar, tanpa tanda hubung), `status`, `approval_mode`, `expires_at`, `max_uses`, `use_count`, `created_by`, `created_at`, `revoked_at`. Indeks unik parsial satu `active` per `form_id` |
| `extension_workers` | Dibuat saat klaim kode, bukan saat undangan. Tambah `status` `pending_approval` / `active` / `left` / `blocked`, `joined_via_code_id`, `joined_at`, `confirmed_at` (saat penyuluh menekan "Ya, tetap"), `display_name_source` (`channel_profile` atau `admin`). Ikatan yang belum dikonfirmasi tidak menerima laporan |
| `extension_worker_invites` | **Dihapus**. Digantikan `join_codes` |
| `chat_contexts` (baru) | `channel_id`, `chat_id`, `extension_worker_id` (topik aktif), `updated_at`. Unik per (`channel_id`, `chat_id`) |
| `conversations`, `messages` | Tidak berubah; `channel_id` menunjuk kanal platform |

Kuota penyuluh paket ([billing-and-plans.md](billing-and-plans.md)) dihitung dari `extension_workers.status = 'active'` per organisasi. Bila kuota penuh, klaim kode berakhir di `pending_approval` dengan alasan `quota`.

## Status implementasi (Langkah 2.7)

- Modul `app/modules/join_codes/` + tabel `join_codes` (kolom di atas; indeks unik parsial: satu kode tidak dicabut per form). Kode dibuat otomatis oleh `forms.service.create_form` lewat `join_codes.service.create_for_form` (dalam unit kerja yang sama); form lama mendapat kode lewat migrasi.
- `GET/PATCH /forms/{id}/join-code` ada. `claimable` = kode `active` dan form `pilot`/`active`. Tautan bagikan dari env `TELEGRAM_BOT_USERNAME` (`https://t.me/<bot>?start=<KODE>`) dan `WHATSAPP_PUBLIC_NUMBER` (`https://wa.me/<nomor>?text=GABUNG%20<KODE>`); kosong = null.
- Buat ulang: `POST /forms/{id}/join-code/rotate` (Langkah 3.10), pengaturan ikut ke kode baru. `GET /bots` untuk kartu bot bersama.

## Status implementasi (Langkah 3.6, Telegram)

- Klaim di `app/modules/conversations/joining.py`; cek kode di `join_codes.service.find_claimable` (`unknown` / `closed` / `not_open`), hitungan pakai atomik `take_use` (`UPDATE … WHERE status='active' AND belum kedaluwarsa AND use_count < max_uses`), penyuluh dan topik di `extension_workers.service.join`.
- Kode dikenali dari `/start <kode>`, `gabung`/`kode <kode>`, `K7M2-9QXA`, atau 8 karakter polos. Di chat yang **sudah punya topik**, 8 karakter polos dianggap jawaban (mungkin nama); kode harus bertanda hubung/spasi atau berawalan.
- Bergabung: penyuluh dibuat/dihidupkan lagi (`left`/`unreachable` → aktif), `form_assignments` dibuat/diaktifkan, `conversations.status = joining`, `chat_contexts` menunjuk ikatan baru, audit `extension_worker.joined`. Balasan menyebut **organisasi · topik** + kalimat persetujuan data + tombol `join:keep` / `join:change`.
- "Ya, tetap" → percakapan `idle`, `confirmed_at` terisi. "Bukan, ganti" → ikatan `left` (penyuluh `left` bila tidak punya topik lain), `chat_contexts` dikosongkan, audit `extension_worker.left_topic`. Tombol konfirmasi lama → "Pilihan ini sudah kedaluwarsa".
- Kode topik lain dari chat yang sudah punya topik → tombol `join:switch` / `join:add` / `join:cancel`. Pilihan yang menunggu disimpan di Redis `join-choice:{channel}:{chat}` selama 24 jam dan dipakai sekali. Pindah = ikatan lama `left`; tambah = dua ikatan aktif, `chat_contexts` menunjuk yang baru. Kode topik yang sama → "Anda sudah tergabung".
- `approval_mode = manual` → penyuluh `pending_approval` (`pending_reason = manual`), tanpa `chat_contexts`; pesan berikutnya dibalas "Permintaan Anda sudah dikirim ke admin …". Penyuluh `blocked` mendapat balasan kode tertutup (alasan tidak disebut).
- Kepemilikan pesan: setelah diproses, pesan masuk dan balasannya diberi `workspace_id` + `conversation_id` dari topik aktif chat (ditentukan setelah routing, jadi pesan kode yang membuat bergabung ikut menjadi milik topik itu). Chat tanpa topik tetap `NULL`. Pindah topik hanya memengaruhi pesan berikutnya.
- Rate limit tebakan: Redis `join-wrong:{channel}:{chat}`; 5 kode tak dikenal per jam dibalas, setelah itu chat tanpa topik didiamkan sampai jendela habis.
- Kalimat persetujuan (UU PDP) **draf, menunggu persetujuan pemilik produk**: "Data laporan Anda dikelola oleh {organisasi} sebagai pengendali data, dengan Fluctuz sebagai pemroses data. Kebijakan privasi: {PRIVACY_POLICY_URL}" (tautan dihilangkan bila env kosong; halaman Kebijakan Privasi belum ada di frontend).
- Belum: kuota penyuluh per paket (menunggu billing), `activity_events`/event realtime `worker_joined` (Langkah 4), WhatsApp.

## Status implementasi (Langkah 4.6, persetujuan admin)

- `GET /extension-workers?status=pending_approval` (reviewer) menampilkan antrean beserta topik terbaru dan kode yang dipakai.
- `POST /extension-workers/{id}/approve` (admin): penyuluh `active`, `pending_reason` dikosongkan, audit `extension_worker.approved`. Topik terbaru dibuka di chat (`chat_contexts`, `conversations.status = joining`) dan bot mengirim "Halo {nama}! Permintaan Anda sudah disetujui admin {organisasi}. Anda bergabung di **organisasi · topik**… Sudah benar?" + kalimat persetujuan data + tombol `join:keep` / `join:change`, sehingga alur konfirmasi sama dengan bergabung otomatis. Bila chat sudah punya topik lain, topik itu tidak diganti; bot mengabarkan persetujuan dan meminta kode dikirim lagi untuk pindah/tambah. Pesan dikirim lewat job `conversations.deliver`.
- `POST /extension-workers/{id}/block` (admin): penyuluh `blocked`, audit `extension_worker.blocked`, tanpa pesan. Chat itu lalu mendapat balasan "kirim kode" biasa; kode organisasi ini dibalas "kode tertutup".
- Hanya penyuluh `pending_approval` yang bisa disetujui (`409 extension_worker_not_pending`). Sejak 4.4 penyuluh aktif juga bisa diblokir (topiknya berakhir, chat kehilangan topik) dan blokir bisa dibuka (`left`, bergabung lagi lewat kode).
- Kuota (`pending_reason = quota`) belum diperiksa saat menyetujui (menunggu billing).

## Endpoint

Menggantikan `/extension-workers/invites*` dan `/channels*` di [endpoints.md](../03-api/endpoints.md):

| Method | Path | Akses | Catatan |
|---|---|---|---|
| GET | `/forms/{id}/join-code` | reviewer / admin | Kode aktif, status, penggunaan, tautan WhatsApp dan Telegram |
| PATCH | `/forms/{id}/join-code` | admin | `status`, `approval_mode`, `expires_at`, `max_uses` |
| POST | `/forms/{id}/join-code/rotate` | admin | Cabut kode lama, buat baru |
| GET | `/extension-workers?status=pending_approval` | reviewer / admin | Antrean persetujuan |
| POST | `/extension-workers/{id}/approve`, `/block` | admin | Dicatat di `audit_logs` |
| GET | `/bots` | semua anggota | Hanya baca: nomor WhatsApp publik, username Telegram, status. Untuk ditampilkan di panduan |
| POST | `/webhooks/whatsapp`, `/webhooks/telegram` | tanda tangan | Satu URL per platform (tanpa `{channel_id}`) |

## Keamanan dan penyalahgunaan

Kode adalah rahasia tingkat undangan: siapa pun yang memilikinya bisa bergabung. Pengendalinya:

- 40 bit acak; **rate limit tebakan** 5 kode salah per jam per identitas chat, lalu bot diam selama satu jam; pembatas global per IP webhook tidak tersedia, jadi batas dipasang juga per `phone` dan per `telegram_chat_id`.
- Kode tidak pernah muncul di URL halaman web yang bisa di-cache; hanya ditampilkan ke admin dan reviewer organisasi itu.
- `approval_mode = manual`, `max_uses`, `expires_at`, `paused`, dan buat ulang adalah rem darurat bila kode bocor. Laporan dari penyuluh baru tetap melewati aturan `needs_review`.
- Pencabutan kode tidak mengeluarkan penyuluh yang sudah terikat; admin memblokir orang lewat `blocked`.
- Setiap klaim, persetujuan, pemblokiran, dan pembuatan ulang kode masuk `audit_logs`.
- Isolasi tenant diuji khusus: pesan dari identitas chat tanpa ikatan tidak boleh membuat percakapan, laporan, atau media di organisasi mana pun.

## Batas bersama satu bot

Memakai satu bot berarti **semua organisasi berbagi batas yang sama**:

| Kanal | Batas | Konsekuensi |
|---|---|---|
| WhatsApp | Tingkat pesan percakapan harian per nomor, peringkat kualitas nomor, throughput | Satu organisasi yang mengirim pengingat berlebihan menurunkan kualitas nomor untuk semua. Wajib rate limit pengingat per organisasi dan batas frekuensi per penyuluh |
| WhatsApp | Template (`fluctuz_intro`, `fluctuz_resume`, `fluctuz_reminder`) | Diajukan sekali untuk seluruh platform; `fluctuz_invite` dihapus |
| Telegram | ~30 pesan per detik per bot, 1 pesan per detik per chat | Antrean pengiriman global dengan prioritas; pengumuman massal dijadwalkan |
| Biaya | Meta menagih Fluctuz, bukan organisasi | Biaya template dihitung di `usage_counters` dan masuk harga paket |

Verifikasi bisnis Meta dan satu WABA menjadi tanggung jawab Fluctuz, bukan admin organisasi. Ini menghapus layar Embedded Signup dari produk.

## Dampak ke dokumen lain

| Dokumen | Yang berubah |
|---|---|
| [messaging-channels.md](messaging-channels.md) | Hubungkan kanal per organisasi dihapus; webhook satu per platform; template undangan dihapus |
| [conversation-engine.md](conversation-engine.md) | Langkah 1 menjadi "kenali ikatan atau terima kode"; state `joining` |
| [data-model.md](../04-database/data-model.md) | Tabel pada bagian Model data |
| [endpoints.md](../03-api/endpoints.md) | Endpoint pada bagian Endpoint |
| [security-model.md](../05-security-and-access/security-model.md) | Rahasia bot di tingkat platform; bagian kode gabung |
| [glossary.md](glossary.md) | `join_code`, `bot`, `binding` |
| [product-overview.md](../01-product-and-scope/product-overview.md) | Langkah Persiapan |

## Pertanyaan terbuka

Jawaban atas ini mengubah rancangan; usulan bawaan ada di kolom kedua.

| # | Pertanyaan | Usulan bawaan |
|---|---|---|
| 1 | ~~Kode per struktur data atau per proyek?~~ | **Diputuskan: per struktur data** |
| 2 | ~~Sekali atau setiap melapor?~~ | **Diputuskan: sekali, dengan konfirmasi tetap atau pindah** |
| 3 | ~~Persetujuan bawaan?~~ | **Diputuskan: langsung aktif**, manual sebagai pilihan |
| 4 | Pilot (sebagian penyuluh): bagaimana dijalankan dengan kode? | Belum diputuskan. Opsi A: `max_uses` sebagai ukuran pilot lalu dinaikkan setelah lolos ambang. Opsi B: dua kode untuk satu struktur (pilot dan umum). Opsi C: persetujuan manual untuk memilih orang pilot. Perlu dipilih bersama alur publikasi di [forms.md](https://github.com/indrarasyid07/fredd-frontend/blob/development/docs/06-domain-guides/ui/forms.md) |
| 4b | Penyuluh dengan banyak topik: memilih tiap laporan atau memakai topik terakhir? | Memilih di awal laporan bila lebih dari satu |
| 5 | Perlukah daftar putih nomor untuk topik sensitif (hanya nomor yang didaftarkan admin boleh bergabung)? | Ditunda; satu opsi `restricted` untuk paket Enterprise |
| 6 | Perlukah opsi bot sendiri (nomor atau bot milik organisasi) untuk Enterprise? | Ya, nanti; `channels.workspace_id` yang tidak `NULL` menyiapkan jalannya |
| 7 | Siapa menanggung biaya pesan template Meta? | Fluctuz, dimasukkan ke harga paket dan dibatasi kuota |
