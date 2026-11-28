## Deploy otomatis server development

- Workflow `deploy-development`: setelah `ci` lulus di push ke `development`, image `ghcr.io/indrarasyid07/fredd-api` (tag `development` dan SHA) dibangun lalu di-deploy lewat `deploy.sh api` (pull, migrasi, restart api/worker/scheduler).
- `deployment.md`: env var baru ditambahkan ke `.env.example` dan `/opt/fluctuz/.env` server sebelum merge.
