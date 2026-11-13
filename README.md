# Fredd API

FastAPI backend. Technical docs: [docs/README.md](docs/README.md).

## Run locally

Two options: natively with hot reload (below), or the whole stack in Docker.

### Native

Requirements: [uv](https://docs.astral.sh/uv/), Docker (for Postgres and Redis).

```bash
docker compose -f ../infra/docker-compose.yml up -d --wait
cp .env.example .env
uv sync
uv run alembic upgrade head
uv run uvicorn fredd.main:app --reload
```

- Health: http://127.0.0.1:8000/api/v1/health
- OpenAPI (development only): http://127.0.0.1:8000/api/docs

Dev Postgres and Redis come from [infra/](https://gitlab.com/databiota-fredd/infra/-/blob/main/README.md) and listen on host ports 5433 and 6380 so they don't clash with a native install. Use `127.0.0.1`, not `localhost`: Windows resolves `localhost` to IPv6 first and the containers only bind IPv4.

### Docker

From the parent folder (requires only Docker):

```bash
docker compose -f infra/docker-compose.yml --profile app up -d --build --wait
```

The API is served behind Caddy at http://localhost:8080/api/v1/health. Migrations run automatically. The image is a production build ([Dockerfile](Dockerfile)); rebuild with `--build` after code changes. Details: [infra README](https://gitlab.com/databiota-fredd/infra/-/blob/main/README.md).

## Checks

```bash
uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest
```

Tests need the Docker services running.

## New migration

```bash
uv run alembic revision --autogenerate -m "add users table"
```

## Repositories

Fredd is split into three GitLab repos. Clone them side by side in one folder; commands in the docs assume this layout.

```bash
mkdir fredd && cd fredd
git clone https://gitlab.com/databiota-fredd/backend.git
git clone https://gitlab.com/databiota-fredd/frontend.git
git clone https://gitlab.com/databiota-fredd/infra.git
```
