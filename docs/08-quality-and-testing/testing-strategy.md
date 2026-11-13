# Testing Strategy

## Tooling

- `ruff` untuk lint dan format.
- `pyright` untuk pemeriksaan tipe (satu pemeriksa saja).
- `pytest` + `pytest-asyncio` + `httpx.AsyncClient` untuk tes API.
- Database tes: PostgreSQL sungguhan di Docker (bukan SQLite), dibersihkan per tes dengan transaksi yang di-rollback.

## Yang wajib dites

Urut dari risiko tertinggi:

1. **Parser jawaban.** Tes tabel input → hasil: `"1,5"`, `"1.5"`, `"satu setengah"`, `"2 ha"`, `"banyak"` (gagal), `"15"` vs `"1,5"`; `"pari"` → `padi`; tanggal relatif.
2. **Alur percakapan penuh** dengan adapter kanal palsu: mulai → jawab semua → ringkasan → kirim → laporan tersimpan; gagal 3 kali → `needs_help`; sinyal hilang → draf → pengingat → lanjutkan.
3. **Urutan pesan:** dua pesan masuk berdekatan diproses sesuai `channel_sent_at`.
4. **Takeover:** dua admin bersamaan → satu 200, satu 409; Fredd tidak membalas selama takeover.
5. **Jendela 24 jam WhatsApp:** di luar jendela adapter memakai template.
6. **Webhook:** tanda tangan salah ditolak; payload yang sama dua kali hanya menghasilkan satu pesan.
7. **Otorisasi:** setiap endpoint menolak peran yang tidak cukup dan data workspace lain.
8. **Aturan struktur:** JIKA/MAKA dan `review_above`.

## CI

Setiap push: `ruff check`, `ruff format --check`, `pyright`, `pytest`. Ekspor `openapi.json` dan bandingkan dengan yang di-commit agar frontend tahu ada perubahan kontrak.
