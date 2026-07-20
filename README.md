# SentinelOps

SentinelOps is a FastAPI service for registering services, logging incidents, enforcing the incident lifecycle, and exposing per-service statistics including MTTR.

![CI](https://github.com/Sharazsony/sharaz-soni-sentinelops/actions/workflows/ci.yml/badge.svg)

## Prerequisites

- Docker 24+
- Docker Compose v2 (`docker compose`)
- Git

Python is not required on the host because the API and tests run inside the `api` container.

## Quickstart

```bash
git clone https://github.com/Sharazsony/sharaz-soni-sentinelops.git
cd sharaz-soni-sentinelops
cp .env.example .env
docker compose up --build -d
```

Once the containers are up, open:

- API health check: http://localhost:8000/health
- Interactive docs: http://localhost:8000/docs

To stop everything:

```bash
docker compose down -v
```

## Environment variables

Create `.env` from `.env.example` and keep the values consistent between the app and the Postgres container.

| Variable | Used by | Purpose | Example |
|---|---|---|---|
| `POSTGRES_USER` | `db` container | Postgres role created on first boot | `appuser` |
| `POSTGRES_PASSWORD` | `db` container | Password for that role | `localdevpassword` |
| `POSTGRES_HOST` | app | Hostname used to build the connection string | `db` |
| `POSTGRES_PORT` | app | Postgres port | `5432` |
| `POSTGRES_DB` | `db` container | Database created on first boot | `sentinelops` |
| `APP_ENV` | app | Runtime environment label | `local` |
| `LOG_LEVEL` | app | Logging verbosity | `INFO` |

## API endpoints

Base URL: http://localhost:8000

| Method | Path | Purpose | Success code |
|---|---|---|---|
| GET | `/health` | Liveness check that runs a real `SELECT 1` against Postgres | 200 / 503 |
| POST | `/services` | Create a service | 201 |
| GET | `/services` | List all services | 200 |
| POST | `/incidents` | Create an incident (it always starts as `open`) | 201 |
| GET | `/incidents` | List incidents with filtering, pagination, and a `{total, limit, offset, items}` envelope | 200 |
| PATCH | `/incidents/{incident_id}/status` | Advance an incident through `open -> acknowledged -> resolved` | 200 |
| GET | `/stats/services` | Per-service open counts and MTTR in minutes | 200 |

Example requests:

```bash
curl -X POST http://localhost:8000/services \
  -H 'Content-Type: application/json' \
  -d '{"name":"checkout-api","owner_team":"payments"}'

curl http://localhost:8000/services

curl -X POST http://localhost:8000/incidents \
  -H 'Content-Type: application/json' \
  -d '{"service_id":1,"title":"Checkout 500s","severity":"sev1"}'

curl -X PATCH http://localhost:8000/incidents/1/status \
  -H 'Content-Type: application/json' \
  -d '{"status":"acknowledged"}'
```

## Running tests

Tests run inside the `api` container against the live `db` service.

```bash
docker compose exec -T api pytest -q
docker compose exec -T api pytest --cov=app --cov-report=term-missing --cov-fail-under=60
docker compose exec -T api ruff check .
```

## Bash scripts

- `./scripts/healthcheck.sh` polls `GET /health` until the API is ready.
- `./scripts/seed_data.sh` seeds sample services and incidents through the live API.

## Troubleshooting

- If the API fails to start on first boot, Postgres is probably still initializing. Wait a few seconds and run `docker compose up -d` again.
- If the app cannot connect to the database, the values in `.env` for the Postgres credentials no longer match the app connection settings. Reconcile them and restart the stack.
- If `http://localhost:8000/docs` does not load, confirm that the `api` container is healthy and that the stack is running with `docker compose ps`.

## Architecture and request flow

A request reaches the FastAPI router, then passes through Pydantic validation before the handler calls into `app/crud.py`. All SQLAlchemy queries, filtering, pagination, state-machine checks, and stats aggregation live in `app/crud.py`, while the router layer stays thin. The status transition logic is implemented in `app/state_machine.py`, and the MTTR aggregation for `GET /stats/services` is computed from incident durations stored in Postgres. The health endpoint runs a real `SELECT 1` and returns either a healthy or degraded payload depending on database connectivity.
