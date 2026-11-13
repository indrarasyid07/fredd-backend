# Fredd Backend Docs

Dokumentasi teknis backend Fredd (FastAPI). Isi ditulis dalam Bahasa Indonesia; nama file, kode, endpoint, dan skema database memakai Bahasa Inggris.

| Folder | Isi |
|---|---|
| [00-governance](00-governance/documentation-guidelines.md) | Aturan menulis dan merawat dokumen ini |
| [01-product-and-scope](01-product-and-scope/product-overview.md) | Apa itu Fredd, aktor, alur, ruang lingkup v1 |
| [02-architecture](02-architecture/system-architecture.md) | Komponen sistem, tech stack, alur pesan |
| [03-api](03-api/api-conventions.md) | Konvensi API dan daftar endpoint |
| [04-database](04-database/data-model.md) | Model data dan konvensi skema |
| [05-security-and-access](05-security-and-access/security-model.md) | Auth, peran, webhook, enkripsi, retensi |
| [06-domain-guides](06-domain-guides/glossary.md) | Glosarium, auth, mesin percakapan, kanal WhatsApp/Telegram, paket & tagihan |
| [07-operations](07-operations/deployment.md) | Proses, env, zona waktu, migrasi (layanan dan backup di infra) |
| [08-quality-and-testing](08-quality-and-testing/testing-strategy.md) | Strategi tes dan tooling kualitas |
| [09-seeding](09-seeding/seed-data.md) | Data awal dan data demo |
| [10-roadmap](10-roadmap/roadmap.md) | Urutan pengerjaan |
| [11-decisions](11-decisions/decision-log.md) | Catatan keputusan teknis |
| [12-phase-history](12-phase-history/changelog.md) | Riwayat fase pengerjaan |
| [13-diagrams](13-diagrams/system-diagrams.md) | Diagram sistem (Mermaid) |
| [14-agent-guides](14-agent-guides/agent-guidelines.md) | Panduan untuk AI coding agent |
| [99-archive](99-archive/README.md) | Dokumen lama yang tidak berlaku |

Dokumentasi frontend ada di [`../../frontend/docs`](https://gitlab.com/databiota-fredd/frontend/-/blob/main/docs/README.md), infrastruktur (database, Redis, deploy) di [`../../infra/docs`](https://gitlab.com/databiota-fredd/infra/-/blob/main/docs/README.md).
