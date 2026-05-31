#!/bin/bash
# Run Alembic migrations then hand off to the process passed as arguments (CMD).
set -e

echo "[entrypoint] Running database migrations..."
alembic upgrade head
echo "[entrypoint] Migrations complete."

echo "[entrypoint] Starting: $*"
exec "$@"
