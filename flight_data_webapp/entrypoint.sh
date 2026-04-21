#!/bin/sh
# Wait for the shared TSN DB file to appear before starting Flask.
# This avoids a race where flight-assistant boots first and creates an empty
# tsn_analyzer.db with only its own 3 tables, which may confuse the TSN
# backend's first-run schema/PRAGMA setup.
#
# Behaviour:
#   - If FLIGHT_DATA_DB_PATH is set, wait up to ${FLIGHT_DATA_WAIT_SECS:-60}s
#     for the file to exist. Once present, continue.
#   - If the timeout elapses, continue anyway (flight-assistant will create the
#     file itself and the TSN backend will still add its missing tables when it
#     eventually starts -- SQLite schemas coexist by table name).

set -eu

WAIT_SECS="${FLIGHT_DATA_WAIT_SECS:-60}"
DB_PATH="${FLIGHT_DATA_DB_PATH:-}"

if [ -n "$DB_PATH" ]; then
    elapsed=0
    while [ "$elapsed" -lt "$WAIT_SECS" ]; do
        if [ -f "$DB_PATH" ]; then
            echo "[entrypoint] shared DB detected at $DB_PATH (waited ${elapsed}s)"
            break
        fi
        sleep 1
        elapsed=$((elapsed + 1))
    done
    if [ ! -f "$DB_PATH" ]; then
        echo "[entrypoint] WARN: $DB_PATH not present after ${WAIT_SECS}s; starting anyway (flight-assistant will create it)."
    fi
fi

exec "$@"
