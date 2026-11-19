# Data Model

PostgreSQL. Nama tabel dan kolom dalam Bahasa Inggris, `snake_case`, tabel jamak.

## Konvensi

- Primary key `id UUID` (v7, urut waktu). Kode tampilan terpisah bila perlu.
- Semua tabel milik tenant punya `workspace_id` dan setiap query difilter dengannya.
- `created_at`, `updated_at` `timestamptz` (UTC).
- Penamaan constraint mengikuti `naming_convention` SQLAlchemy agar migrasi Alembic stabil.
- Enum disimpan sebagai `text` + `CHECK`, bukan tipe enum Postgres (mudah diubah).
- Migrasi dengan Alembic; file diberi nama `YYYY-MM-DD_<slug>.py`.

## Tabel inti

| Tabel | Kolom penting | Catatan |
|---|---|---|
| `workspaces` | name, type (`personal`/`organization`), personal_owner_id (unik; wajib untuk `personal`, kosong untuk `organization`), timezone (`Asia/Jakarta`), operating_hours JSONB, quiet_hours JSONB, retention_conversations_months (12), retention_photos_months (24), require_sso, settings JSONB | Satu workspace Perorangan per user; Organisasi tidak dibatasi (B-049) |
| `users` | email (unik, huruf kecil), name, password_hash (null bila hanya Google), email_verified_at, google_sub (unik), organization, created_at, updated_at | Rincian: [auth.md](../06-domain-guides/auth.md#tabel) |
| `members` | workspace_id, user_id, role (`admin`, `form_editor`, `reviewer`), approved_at | Unik (workspace_id, user_id). `approved_at` kosong = belum disetujui, tanpa akses |
| `sessions` | user_id, token_hash (unik), user_agent, ip, created_at, last_seen_at, expires_at, revoked_at | Token mentah hanya di cookie; `city` untuk halaman Keamanan diturunkan dari IP saat ditampilkan |
| `channels` | type (`whatsapp`, `telegram`), status, display_name, phone_number_id / bot_username, workspace_id (`NULL` = bot platform) | Bot bersama; kredensial di rahasia lingkungan, bukan di tabel ([join-codes.md](../06-domain-guides/join-codes.md)) |
| `join_codes` | workspace_id, form_id, code (unik), status (`active`, `paused`, `revoked`), approval_mode (`auto`, `manual`), expires_at, max_uses, use_count, created_by, revoked_at | Satu `active` per form; dibuat otomatis saat form dibuat |
| `chat_contexts` | channel_id, chat_id, extension_worker_id, updated_at | Topik aktif per identitas chat; unik (channel_id, chat_id) |
| `extension_workers` | workspace_id, name, region_id, phone_e164, telegram_chat_id, joined_via_code_id, joined_at, status (`pending_approval`, `active`, `blocked`) | Dibuat saat klaim kode. Unik per workspace: phone, telegram_chat_id |
| ~~`extension_worker_invites`~~ | - | Dihapus (B-048); digantikan `join_codes` |
| `reference_data` | workspace_id (kosong = data platform), type (`region`, `commodity`, `farmer_group`, `unit`), code, value, aliases text[], parent_id, level (`province`, `regency`, `district`, `village`; wilayah saja), centroid `geometry(Point,4326)`, boundary `geometry(MultiPolygon,4326)` + GiST | Alias untuk mencocokkan kata lokal; wilayah membentuk pohon lewat `parent_id`, kode Kemendagri di `code`. Unik (type, code) untuk baris platform |
| `forms` | workspace_id, name, description, status (`draft`, `pilot`, `active`, `archived`), current_version_id, created_by_user_id | Struktur data; `current_version_id` = versi terbit yang dipakai percakapan baru |
| `form_versions` | workspace_id, form_id, version, definition JSONB, published_at, published_by_user_id | `published_at` kosong = draf (paling banyak satu per form, bisa diubah); tidak pernah diubah setelah dipublikasikan |
| `form_assignments` | form_version_id, extension_worker_id | Pilot = sebagian penyuluh |
| `conversations` | workspace_id, extension_worker_id, form_version_id, channel_id, step, draft_answers JSONB, status, failed_attempts, last_inbound_at, taken_over_by, taken_over_at, next_reminder_at | `last_inbound_at` untuk jendela 24 jam WA |
| `messages` | conversation_id, direction (`in`, `out`), body, media_key, external_id, channel_sent_at, processed_at, delivery_status | `UNIQUE (channel_id, external_id)` |
| `reports` | workspace_id, code, form_version_id, extension_worker_id, conversation_id, answers JSONB, latitude, longitude, accuracy_m, region_id, commodity_id, condition, area_ha, plot_key, complete, needs_review, received_at | Kolom filter disalin dari `answers` dan diindeks |
| `report_exports` | workspace_id, requested_by, params JSONB, status, object_key, row_count, error, created_at, finished_at, expires_at | Ekspor dashboard; lihat [dashboard.md](../06-domain-guides/dashboard.md#model-data-tambahan) |
| `report_photos` | report_id, object_key, size_bytes, blur_score, ai_note | |
| `report_follow_ups` | report_id, assignee_member_id, priority, status, note | |
| `activity_events` | workspace_id, occurred_at, extension_worker_id, channel, type, details JSONB, status | Log Aktivitas Agent |
| `member_invites` | workspace_id, email (huruf kecil), role, token_hash, invited_by_user_id, sent_at, expires_at, accepted_at, revoked_at | Undangan anggota (B-055). Unik (workspace_id, email) selama terbuka (`accepted_at` dan `revoked_at` kosong) |
| `audit_logs` | workspace_id (null untuk aksi platform, mis. artikel), actor_user_id, action, target, metadata JSONB | Ekspor, ubah peran, publikasi, takeover, hapus |
| `leads` | name, email, organization, message, source | Dari form landing page dan "Hubungi kami" Enterprise |
| `plans`, `subscriptions`, `payments`, `usage_counters` | lihat [billing-and-plans.md](../06-domain-guides/billing-and-plans.md#model-data) | Paket, langganan, kuota |
| `auth_tokens` | user_id, purpose (`verify_email`, `reset_password`), token_hash, expires_at, used_at | Token sekali pakai; hanya hash yang disimpan ([auth.md](../06-domain-guides/auth.md#tabel)) |
| `articles`, `article_categories`, `article_media`, `article_revisions` | lihat [articles.md](../06-domain-guides/articles.md#model-data) | Blog; data platform, **tanpa `workspace_id`** |
| `users.platform_role` | `content_author`, `content_editor`, atau null | Peran konten Fluctuz, diberikan lewat CLI |

## Detail penting

**Kode laporan.** `code` dibuat dari sequence Postgres per tahun-bulan (`LP-2411-0248`) dengan `UNIQUE (workspace_id, code)`. Jangan memakai "nomor terbesar + 1" karena dua laporan bersamaan bisa mendapat kode sama.

**Takeover.** Ambil alih memakai satu query bersyarat:

```sql
UPDATE conversations SET taken_over_by = :member_id, taken_over_at = now()
WHERE id = :id AND taken_over_by IS NULL;
```

0 baris berubah → kembalikan 409.

**Lokasi.** `latitude`/`longitude` `double precision` + indeks pada `region_id`. Agregasi peta = `GROUP BY region_id`. `region_id` diisi dari titik GPS lewat `reference_data.service.locate` (PostGIS, titik-dalam-poligon kecamatan; titik ≤ 2 km di luar batas, mis. di pantai, masuk ke kecamatan terdekat).

**`form_versions.definition`** divalidasi oleh model Pydantic `FormDefinition` (`app/modules/forms/schemas.py`) sebelum disimpan. Aturan lengkap, tipe isian, dan kode galat: [forms.md](../06-domain-guides/forms.md).

```json
{
  "fields": [
    { "key": "farmer_name", "type": "short_text", "label": "Nama petani", "question": "Siapa nama petaninya?", "required": true },
    { "key": "land_area", "type": "number", "label": "Luas lahan", "question": "Berapa luas lahan?", "unit": "ha", "min": 0, "max": 500, "review_above": 50, "role": "area" },
    { "key": "condition", "type": "single_choice", "label": "Kondisi tanaman", "question": "Bagaimana kondisi tanamannya?", "role": "condition",
      "options": [{"value": "healthy", "label": "Sehat"}, {"value": "attention", "label": "Perlu perhatian"}, {"value": "infected", "label": "Terserang"}] },
    { "key": "photos", "type": "photo", "label": "Foto lahan", "question": "Boleh kirim 1 sampai 3 foto?", "min": 1, "max": 3 },
    { "key": "location", "type": "location", "label": "Lokasi lahan", "question": "Di mana lahannya?", "max_accuracy_m": 50 }
  ],
  "rules": [
    { "if": { "field": "condition", "equals": "infected" }, "then": { "require": "photos" } }
  ]
}
```

`key` dan nilai pilihan dalam Bahasa Inggris (stabil untuk data dan analitik); `question` dan `label` dalam Bahasa Indonesia (dilihat penyuluh).

**Retensi.** Job cron menghapus `messages` dan media melewati masa retensi. `reports.answers` tetap disimpan, sehingga detail laporan lama tetap utuh; bagian "Percakapan asli" di UI menampilkan "dihapus sesuai kebijakan retensi".
