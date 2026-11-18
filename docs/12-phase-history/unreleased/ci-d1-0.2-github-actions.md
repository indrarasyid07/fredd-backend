## CI GitHub Actions dan Dependabot

- Workflow `ci` berjalan di setiap PR dan push ke `development`/`main`.
- Pemeriksaan: ruff, pyright, satu head Alembic, pytest + cakupan, `openapi.json` usang, pesan commit.
- Perbaikan baris terlalu panjang di email reset kata sandi; ruff tidak lagi memeriksa `docs/`.
- Dependabot mengusulkan pembaruan dependency tiap Senin, dikelompokkan.
