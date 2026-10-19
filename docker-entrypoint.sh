#!/bin/sh
set -eu

wait_for() {
  host="$1"; port="$2"; name="$3"; timeout="${4:-60}"
  i=0
  until python -c "import socket,sys; s=socket.socket(); s.settimeout(2); sys.exit(0 if s.connect_ex(('$host', $port)) == 0 else 1)" 2>/dev/null; do
    i=$((i+1))
    if [ "$i" -ge "$timeout" ]; then
      echo "ERROR: $name ($host:$port) not reachable after ${timeout}s" >&2
      echo "DNS lookup:" >&2
      getent hosts "$host" >&2 || echo "  not resolvable" >&2
      exit 1
    fi
    echo "waiting for $name ($host:$port)... ${i}s"
    sleep 1
  done
}
wait_for_pg() {
  host="$1"; port="$2"; timeout="${3:-120}"
  i=0
  until pg_isready -h "$host" -p "$port" -q; do
    i=$((i+1))
    if [ "$i" -ge "$timeout" ]; then
      echo "ERROR: postgres ($host:$port) not ready after ${timeout}s" >&2
      exit 1
    fi
    echo "waiting for postgres ($host:$port)... ${i}s"
    sleep 1
  done
}



: "${POSTGRES_HOST:=db}"
: "${POSTGRES_PORT:=5432}"
: "${REDIS_HOST:=redis}"
: "${REDIS_PORT:=6379}"

# wait_for "$POSTGRES_HOST" "$POSTGRES_PORT" "postgres" 240
wait_for_pg "$POSTGRES_HOST" "$POSTGRES_PORT" 240
wait_for "$REDIS_HOST"    "$REDIS_PORT"    "redis"    240

if [ "${RUN_MIGRATIONS:-0}" = "1" ]; then
  echo "running migrations..."
  python manage.py migrate --noinput
fi

if [ "${RUN_COLLECTSTATIC:-0}" = "1" ]; then
  echo "collecting static..."
  python manage.py collectstatic --noinput
fi

exec "$@"
