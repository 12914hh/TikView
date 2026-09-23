#!/bin/bash
# 每小时跑一次：到点或需补跑时才执行 pull.py --write
set -euo pipefail
cd "$(dirname "$0")"
LOG="${PWD}/cron.log"
{
  echo "==== $(date -u +%Y-%m-%dT%H:%M:%SZ) ===="
  out="$(.venv/bin/python auto_sync_due.py)"
  echo "$out"
  if echo "$out" | grep -qE '本次执行|本次补跑'; then
    .venv/bin/python pull.py --write
  fi
} >>"$LOG" 2>&1
