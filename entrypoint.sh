#!/usr/bin/env bash
#
# Container entrypoint: run first-time setup (idempotent), then exec the
# container's command (uvicorn by default). Works whether PostgreSQL is a
# sibling container or a dedicated host -- setup.py waits for the server and
# creates the database/admin user as needed.
#
# Set SKIP_SETUP=1 to bypass setup entirely (e.g. for one-off commands).
set -e

if [ "${SKIP_SETUP:-0}" != "1" ]; then
    python setup.py
fi

exec "$@"
