# Testing Strategy

## Tooling

- `ruff` untuk lint dan format.
- `pyright` untuk pemeriksaan tipe (satu pemeriksa saja).
- `pytest` + `pytest-asyncio` + `httpx.AsyncClient` untuk tes API.
- Database tes: PostgreSQL sungguhan di Docker (bukan SQLite), dibersihkan per tes dengan transaksi yang di-rollback.

Letak tes mengikuti [struktur kode](../02-architecture/system-architecture.md#tes): `tests/unit/`, `tests/api/`, `tests/integration/`.

## Yang wajib dites

### Fondasi (dibuat bersama endpoint pertama)

- **Format respons** (`tests/api/test_responses.py`): setiap jenis error (AppError, validasi 422, 404 route, 405, 500 yang dipaksa) menghasilkan bentuk standar dengan `request_id` di body dan header; respons sukses selalu punya `errors: []`.
- **Auth**: daftar tes di [auth.md](../06-domain-guides/auth.md#tes-wajib).

### Domain

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
