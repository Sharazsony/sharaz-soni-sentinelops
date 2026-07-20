# SentinelOps

SentinelOps — a FastAPI service for tracking incidents against registered services, with filtering/pagination, an enforced status state machine, and a per-service MTTR stats endpoint.

> **CI/CD is not built yet.** This README covers the backend, database, and local Docker runtime only. There is no `.github/workflows/ci.yml`, no Docker Hub push, and no repo secrets configured — that's the next phase, not this one.

## Prerequisites

Tested with:
- Docker 24+
- Docker Compose v2 (the `docker compose` subcommand, not the standalone `docker-compose` binary)
- Git (any recent version)

Python is not required on your host — the API and the test suite both run inside the `api` container.

## GitHub Actions secrets

The CI pipeline expects 5 repository secrets in GitHub. Add them at GitHub → Settings → Secrets and variables → Actions → New repository secret:

- `DOCKERHUB_USERNAME`: Your Docker Hub username for the image-publish job
- `DOCKERHUB_TOKEN`: A Docker Hub access token (recommended) or password

## Quickstart

```bash
https://github.com/Sharazsony/sharaz-soni-sentinelops.git
cd sharaz-soni-sentinelops

cp .env.example .env          # works as-is, no edits needed
docker compose up --build -d
curl http://localhost:8000/health
# -> {"status": "ok", "database": "ok"}
# Interactive docs: http://localhost:8000/docs
```

No manual table creation, no `docker exec`, no editing files required — tables (and the two native Postgres enum types) are created automatically on startup via `Base.metadata.create_all()`.

## Configuration (`.env`)

Your `pydantic-settings` `Settings` class reads only `DATABASE_URL`, `APP_ENV`, and `LOG_LEVEL` — the split Postgres variables below exist for the `db` container's own initialization and are never read by the app directly:

| Variable | Consumed by | Purpose | Example |
|---|---|---|---|
| `DATABASE_URL` | app (`Settings`) | Full SQLAlchemy connection string. Host is `db` (the compose service name), not `localhost`, when running under Compose. | `postgresql+psycopg://appuser:localdevpassword@db:5432/sentinelops` |
| `APP_ENV` | app (`Settings`) | Logged on startup; informational | `local` |
| `LOG_LEVEL` | app (`Settings`) | stdlib logging level | `INFO` |
| `POSTGRES_USER` | `db` container only | Role the `postgres:16` image creates on first boot | `appuser` |
| `POSTGRES_PASSWORD` | `db` container only | Password for that role | `localdevpassword` |
| `POSTGRES_HOST` | used to build `DATABASE_URL` | Hostname the app connects to (the compose service name) | `db` |
| `POSTGRES_PORT` | used to build `DATABASE_URL` | Postgres port | `5432` |
| `POSTGRES_DB` | `db` container only | Database created on first boot | `sentinelops` |

The `POSTGRES_*` values must stay consistent with the credentials embedded in `DATABASE_URL`, or the `api` container will boot and then fail to authenticate against `db`. There is no `API_KEY` or auth of any kind in this service — every endpoint is public.

## API Endpoints

Base URL: `http://localhost:8000`. No authentication on any endpoint.

| Method | Path | Purpose | Success |
|---|---|---|---|
| GET | `/health` | Liveness + real DB check (not part of the 6-endpoint budget) | 200 / 503 |
| POST | `/services` | Register a service | 201 |
| GET | `/services` | List all services | 200 |
| POST | `/incidents` | Create an incident (always starts `open`) | 201 |
| GET | `/incidents` | Filtered + paginated list (`{total, limit, offset, items}`) | 200 |
| PATCH | `/incidents/{id}/status` | Advance status one legal step | 200 |
| GET | `/stats/services` | Per-service open count + MTTR | 200 |

Example calls:

```bash
# register a service
curl -i -X POST http://localhost:8000/services \
  -H "Content-Type: application/json" \
  -d '{"name": "checkout-api", "owner_team": "platform"}'

# list services
curl http://localhost:8000/services

# create an incident
curl -i -X POST http://localhost:8000/incidents \
  -H "Content-Type: application/json" \
  -d '{"service_id": 1, "severity": "sev2", "summary": "elevated 500s on checkout"}'

# advance its status
curl -i -X PATCH http://localhost:8000/incidents/1/status \
  -H "Content-Type: application/json" \
  -d '{"status": "acknowledged"}'

# per-service stats
curl http://localhost:8000/stats/services
```

The status state machine only allows `open → acknowledged → resolved`; every other transition (including no-ops like `open → open`) returns `409`.

## Running Tests

Tests run inside the `api` container against the `db` service — there is no SQLite path, because `severity` and `status` are native PostgreSQL enum types.

```bash
docker compose exec -T api pytest -q
docker compose exec -T api pytest --cov=app --cov-report=term-missing --cov-fail-under=60
docker compose exec -T api ruff check .
```

Last verified run: **13 passed**, **93.41% coverage** (gate is 60%), `ruff check .` clean.

## Bash Scripts

| Script | What it does | How to run it |
|---|---|---|
| `scripts/seed_data.sh` | Polls `/health` until ready, then creates 3 services and 6 incidents (one driven through the full status lifecycle) via the live API | `./scripts/seed_data.sh` |
| `scripts/healthcheck.sh` | Polls `GET /health`, exits non-zero if the API never comes up — usable from CI or a host script | `./scripts/healthcheck.sh` |

## Troubleshooting

**1. `api` container crash-loops with `connection refused` on startup.**
Happens if `api` tries to connect before Postgres is ready. Fix: `docker-compose.yml` uses `depends_on: db: condition: service_healthy`, gated on a `pg_isready` healthcheck — plain `depends_on: [db]` only waits for the container to *start*, not for Postgres to actually accept connections.

**2. `psycopg.OperationalError: password authentication failed for user "appuser"`.**
`.env`'s `DATABASE_URL` credentials don't match `POSTGRES_USER` / `POSTGRES_PASSWORD` — often because one was edited and not the other, or because a stale Postgres volume from an earlier password still exists (Postgres only applies `POSTGRES_*` on the *first* boot of an empty volume). Fix: either revert `.env` to match, or wipe the volume: `docker compose down -v && docker compose up --build -d`.

**3. Tests fail with enum-related SQLAlchemy errors when run outside Docker.**
`severity` and `status` are native PostgreSQL enum types — SQLite can't create this schema at all. Always run tests against a real PostgreSQL 16, either inside the `api` container against the compose `db` service, or against a local Postgres instance with `DATABASE_URL` pointed at it.

## Architecture / Request Flow

A request hits FastAPI's router layer first; Pydantic validates the body/query params against `app/schemas.py` before the handler runs — bad shapes short-circuit as `422` automatically. Routers stay thin: they call into `app/crud.py`, which owns every SQLAlchemy query, using a `Session` from the `get_db()` dependency (opened per-request, closed in a `finally` block). No router builds a query or raw SQL directly.

Status transitions go through `app/state_machine.py` first — its `ALLOWED_TRANSITIONS` map only permits `open → acknowledged` and `acknowledged → resolved`; anything else raises `409` before `crud.py` is ever called. `resolved_at` is stamped server-side, timezone-aware, only on the `acknowledged → resolved` move, and is never accepted from the client.

`GET /stats/services` runs a single `LEFT OUTER JOIN` from `services` to `incidents` with `CASE`-based `SUM()`/`AVG()` — not a per-service query loop — so every service appears even with zero incidents, and `acknowledged` incidents count toward neither `open_count` nor MTTR.

Every error response — `400`/`404`/`409`/`422` — returns the same envelope: `{"detail": "<message>"}`. FastAPI's default validation-error shape (a list of objects) is flattened to a single string by a custom exception handler in `app/main.py`. `GET /health` is the one exception, returning `{"status": "ok"|"degraded", "database": "ok"|"unavailable"}` verbatim.

## Notes on this build

This repo currently covers the backend, database, and local Docker runtime end-to-end — schema, all six endpoints, the three graded twists (filtering/pagination, the status state machine, MTTR aggregation), the error envelope, logging, tests, and `docker-compose.yml` — all run and verified against a real PostgreSQL 16 instance.

**Intentionally not built yet:**
- `.github/workflows/ci.yml` — no lint-and-test job, no Postgres CI service, no `docker` job
- No Docker Hub push, no image tagging
- No `DOCKERHUB_USERNAME` / `DOCKERHUB_TOKEN` repo secrets — nothing to configure them for yet
- No CI badge at the top of this README — reserved for once the workflow exists
- Git workflow hygiene (feature branches, incremental commits, a merged PR) has not been applied to this working directory yet — do that before pushing

Recommended first steps on your machine:
```bash
cp .env.example .env
docker compose up --build -d
docker compose exec -T api pytest --cov=app --cov-fail-under=60
./scripts/seed_data.sh
```
