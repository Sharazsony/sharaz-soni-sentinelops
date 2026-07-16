#!/usr/bin/env bash
set -euo pipefail

API_URL="${API_URL:-http://localhost:8000}"
ATTEMPTS=10
TIMEOUT_SECONDS=3

usage() {
  cat <<EOF
Usage: ./scripts/healthcheck.sh [-n ATTEMPTS] [-t TIMEOUT_SECONDS] [-h]
  Env: API_URL (default http://localhost:8000)
  Defaults: ATTEMPTS=10, TIMEOUT_SECONDS=3
EOF
}

parse_args() {
  local OPTIND opt
  while getopts ":n:t:h" opt; do
    case "$opt" in
      n)
        if ! [[ "$OPTARG" =~ ^[0-9]+$ ]]; then
          echo "ERROR: -n requires a numeric value, got '${OPTARG}'" >&2
          exit 2
        fi
        ATTEMPTS="$OPTARG"
        ;;
      t)
        if ! [[ "$OPTARG" =~ ^[0-9]+$ ]]; then
          echo "ERROR: -t requires a numeric value, got '${OPTARG}'" >&2
          exit 2
        fi
        TIMEOUT_SECONDS="$OPTARG"
        ;;
      h)
        usage
        exit 0
        ;;
      \?)
        echo "ERROR: invalid option -${OPTARG}" >&2
        exit 2
        ;;
      :)
        echo "ERROR: option -${OPTARG} requires an argument" >&2
        exit 2
        ;;
    esac
  done
}

probe() {
  local i=1
  local code
  while (( i <= ATTEMPTS )); do
    code=$(curl -s -o /dev/null -w '%{http_code}' --max-time "$TIMEOUT_SECONDS" "${API_URL}/health" 2>/dev/null || echo "000")
    if [[ "$code" == "200" ]]; then
      echo "attempt ${i}/${ATTEMPTS}: 200 OK"
      echo "HEALTHCHECK OK: ${API_URL}/health responded 200 after ${i} attempt(s)"
      exit 0
    elif [[ "$code" == "503" ]]; then
      echo "attempt ${i}/${ATTEMPTS}: 503 degraded"
    elif [[ "$code" == "000" ]]; then
      echo "attempt ${i}/${ATTEMPTS}: connection refused"
    else
      echo "attempt ${i}/${ATTEMPTS}: ${code}"
    fi
    sleep 2
    ((i++))
  done
  echo "HEALTHCHECK FAIL: ${API_URL}/health did not return 200 after ${ATTEMPTS} attempts" >&2
  exit 1
}

main() {
  parse_args "$@"
  probe
}

main "$@"
