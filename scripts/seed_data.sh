#!/usr/bin/env bash
set -euo pipefail

API_URL="${API_URL:-http://localhost:8000}"

usage() {
  cat <<EOF
Usage: ./scripts/seed_data.sh [-h]
  Env: API_URL (default http://localhost:8000)

Seeds 3 services and 6 incidents (covering all three severities) via the
running API, and drives one incident through open -> acknowledged ->
resolved so GET /stats/services has non-empty data to aggregate.
EOF
}

wait_for_api() {
  local attempts=30
  local i=1
  local code
  while (( i <= attempts )); do
    code=$(curl -s -o /dev/null -w '%{http_code}' "${API_URL}/health" || echo "000")
    if [[ "$code" == "200" ]]; then
      echo "API is healthy after ${i} attempt(s)."
      return 0
    fi
    echo "waiting for API... attempt ${i}/${attempts} (status: ${code})"
    sleep 2
    ((i++))
  done
  echo "ERROR: ${API_URL}/health never returned 200 after ${attempts} attempts" >&2
  exit 1
}

_extract_detail() {
  # $1 = response body (possibly not JSON)
  python3 -c 'import sys, json
try:
    print(json.loads(sys.argv[1]).get("detail", "unknown error"))
except Exception:
    print(sys.argv[1])' "$1" 2>/dev/null || echo "$1"
}

create_service() {
  local name="$1" owner="$2"
  local response http_code body
  response=$(curl -s -w '\n%{http_code}' -X POST "${API_URL}/services" \
    -H "Content-Type: application/json" \
    -d "{\"name\": \"${name}\", \"owner_team\": \"${owner}\"}")
  http_code=$(echo "$response" | tail -n1)
  body=$(echo "$response" | sed '$d')

  if [[ "$http_code" == "409" ]]; then
    echo "NOTE: service '${name}' already exists (safe to ignore on a re-run): $(_extract_detail "$body")" >&2
    return 1
  fi
  if [[ "$http_code" != "201" ]]; then
    echo "ERROR creating service '${name}' (status ${http_code}): $(_extract_detail "$body")" >&2
    exit 1
  fi
  echo "$body" | python3 -c 'import sys, json; print(json.load(sys.stdin)["id"])'
}

create_incident() {
  local service_id="$1" title="$2" severity="$3"
  local response http_code body
  response=$(curl -s -w '\n%{http_code}' -X POST "${API_URL}/incidents" \
    -H "Content-Type: application/json" \
    -d "{\"service_id\": ${service_id}, \"title\": \"${title}\", \"severity\": \"${severity}\"}")
  http_code=$(echo "$response" | tail -n1)
  body=$(echo "$response" | sed '$d')

  if [[ "$http_code" != "201" ]]; then
    echo "ERROR creating incident '${title}' (status ${http_code}): $(_extract_detail "$body")" >&2
    exit 1
  fi
  echo "$body" | python3 -c 'import sys, json; print(json.load(sys.stdin)["id"])'
}

transition() {
  local incident_id="$1" status="$2"
  local http_code
  http_code=$(curl -s -o /dev/null -w '%{http_code}' -X PATCH \
    "${API_URL}/incidents/${incident_id}/status" \
    -H "Content-Type: application/json" \
    -d "{\"status\": \"${status}\"}")
  if [[ "$http_code" != "200" ]]; then
    echo "ERROR transitioning incident ${incident_id} to '${status}' (status ${http_code})" >&2
    exit 1
  fi
}

main() {
  if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
    usage
    exit 0
  fi

  wait_for_api

  local svc1 svc2 svc3
  svc1=$(create_service "checkout-api1" "payments") || { echo "Duplicate seed data detected — aborting seed run." >&2; exit 1; }
  svc2=$(create_service "payments-worker" "payments") || exit 1
  svc3=$(create_service "search-indexer" "search") || exit 1

  local i1
  i1=$(create_incident "$svc1" "Checkout 500s on card payments" "sev1")
  create_incident "$svc1" "Slow checkout responses" "sev3" > /dev/null
  create_incident "$svc2" "Worker queue backlog" "sev2" > /dev/null
  create_incident "$svc2" "Worker crash loop" "sev1" > /dev/null
  create_incident "$svc3" "Index lag on search-api" "sev3" > /dev/null
  create_incident "$svc3" "Search returning 404 for valid queries" "sev2" > /dev/null

  transition "$i1" "acknowledged"
  transition "$i1" "resolved"

  echo "Seeded 3 services, 6 incidents."
}

main "$@"
