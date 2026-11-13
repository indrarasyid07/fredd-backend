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
| `workspaces` | name, timezone (`Asia/Jakarta`), operating_hours, quiet_hours, retention_conversations_months, retention_photos_months | |
| `users` | email, name, google_sub | |
| `members` | workspace_id, user_id, role (`admin`, `form_editor`, `reviewer`), approved_at | |
| `sessions` | user_id, token_hash, user_agent, ip, city, expires_at, revoked_at | Token mentah hanya di cookie |
| `channels` | workspace_id, type (`whatsapp`, `telegram`), credentials_encrypted, status, display_name, phone_number_id / bot_username | |
| `extension_workers` | workspace_id, name, region_id, phone_e164, telegram_chat_id, verified_at, status | Unik per workspace: phone, telegram_chat_id |
| `extension_worker_invites` | extension_worker_id, token_hash, channel, sent_at, accepted_at | |
| `reference_data` | workspace_id, type (`region`, `commodity`, `farmer_group`, `unit`), value, aliases text[], parent_id | Alias untuk mencocokkan kata lokal |
| `forms` | workspace_id, name, status (`draft`, `pilot`, `active`, `archived`), current_version_id | Struktur data |
| `form_versions` | form_id, version, definition JSONB, published_at | Tidak pernah diubah setelah dipublikasikan |
| `form_assignments` | form_version_id, extension_worker_id | Pilot = sebagian penyuluh |
| `conversations` | workspace_id, extension_worker_id, form_version_id, channel_id, step, draft_answers JSONB, status, failed_attempts, last_inbound_at, taken_over_by, taken_over_at, next_reminder_at | `last_inbound_at` untuk jendela 24 jam WA |
| `messages` | conversation_id, direction (`in`, `out`), body, media_key, external_id, channel_sent_at, processed_at, delivery_status | `UNIQUE (channel_id, external_id)` |
| `reports` | workspace_id, code, form_version_id, extension_worker_id, conversation_id, answers JSONB, latitude, longitude, accuracy_m, region_id, commodity_id, condition, needs_review, received_at | Kolom filter disalin dari `answers` dan diindeks |
| `report_photos` | report_id, object_key, size_bytes, blur_score, ai_note | |
| `report_follow_ups` | report_id, assignee_member_id, priority, status, note | |
| `activity_events` | workspace_id, occurred_at, extension_worker_id, channel, type, details JSONB, status | Log Aktivitas Agent |
| `audit_logs` | workspace_id, actor_user_id, action, target, metadata JSONB | Ekspor, ubah peran, publikasi, takeover, hapus |
| `leads` | name, email, organization, message, source | Dari form landing page |

## Detail penting

**Kode laporan.** `code` dibuat dari sequence Postgres per tahun-bulan (`LP-2411-0248`) dengan `UNIQUE (workspace_id, code)`. Jangan memakai "nomor terbesar + 1" karena dua laporan bersamaan bisa mendapat kode sama.

**Takeover.** Ambil alih memakai satu query bersyarat:

```sql
UPDATE conversations SET taken_over_by = :member_id, taken_over_at = now()
WHERE id = :id AND taken_over_by IS NULL;
```

0 baris berubah → kembalikan 409.

**Lokasi.** `latitude`/`longitude` `double precision` + indeks pada `region_id`. Agregasi peta = `GROUP BY region_id`. PostGIS ditambahkan bila nanti butuh kueri spasial (titik dalam poligon desa, radius).

**`form_versions.definition`** divalidasi oleh model Pydantic sebelum disimpan:

```json
{
  "fields": [
    { "key": "farmer_name", "type": "text", "question": "Siapa nama petaninya?", "required": true },
    { "key": "land_area_ha", "type": "number", "question": "Berapa luas lahan (ha)?", "min": 0, "max": 500, "review_above": 50 },
    { "key": "condition", "type": "choice", "question": "Bagaimana kondisi tanamannya?",
      "options": [{"value": "healthy", "label": "Sehat"}, {"value": "needs_attention", "label": "Perlu perhatian"}, {"value": "infested", "label": "Terserang"}] },
    { "key": "photos", "type": "photo", "min": 1, "max": 3 },
    { "key": "location", "type": "location", "max_accuracy_m": 50 }
  ],
  "rules": [
    { "if": { "field": "condition", "equals": "infested" }, "then": { "require": "photos" } }
  ]
}
```

`key` dan nilai pilihan dalam Bahasa Inggris (stabil untuk data dan analitik); `question` dan `label` dalam Bahasa Indonesia (dilihat penyuluh).

**Retensi.** Job cron menghapus `messages` dan media melewati masa retensi. `reports.answers` tetap disimpan, sehingga detail laporan lama tetap utuh; bagian "Percakapan asli" di UI menampilkan "dihapus sesuai kebijakan retensi".
