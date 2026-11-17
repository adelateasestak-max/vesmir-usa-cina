#!/usr/bin/env bash
# Lokální/cron aktualizace: update + report + export do docs/ (log v logs/refresh.log)
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p logs
exec flock -n logs/.refresh.lock python3 main.py refresh
