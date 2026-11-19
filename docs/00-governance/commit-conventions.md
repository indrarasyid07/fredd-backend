# Commit Conventions

Berlaku untuk repo `backend`, `frontend`, dan `infra`. Daftar scope tiap repo ada di bagian [Scope](#scope); frontend dan infra punya file pendek yang menautkan ke dokumen ini.

Formatnya mengikuti [Conventional Commits 1.0](https://www.conventionalcommits.org/en/v1.0.0/), dengan aturan tambahan di bawah.

## Format

```
<type>(<scope>): <subject>

<body>

<footer>
```

- Baris pertama (header) wajib. Body dan footer opsional, dipisah dari header dan satu sama lain dengan **satu baris kosong**.
- Seluruh pesan dalam **Bahasa Inggris**, sama dengan kode. Istilah domain memakai padanan Inggris dari [glosarium](../06-domain-guides/glossary.md) (`extension worker`, bukan `penyuluh`). Teks UI berbahasa Indonesia boleh dikutip apa adanya bila memang itu yang berubah, mis. ``fix(auth): show "Email belum terdaftar" on unknown email``.

## Type

| Type | Dipakai untuk | Contoh |
|---|---|---|
| `feat` | Kemampuan baru yang terasa oleh pengguna atau pemanggil API | `feat(auth): add email login, logout and session check` |
| `fix` | Perbaikan bug | `fix(auth): return the same error for unknown email and wrong password` |
| `docs` | Hanya dokumentasi (`docs/`, README, komentar dok) | `docs: define response envelope and error catalog` |
| `refactor` | Ubah struktur kode tanpa mengubah perilaku | `refactor(auth): move session cookie helpers to api/cookies` |
| `perf` | Peningkatan kinerja tanpa mengubah perilaku | `perf(reports): add index on reports(form_id, submitted_at)` |
| `test` | Hanya menambah atau memperbaiki tes | `test(auth): cover rate limit per IP` |
| `build` | Dependensi, Dockerfile, sistem build, image | `build: add Dockerfile for the API image` |
| `ci` | Pipeline CI | `ci: run pyright and pytest on merge requests` |
| `chore` | Pemeliharaan lain yang tidak masuk type di atas (gitignore, konfigurasi editor, setup awal) | `chore: initial project setup` |
| `style` | Format saja (spasi, urutan import) tanpa perubahan logika | `style: apply ruff format` |
| `revert` | Membatalkan commit sebelumnya | `revert: feat(auth): add email login` |

Bila satu commit cocok dengan dua type, pilih yang paling berdampak bagi pengguna: `feat` > `fix` > `perf` > `refactor` > yang lain. Tes dan dokumen yang menyertai sebuah fitur ikut di commit `feat` itu, bukan dipisah.

## Scope

Scope opsional, huruf kecil, satu kata (`kebab-case` bila perlu), dan menyebut **area yang berubah**, bukan nama file. Kosongkan scope bila perubahan menyentuh banyak area atau seluruh repo (`docs: ...`, `chore: ...`).

| Repo | Scope | Area |
|---|---|---|
| backend | nama modul fitur: `auth`, `forms`, `reports`, `extension-workers`, `channels`, `billing`, ... | `app/modules/<fitur>` dan endpoint-nya di `app/api/v1/<fitur>` |
| backend | `api` | Lapisan HTTP bersama: respons standar, handler error, middleware, dependensi |
| backend | `core` | Konfigurasi, keamanan, Redis, rate limit |
| backend | `db` | Base model, sesi database, migrasi yang tidak milik satu fitur |
| backend | `system` | Health check dan endpoint sistem |
| backend | `scripts`, `deps` | Skrip CLI; pembaruan dependensi |
| frontend | `auth`, `dashboard`, `forms`, `reports`, ... | Fitur di `src/features/<fitur>` dan route-nya |
| frontend | `marketing` | Halaman publik (landing dan halaman SEO lain) |
| frontend | `api` | Klien API dan tipe hasil generate |
| frontend | `ui`, `config`, `deps` | Komponen bersama dan token desain; konfigurasi Next.js; dependensi |
| infra | `compose`, `caddy`, `postgres`, `redis`, `env` | Layanan atau file konfigurasi yang berubah |

Nama fitur baru mengikuti nama folder modulnya, sehingga scope di ketiga repo sama untuk fitur yang sama (`auth` di backend dan frontend).

## Subject

- Kalimat perintah (imperative): `add`, `fix`, `remove`, `rename`, bukan `added` / `adds` / `adding`. Uji: "If applied, this commit will _<subject>_".
- Huruf kecil di awal, tanpa titik di akhir.
- Maksimal **72 karakter** untuk seluruh header; usahakan sekitar 50.
- Sebut **apa yang berubah bagi pengguna atau sistem**, bukan proses kerjanya. `add login page and session check`, bukan `work on login` atau `update files`.
- Hindari kata kosong: `update`, `changes`, `misc`, `wip`, `fix stuff`, `final`.

## Body

- Wajib bila perubahan tidak jelas dari header saja: lebih dari satu hal berubah, ada alasan yang tidak terlihat dari kode, atau ada efek samping.
- Baris dibungkus di **72 karakter**.
- Jelaskan **apa dan kenapa**, bukan langkah demi langkah bagaimana (itu ada di diff).
- Boleh paragraf atau daftar berpoin `- `. Daftar dipakai bila commit berisi beberapa perubahan setara.
- Sebut nomor keputusan bila commit menerapkan keputusan di decision log (`B-012`, `F-015`, `I-010`).

## Footer

| Footer | Kapan |
|---|---|
| `BREAKING CHANGE: <penjelasan>` | Kontrak API, skema, variabel env, atau perilaku yang dipakai repo lain berubah tidak kompatibel. Header juga diberi `!`: `feat(api)!: ...` |
| `Refs: #<nomor>` | Terkait issue GitHub tanpa menutupnya |
| `Closes: #<nomor>` | Menutup issue GitHub saat di-merge |

Perubahan yang memutus kontrak antar-repo (mis. endpoint backend yang dipakai frontend) juga dicatat di changelog repo yang terdampak.

## Yang tidak boleh ada di pesan commit

| Larangan | Alasan |
|---|---|
| Baris atribusi AI atau alat: `Co-Authored-By: Claude ...`, `Generated with ...`, dan sejenisnya | Penulis commit adalah orang yang meng-commit; riwayat repo bukan tempat iklan alat |
| Referensi ke alat atau file desain: nama artifact, canvas, halaman atau artboard desain, label versi desain (mis. "V.1"), nama layar di file desain | Pesan commit menjelaskan perubahan produk dan harus tetap bermakna walau alat desain berganti. Tulis fiturnya: `build landing page`, bukan `build landing page from <nama halaman desain>` |
| Rahasia: password, token, API key, isi `.env`, URL dengan kredensial | Riwayat git permanen dan ikut tersalin ke setiap clone |
| Data pribadi: nama, nomor telepon, atau email pengguna atau penyuluh | Privasi; riwayat git tidak bisa dihapus selektif dengan mudah |
| Nama klien atau mitra yang belum diumumkan | Kerahasiaan bisnis |
| Emoji dan gitmoji | Menyulitkan pencarian dan pembuatan changelog |

Aturan rahasia dan data pribadi juga berlaku untuk **isi** commit: file `.env`, dump database, dan ekspor data lapangan tidak pernah di-commit (lihat `.gitignore` tiap repo).

## Ukuran dan isi commit

- **Satu perubahan logis per commit.** Fitur beserta tes dan dokumennya boleh satu commit; perbaikan bug yang tidak berhubungan dibuat commit terpisah.
- Setiap commit di `development` harus lolos lint, typecheck, dan tes. Jangan commit kode yang setengah jadi.
- File hasil generate ikut di commit yang membuatnya berubah: `openapi.json` (backend) bersama perubahan endpoint, `src/lib/api/schema.d.ts` (frontend) bersama pemakaian tipe barunya, migrasi Alembic bersama perubahan model.
- Perubahan format massal (`ruff format`, Prettier) dibuat commit `style` tersendiri agar diff fitur tetap terbaca.

## Cabang

| Cabang | Fungsi |
|---|---|
| `development` | Cabang utama (default di GitHub). Semua pekerjaan dan commit harian masuk ke sini. |
| `main` | Cabang rilis. Berisi commit awal; diperbarui hanya dengan merge dari `development` bila ada rilis atau pembaruan yang disengaja. |

- Commit awal (`chore: initial project setup`) ada di kedua cabang. Selebihnya hanya di `development`.
- Jangan commit langsung ke `main`. Perbarui dengan merge dari `development` (`git switch main && git merge --no-ff development`), lalu push.
- Aturan ini sama di ketiga repo (backend, frontend, infra).
- Cabang fitur, bila dipakai, dicabangkan dari `development` dan digabung kembali ke `development`.

## Menulis ulang riwayat

- Sebelum di-push, commit boleh dirapikan: `git commit --amend`, rebase untuk menggabung atau mengganti pesan.
- Setelah di-push ke `development` atau `main`, riwayat **tidak** ditulis ulang dan tidak di-force push. Kesalahan diperbaiki dengan commit baru atau `git revert`.
- Branch fitur yang sudah di-push hanya boleh di-force push (`--force-with-lease`) bila belum ada orang lain yang bekerja di atasnya.

## Cek sebelum commit

1. `git status` dan `git diff --staged`: hanya file yang dimaksud; tidak ada `.env`, build, atau file pribadi.
2. Lint, typecheck, dan tes repo itu lolos (perintahnya di README repo).
3. Header sesuai format, ≤ 72 karakter, kalimat perintah.
4. Tidak ada baris atribusi, referensi file desain, rahasia, atau data pribadi di pesan.

Untuk mengecek pesan commit yang sudah ada sebelum push:

```bash
git log origin/development..HEAD --format='%h %s%n%b' | grep -n -i -E 'co-authored|generated with|artifact|canvas|artboard|v\.1'
```

Perintah di atas tidak boleh menghasilkan apa pun.

## Contoh

Baik:

```
feat(auth): add email login, logout and session check

Sessions are opaque tokens in an HttpOnly cookie; only the SHA-256
hash is stored. Login is rate limited per IP and per IP+email, and
unknown emails go through a dummy hash so timing does not reveal
which accounts exist.
```

```
fix(config): scope the Tailwind Turbopack rule to globals.css

A "*.css" rule renamed every *.module.css to plain CSS, so CSS
Module class names came back undefined.
```

```
feat(api)!: wrap all responses in the standard envelope

BREAKING CHANGE: every endpoint now returns {success, message, data,
errors, meta}. Clients must read the payload from `data`.
```

Buruk, dan perbaikannya:

| Buruk | Masalah | Lebih baik |
|---|---|---|
| `update` | Tidak menjelaskan apa pun | `fix(auth): clear the session cookie on logout` |
| `Added login page.` | Bentuk lampau, huruf besar, titik | `feat(auth): add login page` |
| `feat: build landing from Landing V.1 design` | Menyebut halaman desain | `feat(marketing): build landing page` |
| `fix(auth): fix bug` | Tidak menyebut bug-nya | `fix(auth): accept emails with uppercase letters` |
| `feat: login, docker, docs, fix typo` | Beberapa perubahan tak berhubungan | Pecah menjadi beberapa commit |
| `wip` | Commit setengah jadi di `development` | Selesaikan dulu, atau rapikan sebelum push |
