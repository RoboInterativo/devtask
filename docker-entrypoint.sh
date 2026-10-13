#!/bin/sh
set -eu

# ---- helpers ---------------------------------------------------------------
wait_for() {
  host="$1"; port="$2"; name="$3"; timeout="${4:-60}"
  i=0
  until nc -z "$host" "$port" 2>/dev/null; do
    i=$((i+1))
    if [ "$i" -ge "$timeout" ]; then
      echo "ERROR: $name ($host:$port) not reachable after ${timeout}s" >&2
      exit 1
    fi
    echo "waiting for $name ($host:$port)... ${i}s"
    sleep 1
  done
}

# ---- wait for dependencies -------------------------------------------------
: "${POSTGRES_HOST:=db}"
: "${POSTGRES_PORT:=5432}"
: "${REDIS_HOST:=redis}"
: "${REDIS_PORT:=6379}"

wait_for "$POSTGRES_HOST" "$POSTGRES_PORT" "postgres" 60
wait_for "$REDIS_HOST"    "$REDIS_PORT"    "redis"    60

# ---- one-shot init commands (opt-in via env) -------------------------------
if [ "${RUN_MIGRATIONS:-0}" = "1" ]; then
  echo "running migrations..."
  python manage.py migrate --noinput
fi

if [ "${RUN_COLLECTSTATIC:-0}" = "1" ]; then
  echo "collecting static..."
  python manage.py collectstatic --noinput
fi

# ---- exec the passed command ----------------------------------------------
exec "$@"
