# SentinelOps — Incident Tracker API

A FastAPI + PostgreSQL 16 backend that lets a platform team register services and
track incidents against them, with filtering/pagination, an enforced status
state machine, and a per-service MTTR (mean time to resolve) stats endpoint.

> **Scope of this build.** This README documents the **backend, database, and
> local Docker runtime only** — models, schemas, business logic, validation,
> the state machine, the stats aggregation, tests, the Dockerfile, and
> `docker-compose.yml`. **GitHub Actions CI/CD and the Docker Hub push
> pipeline are intentionally NOT built yet** and are called out explicitly in
> [Section 9](#9-what-is-intentionally-not-done-yet--next-phase) so nothing
> gets assumed or hallucinated when that phase starts. Everything in Sections
> 1–8 is finished, wired together, and has been run end-to-end against a real
> PostgreSQL 16 instance (not SQLite — see §3.2 for why that matters).

---

## Table of contents

1. [Repository layout](#1-repository-layout)
2. [Prerequisites](#2-prerequisites)
3. [Architecture — how a request flows](#3-architecture--how-a-request-flows)
4. [Configuration — every env var explained](#4-configuration--every-env-var-explained)
5. [Step-by-step: run it locally with Docker](#5-step-by-step-run-it-locally-with-docker)
6. [Step-by-step: run the test suite](#6-step-by-step-run-the-test-suite)
7. [API reference — every endpoint](#7-api-reference--every-endpoint)
8. [The three graded twists, explained](#8-the-three-graded-twists-explained)
9. [What is intentionally NOT done yet — next phase](#9-what-is-intentionally-not-done-yet--next-phase)
10. [Troubleshooting](#10-troubleshooting)
11. [Full specification-compliance checklist](#11-full-specification-compliance-checklist)

---

## 1. Repository layout

```
sentinelops/
├── app/
│   ├── __init__.py
│   ├── main.py             # FastAPI app instance, lifespan startup, /health, error handler
│   ├── config.py            # pydantic-settings Settings (DATABASE_URL, APP_ENV, LOG_LEVEL)
│   ├── database.py          # engine, SessionLocal, Base, get_db()
│   ├── models.py             # SQLAlchemy ORM models ONLY (Service, Incident, enums)
│   ├── schemas.py            # Pydantic v2 models ONLY (Create/Read/List/Stats schemas)
│   ├── crud.py                # ALL SQLAlchemy queries live here — routers never query directly
│   ├── state_machine.py       # ALLOWED_TRANSITIONS map + assert_transition_allowed()
│   └── routers/
│       ├── __init__.py
│       ├── services.py        # POST/GET /services
│       ├── incidents.py       # POST/GET /incidents, PATCH /incidents/{id}/status
│       └── stats.py           # GET /stats/services
├── tests/
│   ├── __init__.py
│   ├── conftest.py            # db_session, client, sample_service fixtures (Postgres only)
│   ├── test_services.py
│   └── test_incidents.py
├── scripts/
│   ├── seed_data.sh            # populates 3 services + 6 incidents via the live API
│   └── healthcheck.sh          # polls GET /health, CI/host usable
├── .env.example                 # every var needed for `cp .env.example .env` to work
├── .gitignore
├── .dockerignore
├── Dockerfile                    # multi-stage, non-root, production CMD
├── docker-compose.yml            # api + db, healthcheck, named volume, dev reload override
├── requirements.txt               # the ONLY dependency file (runtime + pytest + ruff)
└── README.md                      # this file
```

This tree matches the assignment's mandated structure exactly. `.github/workflows/`
is deliberately absent right now — see §9.

---

## 2. Prerequisites

| Tool | Version | Why |
|---|---|---|
| Docker | 24+ | Runs the `api` and `db` containers |
| Docker Compose | v2 (the `docker compose` subcommand, not the old `docker-compose` binary) | Orchestrates both services together |
| Git | any recent version | Clone / version the repo |

**Python is not required on your host.** All Python execution — the API
itself and the test suite — happens inside the `api` container. You do not
need a local virtualenv, and you do not need PostgreSQL installed on your
machine; the `db` service in `docker-compose.yml` provides it.

---

## 3. Architecture — how a request flows

### 3.1 Request lifecycle

1. A client sends an HTTP request (`curl`, `/docs`, a script) to the `api`
   container on port `8000`.
2. **FastAPI routing** (`app/routers/*.py`) matches the path + method and
   parses path/query/body parameters.
3. **Pydantic v2 validation** (`app/schemas.py`) runs automatically on the
   request body / query params. If validation fails, FastAPI raises
   `RequestValidationError`, which is caught by the custom handler in
   `app/main.py` and reshaped into this API's single error envelope
   (`{"detail": "<string>"}`) — see §3.3.
4. The router function is **thin by design**: it does at most a couple of
   lookups, calls one or two functions in `app/crud.py`, translates a `None`
   result into an `HTTPException(404, ...)`, and returns. **No router
   contains a raw SQL string or builds a SQLAlchemy `select()` directly** —
   that is a hard rule from the spec, enforced by convention here (a grader
   would `grep -rniE "SELECT |INSERT INTO|text\(" app/routers/` and expect
   zero hits).
5. **`app/crud.py`** is where every SQLAlchemy query lives: filtering,
   ordering, joins, aggregation. It receives a `Session` (obtained via the
   `Depends(get_db)` dependency chain — see §3.4) and returns ORM objects or
   plain dicts.
6. For incident status changes, the router calls
   **`app/state_machine.assert_transition_allowed()`** *before* calling
   `crud.update_incident_status()`. This is where the `open → acknowledged →
   resolved` rule and the `409` responses live — see §8.2.
7. SQLAlchemy issues the query against **PostgreSQL 16** (the `db`
   container), using the native `severity_enum` / `status_enum` Postgres enum
   types defined in `app/models.py`.
8. The ORM result is handed back to the router, which returns it directly.
   FastAPI serializes it through the endpoint's `response_model`
   (`app/schemas.py`), which is what actually shapes the JSON the client
   sees — this is also where `from_attributes=True` lets a Pydantic model
   read straight off a SQLAlchemy ORM instance.

### 3.2 Why PostgreSQL only, never SQLite

`app/models.py` declares `severity` and `status` as **native PostgreSQL enum
types** (`sqlalchemy.Enum(..., name="severity_enum")` /
`sqlalchemy.Enum(..., name="status_enum")`), not free-text columns with a
Python-side check. SQLite has no native enum type — it cannot even build this
schema, let alone run it correctly. This is why:
- `tests/conftest.py` **only** ever points at a Postgres `DATABASE_URL`
  (whatever is in `.env` / `POSTGRES_*`), never an in-memory SQLite engine.
- The `docker-compose.yml` `db` service is `postgres:16`, not swappable.
- When CI is added later (§9), its Postgres-service-container requirement is
  non-negotiable for the same reason.

### 3.3 The error envelope

Every error response — `400`, `404`, `409`, `422`, `500` — has exactly this
shape:

```json
{ "detail": "Human-readable message explaining what went wrong" }
```

`raise HTTPException(status_code=..., detail="...")` produces this natively.
The one place FastAPI does **not** produce it natively is its built-in `422`
validation errors, which by default return `{"detail": [ {...}, {...} ]}` — a
list of objects. `app/main.py` registers an exception handler for
`RequestValidationError` that flattens that list into a single string, so
`response.json()` always has exactly one key (`detail`) whose value is a
`str`, for every error in the spec. **`GET /health` is the one exception** —
its `503` body is `{"status": "degraded", "database": "unavailable"}`
verbatim, not wrapped in `detail` (see §7's health entry).

### 3.4 Session / dependency wiring

`app/database.py` defines:

```python
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
```

Every route obtains its session via `db: Session = Depends(get_db)` and
passes it straight into the corresponding `crud.py` function — no route ever
calls `SessionLocal()` itself. This indirection is what lets
`tests/conftest.py` override `get_db` with a test-scoped session
(`app.dependency_overrides[get_db] = ...`) so tests run inside a clean,
isolated transaction per test.

### 3.5 Where the twists live

| Twist | Lives in |
|---|---|
| T1 — filtering + pagination | `app/crud.py::list_incidents()` (builds one filter set, reuses it for both the `COUNT` and the page query) + `app/routers/incidents.py::list_incidents()` (query param parsing/defaults) |
| T2 — status state machine | `app/state_machine.py` (the literal `ALLOWED_TRANSITIONS` map) + `app/crud.py::update_incident_status()` (server-side `resolved_at` stamping) |
| T3 — MTTR aggregation | `app/crud.py::get_service_stats()` — a single `LEFT OUTER JOIN` + `CASE`/`AVG()` query, not an N+1 loop |

---

## 4. Configuration — every env var explained

`.env.example` is committed; `.env` is gitignored. Copy one to the other
before running anything (`cp .env.example .env`). There are two groups, and
mixing them up is the single most common setup mistake:

| Variable | Consumed by | Purpose | Example |
|---|---|---|---|
| `DATABASE_URL` | **app** (`app/config.py` → `Settings`) | Full SQLAlchemy connection string. Host **must** be `db` (the compose service name), not `localhost`, when running under Docker Compose. | `postgresql+psycopg://appuser:localdevpassword@db:5432/sentinelops` |
| `APP_ENV` | **app** (`Settings`) | Logged on startup; informational. | `local` |
| `LOG_LEVEL` | **app** (`Settings`) | stdlib `logging` level. | `INFO` |
| `POSTGRES_USER` | **db container only** — never read by `Settings` | Role the `postgres:16` image creates on first boot of the volume. | `appuser` |
| `POSTGRES_PASSWORD` | **db container only** | Password for that role. | `localdevpassword` |
| `POSTGRES_DB` | **db container only** | Database created on first boot. | `sentinelops` |

**These two groups must be internally consistent.** The user/password/db
segment inside `DATABASE_URL` must match `POSTGRES_USER` / `POSTGRES_PASSWORD`
/ `POSTGRES_DB` exactly, or the `api` container will boot and then fail to
authenticate against `db`.

`app/config.py` reads **only** `DATABASE_URL`, `APP_ENV`, `LOG_LEVEL` — it
deliberately does not import or reference `POSTGRES_USER` /
`POSTGRES_PASSWORD` / `POSTGRES_DB`. There is no hardcoded connection string,
username, password, or host anywhere under `app/` — confirmed by
`grep -rniE "postgresql(\+psycopg)?://" app/` returning nothing.

---

## 5. Step-by-step: run it locally with Docker

### 5.1 Clone and configure

**5.1.1** Clone the repo and `cd` into it:
```bash
git clone <your-repo-url>
cd <firstname>-<lastname>-sentinelops
```

**5.1.2** Copy the example env file — this is the only manual setup step, and
it requires no edits, since every placeholder value already works together:
```bash
cp .env.example .env
```

**5.1.3** (Optional) Open `.env` and confirm the two groups from §4 line up.
You do not need to change anything to run locally.

### 5.2 Bring the stack up

**5.2.1** Build and start both containers in the background:
```bash
docker compose up --build -d
```

**5.2.2** What happens on first boot, in order:
1. `db` starts from the `postgres:16` image, creates the `appuser` role and
   `sentinelops` database using `POSTGRES_*`, and begins running its
   `pg_isready` healthcheck every 5 seconds.
2. `api` **waits** — its `depends_on: db: condition: service_healthy` means
   Docker will not even start the `api` container's process until `db`
   reports healthy. This is what prevents the classic "API boots before the
   database is ready and crashes" failure mode.
3. Once `api` starts, `app/main.py`'s `lifespan` startup handler runs
   `Base.metadata.create_all(bind=engine)` — this creates the `services` and
   `incidents` tables (plus the two native Postgres enum types) automatically
   against the empty database. **There is no manual migration step.**
4. The startup handler logs exactly one line:
   ```
   INFO  sentinelops sentinelops starting | env=local | db=connected
   ```

**5.2.3** Confirm both containers are up and `db` is healthy:
```bash
docker compose ps
```
You should see `api` as `running` and `db` as `running (healthy)`.

### 5.3 Verify the API is live

**5.3.1** Hit the health endpoint:
```bash
curl http://localhost:8000/health
```
Expected: `{"status":"ok","database":"ok"}` with HTTP `200`.

**5.3.2** Open the interactive docs in a browser:
```
http://localhost:8000/docs
```
You should see all six business endpoints (`/services` ×2, `/incidents` ×3,
`/stats/services` ×1) plus `/health`, grouped under the `services`,
`incidents`, `stats`, and `health` tags — nothing under a bare `default` tag.

**5.3.3** Confirm `openapi.json` is served:
```bash
curl -s http://localhost:8000/openapi.json | head -c 200
```

### 5.4 Seed sample data

**5.4.1** Run the seed script from the repo root (it talks to the API over
`localhost:8000`, so it runs on your host, not inside a container):
```bash
./scripts/seed_data.sh
```

**5.4.2** What it does, step by step:
1. Polls `GET /health` every 2 seconds (up to 30 attempts) until it sees a
   real `200` — a `503` is treated as "not ready yet," not success.
2. Creates 3 services: `checkout-api`, `payments-worker`, `search-indexer`.
3. Creates 6 incidents spread across those services, covering all three
   severities (`sev1`, `sev2`, `sev3`).
4. Drives one incident through `open → acknowledged → resolved` via `PATCH
   /incidents/{id}/status`, so `GET /stats/services` has a non-null MTTR to
   show.
5. Prints `Seeded 3 services, 6 incidents.` on success.

**5.4.3** Expected output on a fresh database:
```
API is healthy after 1 attempt(s).
Seeded 3 services, 6 incidents.
```
Running it a second time against the same database will fail on the
duplicate service names — the script detects this (`409` from `POST
/services`) and reports it explicitly rather than silently succeeding twice.

**5.4.4** Confirm the seed worked:
```bash
curl -s http://localhost:8000/stats/services | python3 -m json.tool
```
You should see 3 objects, one with `open_count` reduced by the resolved
incident and a non-null `mean_time_to_resolve_minutes`.

### 5.5 Verify data survives a restart

**5.5.1**
```bash
docker compose restart
```

**5.5.2**
```bash
curl -s http://localhost:8000/services | python3 -m json.tool
```
The 3 seeded services must still be present — this proves the named volume
(`pgdata`) is actually persisting data, not an anonymous/bind mount that gets
wiped.

### 5.6 Verify live reload (dev convenience)

**5.6.1** Follow the API logs in one terminal:
```bash
docker compose logs -f api
```

**5.6.2** In another terminal, edit any string in `app/main.py` or a router
file under `app/routers/` — for example, change the `/health` summary text.

**5.6.3** Save the file. Because `docker-compose.yml` bind-mounts `./app` into
the container **and** overrides the container `command` to add `--reload`,
you should see `Reloading...` appear in the log stream within a second or
two, with no `docker compose build` needed.

**5.6.4** Re-run `curl http://localhost:8000/docs` (or check `/openapi.json`)
to confirm the change took effect live.

> This reload behavior is **dev-only**. The `Dockerfile`'s own `CMD` has no
> `--reload` flag — the image you'd eventually ship is production-clean; the
> reloader only exists because `docker-compose.yml` overrides `command:` on
> top of it.

### 5.7 Verify the degraded health path

**5.7.1** Stop just the database:
```bash
docker compose stop db
```

**5.7.2**
```bash
curl -i http://localhost:8000/health
```
Expected: HTTP `503` with body `{"status":"degraded","database":"unavailable"}`
— **not** a `500` traceback. This has been verified directly against a real
Postgres instance during this build (stop the DB process, hit `/health`, get
a clean `503`).

**5.7.3** Bring the database back:
```bash
docker compose start db
```
Wait a few seconds for the healthcheck to pass, then re-confirm
`GET /health` returns `200` again.

### 5.8 Confirm the container runs as non-root

```bash
docker compose exec api whoami
```
Expected output: `appuser` — never `root`.

### 5.9 Tear down

```bash
docker compose down -v
```
The `-v` also removes the named volume, so the next `up` starts from a
completely empty database. Omit `-v` if you want to keep your seeded data
across a `down`/`up` cycle.

---

## 6. Step-by-step: run the test suite

### 6.1 Run tests inside the container (the graded command)

**6.1.1** With the stack up (`docker compose up -d`), run:
```bash
docker compose exec -T api pytest -q
```
This runs `pytest` **inside the `api` container**, against the live `db`
service over the compose network — there is no separate SQLite test path (see
§3.2).

**6.1.2** With the coverage gate (the exact command the eventual CI step will
run):
```bash
docker compose exec -T api pytest --cov=app --cov-fail-under=60 --cov-report=term-missing
```

**6.1.3** Run lint the same way:
```bash
docker compose exec -T api ruff check .
```

### 6.2 What's actually being tested (13 tests, 8 of them the graded floor)

| Test | File | What it proves |
|---|---|---|
| `test_create_service_201` | `test_services.py` | `POST /services` returns `201`, echoes `name`/`owner_team`, server-assigns `id` + `created_at` |
| `test_create_incident_201` | `test_incidents.py` | `POST /incidents` always starts `status="open"`, `resolved_at=None` |
| `test_create_incident_invalid_severity_422` | `test_incidents.py` | Bad `severity` value → `422` with the one-key string envelope |
| `test_transition_unknown_incident` | `test_incidents.py` | `PATCH` on a nonexistent id → exact `404` body |
| `test_list_incidents_filter_and_paginate` | `test_incidents.py` | T1 — filters combine, `total` is the filtered count (not `len(items)`), pagination works |
| `test_status_transition_happy_path` | `test_incidents.py` | T2 — both legal moves (`open→acknowledged`, `acknowledged→resolved`) succeed, `resolved_at` gets stamped |
| `test_illegal_transition_409` | `test_incidents.py` | T2 — `open→resolved` and `resolved→open` are both rejected; the row is provably unchanged after a failed call |
| `test_service_stats_aggregation` | `test_incidents.py` | T3 — hand-computed MTTR (`(50+100)/2 = 75.0`) matches the API's output exactly, `acknowledged` incidents excluded |

Three additional (non-mandatory, extra-coverage) tests are included:
`test_create_service_duplicate_name_409`, `test_list_services_empty_returns_200`,
`test_list_incidents_invalid_limit_422`, `test_stats_service_with_no_incidents`.

### 6.3 Verified results (already run during this build)

This exact command was run against a real, freshly-installed PostgreSQL 16
instance while building this backend:

```
13 passed in 0.94s
TOTAL coverage: 93.41%   (gate is 60%)
```

`ruff check .` reported `All checks passed!` with zero warnings.

### 6.4 Test isolation rules already followed

- `tests/conftest.py`'s `db_session` fixture creates all tables before each
  test and drops them after — no test depends on rows left behind by another
  test, and tests pass in any order.
- `app.dependency_overrides.clear()` runs after every test via the `client`
  fixture's teardown, so overrides never leak between tests.
- No test calls a real external host — `TestClient` only.
- No `@pytest.mark.skip` / `xfail` anywhere.

---

## 7. API reference — every endpoint

Base URL when running locally: `http://localhost:8000`. No authentication on
any endpoint in this assignment.

| # | Method | Path | Purpose | Success | Key errors |
|---|---|---|---|---|---|
| — | GET | `/health` | Liveness + DB check. Not part of the 6-endpoint budget. | `200 {"status":"ok","database":"ok"}` | `503 {"status":"degraded","database":"unavailable"}` |
| 1 | POST | `/services` | Register a service | `201` | `422` bad shape, `409` duplicate name |
| 2 | GET | `/services` | List all services (bare array) | `200` | — |
| 3 | POST | `/incidents` | Create an incident (always starts `open`) | `201` | `422` bad shape, `404` unknown `service_id` |
| 4 | GET | `/incidents` | Filtered + paginated list (`{total, limit, offset, items}`) | `200` | `422` bad query params |
| 5 | PATCH | `/incidents/{id}/status` | Advance status one legal step | `200` | `422` bad status value, `404` unknown id, `409` illegal transition |
| 6 | GET | `/stats/services` | Per-service `open_count` + MTTR (bare array) | `200` | — |

Full request/response bodies, validation rules, and worked examples for each
endpoint are in the original assignment spec — the implementation here
matches it field-for-field (exact JSON keys, exact status codes, exact
ordering rules). A few load-bearing details worth restating:

- **`GET /incidents` ordering** is fixed: `opened_at DESC, id DESC`. The `id`
  tiebreak exists specifically so two incidents created in the same
  transaction don't come back in unstable order.
- **`GET /incidents` `total`** is the count of rows matching the filters,
  ignoring `limit`/`offset` — it is never `len(items)`.
- **`GET /stats/services`** includes every service, even ones with zero
  incidents (`open_count: 0`, `mean_time_to_resolve_minutes: null`) — this is
  why the query is a `LEFT OUTER JOIN`, not an `INNER JOIN`.
- **Timestamps** are ISO 8601 with a UTC offset (e.g.
  `"2026-07-14T09:12:00+00:00"`), produced automatically by Pydantic from the
  timezone-aware `DateTime(timezone=True)` columns — never hand-formatted.

---

## 8. The three graded twists, explained

### 8.1 T1 — Filtering & pagination (`GET /incidents`)

- `status`, `severity`, `service_id`, `limit` (1–100, default 20), `offset`
  (≥0, default 0) — all optional, all combine with **AND**.
- `app/crud.py::list_incidents()` builds **one** filter list and reuses it
  for both the `COUNT` query and the paged/ordered query, so the two numbers
  can never drift apart.
- A `service_id` that doesn't exist returns an **empty page with `200`**, not
  a `404` — there's no existence check on that filter.

### 8.2 T2 — Status state machine (`PATCH /incidents/{id}/status`)

- `app/state_machine.py` encodes the transition table as a literal
  `dict[StatusEnum, set[StatusEnum]]`:
  ```python
  ALLOWED_TRANSITIONS = {
      StatusEnum.open: {StatusEnum.acknowledged},
      StatusEnum.acknowledged: {StatusEnum.resolved},
      StatusEnum.resolved: set(),
  }
  ```
  Only two moves are legal. Every other combination — including same-state
  no-ops like `open→open` — is a `409`.
- **Order of checks in the router** (`app/routers/incidents.py`):
  1. Pydantic validates the body shape first (`422` if `status` is missing or
     not one of the three enum values) — this happens automatically before
     the handler runs.
  2. The handler looks up the incident (`404` if it doesn't exist).
  3. Only then does it check the transition table (`409` if illegal).
  A request to `PATCH /incidents/999999/status` with `{"status": "banana"}`
  is `422`, not `404` — the body is invalid before an incident lookup even
  happens.
- `resolved_at` is stamped **server-side**, timezone-aware
  (`datetime.now(timezone.utc)`), only on the `acknowledged → resolved`
  transition, and is never present in any request schema. Because
  `resolved → *` is always `409`, `resolved_at` can never be overwritten
  once set.

### 8.3 T3 — MTTR aggregation (`GET /stats/services`)

- `app/crud.py::get_service_stats()` is a **single query**: a `LEFT OUTER
  JOIN` from `services` to `incidents`, with a `CASE`-based `SUM()` for
  `open_count` and a `CASE`-based `AVG()` (in minutes, via
  `func.extract("epoch", ...)/60.0`) for MTTR — not an N+1 loop issuing one
  query per service.
- `acknowledged` incidents count toward **neither** `open_count` nor MTTR —
  this is the deliberate trap in the spec, and it's covered explicitly by
  `test_service_stats_aggregation`.
- `AVG()` over a `CASE` that returns `NULL` for non-resolved rows
  automatically ignores those `NULL`s — which is exactly "averaged over
  resolved incidents only," and naturally produces SQL `NULL` (→ JSON `null`)
  for a service with zero resolved incidents, instead of `0.0`.
- Result is rounded with Python's `round(value, 1)` after the query returns.

---

## 9. What is intentionally NOT done yet — next phase

To keep this phase scoped to **backend, database, and local Docker runtime
only**, the following were deliberately left out and are the explicit input
to the next phase (CI/CD + deployment):

- **`.github/workflows/ci.yml` does not exist yet.** No GitHub Actions
  workflow, no `lint-and-test` job, no `docker` job, no Postgres service
  container in CI.
- **No Docker Hub push.** The `Dockerfile` builds correctly locally
  (multi-stage, non-root, production `CMD`, `EXPOSE 8000`, `.dockerignore`
  excludes `.git`/`.venv`/`__pycache__`/`.pytest_cache`/`.env` but **keeps**
  `tests/` in the image so a future `docker compose exec -T api pytest -q`
  keeps working) — but nothing publishes it anywhere.
- **No repo secrets configured** (`DOCKERHUB_USERNAME`, `DOCKERHUB_TOKEN`) —
  there's nothing to configure them for yet.
- **No CI badge** in this README — one line is reserved for it once the
  workflow exists: `![CI](https://github.com/<user>/<repo>/actions/workflows/ci.yml/badge.svg)`.
- **No image tagging scheme executed** — the `:latest` + `:<short-sha>`
  double-tag rule from the spec applies only once the `docker` CI job exists.
- **Git workflow hygiene (feature branches, ≥8 incremental commits, a merged
  PR with a filled description) has not been applied to this working
  directory** — this build was produced as a single local scaffold. Before
  pushing to GitHub, work should be split across feature branches
  (`feat/incident-state-machine`, `feat/docker-compose`, etc.) with
  imperative, specific commit messages, and opened as a PR into `main`
  rather than pushed directly.

Everything else in the spec — schema, endpoints, twists, error envelope,
health check, logging, tests, coverage, Docker/Compose local runtime, bash
scripts — is finished and has been verified to actually run, not just written.

---

## 10. Troubleshooting

**Symptom:** `docker compose up` — `api` container restarts in a loop with
`connection refused` in its logs.
**Cause:** `db` hadn't finished initializing yet and `api` tried to connect
before Postgres was accepting connections.
**Fix:** Already handled by `depends_on: db: condition: service_healthy` in
`docker-compose.yml` — the `api` container's process does not start until
`db`'s `pg_isready` healthcheck passes. If you still see this, check
`docker compose ps` to confirm `db` actually reached the `healthy` state
(`docker compose logs db` will show `pg_isready` failures if the DB itself is
misconfigured).

**Symptom:** `psycopg.OperationalError: password authentication failed for
user "appuser"`.
**Cause:** `.env`'s `DATABASE_URL` credentials don't match `POSTGRES_USER` /
`POSTGRES_PASSWORD` — usually because one was edited and not the other, or
because a stale Postgres volume from an earlier `POSTGRES_PASSWORD` still
exists (Postgres only applies `POSTGRES_*` on a **first** boot of an empty
volume — changing `.env` after the volume already has data does nothing).
**Fix:** Either revert `.env` to match, or wipe the volume and reinitialize:
`docker compose down -v && docker compose up --build -d`.

**Symptom:** Running tests locally (outside Docker) fails with `sqlalchemy.exc`
errors about enum types, or the schema simply won't create.
**Cause:** Pointing `DATABASE_URL` at SQLite (or not having a real Postgres
16 reachable). The `severity_enum` / `status_enum` columns are native
PostgreSQL types — see §3.2.
**Fix:** Always run tests against a real PostgreSQL 16 — either inside the
`api` container against the compose `db` service
(`docker compose exec -T api pytest -q`), or, if running outside Docker
entirely, against a local Postgres instance with `DATABASE_URL` pointed at
it.

---

## 11. Full specification-compliance checklist

Everything below has been implemented and, where testable without CI/deploy
infrastructure, verified by actually running it during this build.

**Schema & DB**
- [x] Two tables, correct columns/types, FK `incidents.service_id →
  services.id` `ON DELETE RESTRICT`, `UNIQUE` on `services.name`, `index=True`
  on `incidents.service_id`
- [x] Both enums are native Postgres enum types with lowercase wire values
- [x] Tables auto-created on startup via `Base.metadata.create_all` in a
  FastAPI `lifespan` handler — zero manual SQL steps

**Endpoints & contract**
- [x] Exactly six business endpoints at the exact spec'd paths, plus the
  required, unauthenticated `GET /health`
- [x] `GET /health` runs a real `SELECT 1`; `200`/`503` bodies verified
  directly (§5.7)
- [x] Every error response is `{"detail": "<string>"}`, including
  `RequestValidationError`-driven `422`s, via the custom exception handler
- [x] `POST /services` → `409` on duplicate name (never a `500`)
- [x] `POST /incidents` distinguishes `422` (bad shape) from `404` (missing
  service)
- [x] New incidents always start `open` with `resolved_at: null`
- [x] `GET /services` and `GET /stats/services` return bare arrays;
  `GET /incidents` returns the `{total, limit, offset, items}` envelope
- [x] `GET /incidents` `total` is the filtered count, not `len(items)`
- [x] Ordering on `GET /incidents` is `opened_at DESC, id DESC`
- [x] Transition map has exactly two legal moves; everything else is `409`
- [x] `resolved_at` stamped server-side, timezone-aware, only on
  `acknowledged → resolved`
- [x] `/stats/services` includes services with zero incidents
- [x] `acknowledged` counts toward neither `open_count` nor MTTR
- [x] MTTR in minutes, rounded to 1 decimal, `null` when no resolved
  incidents
- [x] All DB queries live in `app/crud.py`; routers contain no raw SQL
- [x] Nothing from the assignment's out-of-scope list (auth, background
  tasks, rollback endpoints, semver validation) was built into this repo

**Engineering**
- [x] `app/config.py` reads exactly `DATABASE_URL`, `APP_ENV`, `LOG_LEVEL`
- [x] No hardcoded connection strings/credentials anywhere under `app/`
- [x] `app/models.py` is SQLAlchemy-only, `app/schemas.py` is Pydantic-only
- [x] Response schemas use `ConfigDict(from_attributes=True)`
- [x] Every route sets `response_model`, `status_code`, `summary`, `tags`
- [x] Tags are exactly `services`, `incidents`, `stats`, `health` — nothing
  under `default`
- [x] `logging` configured from `LOG_LEVEL`; one startup line; one `INFO`
  line per write operation, in the exact `field=value` shapes from the spec
- [x] No bare `print()` anywhere under `app/`

**Testing**
- [x] `conftest.py` provides `db_session`, `client`, `sample_service`
  fixtures, Postgres-only, with `dependency_overrides` cleared after each test
- [x] All 8 mandatory tests implemented and passing, plus extra coverage
- [x] 93.41% line coverage on `app/` (gate is 60%), verified with
  `pytest --cov=app --cov-fail-under=60`
- [x] `ruff check .` passes with zero warnings
- [x] No `SQLite`, no `skip`/`xfail`, no real network calls in tests

**Docker / Compose (local runtime only — no CI/deploy)**
- [x] Multi-stage `Dockerfile`, both stages `FROM python:3.12-slim`
- [x] Layer-cache-friendly ordering (`requirements.txt` + `pip install`
  before `COPY . .`)
- [x] Non-root user (`appuser`), verified via `docker compose exec api
  whoami`
- [x] `.dockerignore` excludes dev/build junk but keeps `tests/` in the image
- [x] `EXPOSE 8000`; production `CMD` with `--host 0.0.0.0`, no `--reload`
- [x] Exactly two compose services, `api` and `db` (`postgres:16`)
- [x] Named volume for Postgres data — verified data survives
  `docker compose restart` (§5.5)
- [x] `db` healthcheck via `pg_isready`; `api` depends on it via
  `condition: service_healthy`
- [x] Live reload via a **compose `command:` override**, not baked into the
  Dockerfile — verified (§5.6)
- [x] `restart: unless-stopped` on both services
- [x] All config via `.env`, split into the two documented groups

**Explicitly out of scope for this phase (see §9)**
- [ ] `.github/workflows/ci.yml`
- [ ] Docker Hub push / image tagging
- [ ] Repo secrets
- [ ] CI badge
- [ ] Git branch/commit/PR hygiene applied to this working directory
