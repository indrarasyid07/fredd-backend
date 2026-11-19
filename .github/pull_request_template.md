## Apa yang berubah
<!-- 1–3 kalimat, Bahasa Indonesia -->

Roadmap: `Langkah x.y` · Issue: # · Domain: D? · PR pasangan: <!-- fredd-backend#.. / fredd-frontend#.. atau "tidak ada" -->

## Kontrak & data
- [ ] Endpoint/schema berubah → `openapi.json` diekspor ulang di PR ini
- [ ] PR frontend pasangan: `schema.d.ts` dibuat ulang dari `openapi.json` di `development` setelah PR backend di-merge
- [ ] Endpoint dipakai domain lain / perubahan merusak? Bila ya: pemilik domain itu ditandai, `!` di judul bila merusak
- [ ] Migrasi baru → `alembic heads` = 1, `down_revision` menunjuk head terbaru `development`
- [ ] Env var baru → `.env.example` + `07-operations/deployment.md`

## Pemeriksaan
- [ ] Lint, typecheck, tes lolos lokal
- [ ] Tes isolasi tenant / peran untuk endpoint baru
- [ ] Docs diperbarui sesuai matriks di skill `fluctuz-quality-gate`
- [ ] Keputusan baru ditulis sebagai `B-XXX`/`F-XXX` (nomor diisi saat merge)

## Cara menguji
<!-- langkah singkat -->
