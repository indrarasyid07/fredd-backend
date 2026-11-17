# Billing and Plans

Sumber: halaman canvas "Upgrade" (Perorangan, Organisasi). Spesifikasi layar: [frontend ui/upgrade.md](https://gitlab.com/databiota-fredd/frontend/-/blob/development/docs/06-domain-guides/ui/upgrade.md).

Fluctuz dijual sebagai SaaS dengan paket per workspace. Setiap workspace bertipe **Perorangan** atau **Organisasi** dan punya satu langganan aktif.

## Paket (dari desain)

| Kode | Tipe | Harga bulanan | Harga tahunan | Pengguna/anggota | Formulir aktif | Laporan/bulan | Fitur tambahan |
|---|---|---|---|---|---|---|---|
| `free` | personal | Rp0 | Rp0 | 1 | 1 | 50 | Telegram atau WhatsApp, foto & lokasi, dashboard dasar |
| `plus` | personal | Rp49.000 | Rp529.200 | 1 | 3 | 300 | Ringkasan AI, ekspor laporan, kuota transkripsi suara |
| `starter` | organization | Rp250.000 | Rp2.700.000 | 5 | 3 | 300 | Dashboard bersama, WhatsApp & Telegram, logika & validasi |
| `growth` | organization | Rp750.000 | Rp8.100.000 | 20 | 10 | 1.500 | Beberapa admin, analisis tren lintas wilayah, ekspor lengkap, alur verifikasi |
| `enterprise` | organization | kontrak | kontrak | kustom | kustom | kustom | Integrasi sistem, akses lanjutan, dukungan khusus, SLA |

- Tahunan = 12 × bulanan − 10%.
- Harga Plus "per pengguna"; paket Organisasi "per organisasi".
- "Formulir" di halaman Upgrade = struktur data (`form`). Yang dihitung adalah formulir berstatus aktif atau pilot.

Harga, batas, dan fitur disimpan di database (tabel `plans`), bukan di kode, agar bisa diubah tanpa deploy. Nilai di atas menjadi seed awal.

## Kuota dan fitur

| Batas | Dihitung dari | Kapan diperiksa |
|---|---|---|
| Pengguna/anggota | `members` aktif + undangan menunggu | Saat mengundang anggota |
| Formulir aktif | `forms` dengan status `active` atau `pilot` | Saat publikasi atau mulai pilot |
| Laporan per bulan | `reports` dibuat sejak awal periode tagihan | Saat laporan dikirim penyuluh |
| Transkripsi suara | Detik audio yang ditranskripsi per periode | Saat pesan suara diproses |

Fitur per paket disimpan sebagai daftar flag (`ai_summary`, `export`, `voice_transcription`, `multiple_admins`, `trend_analysis`, `report_review`, `integrations`). Backend memeriksa flag lewat satu dependency `require_feature("export")`; frontend menyembunyikan atau mengunci tombol berdasarkan data yang sama dari `/auth/me`.

Periode kuota laporan mengikuti tanggal tagihan ("diatur ulang setiap tanggal tagihan"). Untuk paket Gratis, periode dimulai dari tanggal workspace dibuat.

### Perilaku saat kuota habis (usulan, perlu persetujuan)

- **Laporan penyuluh tetap diterima dan disimpan**, karena data lapangan tidak boleh hilang. Laporan di atas kuota ditandai `over_quota` dan tidak tampil di dashboard sampai paket dinaikkan atau periode berganti.
- Admin diberi peringatan di 80% dan 100% (dashboard + email).
- Fluctuz tidak memberi tahu penyuluh soal kuota; urusan paket hanya antara admin dan Fluctuz.
- Membuat formulir atau mengundang anggota melebihi batas ditolak dengan error `plan_limit_reached` dan tautan ke halaman Upgrade.

## Pembayaran

- Penyedia belum dipilih. Kandidat untuk Rupiah: Midtrans, Xendit (mendukung VA bank, e-wallet, QRIS, kartu).
- Pakai **halaman checkout hosted** penyedia. Fluctuz tidak pernah menerima atau menyimpan data kartu.
- Status langganan hanya berubah dari **webhook penyedia** yang tanda tangannya terverifikasi (`POST /webhooks/payments/{provider}`), bukan dari redirect browser.
- Webhook idempoten berdasarkan ID transaksi penyedia.
- Langganan berulang: bila penyedia tidak mendukung auto-debit untuk metode tertentu, kirim tagihan baru sebelum jatuh tempo dan beri masa tenggang 7 hari sebelum turun ke Gratis.
- Turun paket berlaku di akhir periode; naik paket berlaku langsung (selisih prorata atau mulai periode baru, diputuskan bersama penyedia).
- Faktur/kuitansi dan kebutuhan pajak (PPN) perlu dikonfirmasi dengan pemilik bisnis.

## Model data

| Tabel | Kolom penting |
|---|---|
| `plans` | code, type (`personal`/`organization`), name, monthly_price_idr, yearly_price_idr, limits JSONB (`members`, `active_forms`, `reports_per_month`, `voice_seconds`), features text[], is_public, sort_order |
| `subscriptions` | workspace_id, plan_code, billing_cycle (`monthly`/`yearly`), status (`active`, `past_due`, `canceled`, `trialing`), current_period_start, current_period_end, cancel_at_period_end, provider, provider_subscription_id |
| `payments` | subscription_id, provider, provider_transaction_id (unik), amount_idr, status, paid_at, raw JSONB |
| `usage_counters` | workspace_id, period_start, reports_count, voice_seconds; diperbarui di transaksi yang sama dengan pembuatan laporan |

`workspaces` mendapat kolom `type` (`personal`/`organization`).

## Endpoint

| Method | Path | Peran |
|---|---|---|
| GET | `/billing/plans?type=` | publik (juga untuk halaman harga di website) |
| GET | `/billing/subscription` | login |
| GET | `/billing/usage` | login |
| POST | `/billing/checkout` | admin (body: plan_code, billing_cycle) → URL checkout penyedia |
| POST | `/billing/cancel` | admin |
| POST | `/webhooks/payments/{provider}` | penyedia, tanda tangan wajib |

## Pertanyaan terbuka

1. Penyedia pembayaran dan siapa pemilik akun merchant.
2. Perilaku kuota habis (usulan di atas) perlu disetujui.
3. Faktur, PPN, dan nama badan usaha di kuitansi.
4. Apakah satu pengguna bisa memiliki workspace Perorangan dan Organisasi sekaligus.
5. Uji coba gratis untuk paket Organisasi (status `trialing`) atau tidak.
