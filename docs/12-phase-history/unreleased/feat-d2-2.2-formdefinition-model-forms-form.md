## Struktur data: `FormDefinition` dan tabel forms

- Tabel `forms` dan `form_versions` (draf = versi tanpa `published_at`, satu per form).
- Model `FormDefinition`: 12 tipe isian, peran `condition`/`area`, cara menjawab, aturan JIKA/MAKA; semua masalah dilaporkan sekaligus dengan path bertitik dan kode sendiri.
- `forms.service` untuk domain lain: `get_version_definition`, `get_form`, `create_form`.
- `FormDefinition` ada di `openapi.json` walau endpoint `/forms` belum ada (Langkah 2.3).
- Kontrak lengkap: `docs/06-domain-guides/forms.md`.
