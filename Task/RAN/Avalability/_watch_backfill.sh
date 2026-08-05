#!/bin/bash
LOG="/d/01_RPA/Task/RAN/Avalability/run_backfill.log"
SENT="[BACKFILL] 完成"
PyName="ran_kpi_avalability_1day"
deadline=$(( $(date +%s) + 2700 ))   # 45 min hard cap
while [ $(date +%s) -lt $deadline ]; do
  if grep -qF "$SENT" "$LOG" 2>/dev/null; then
    echo "BACKFILL_DONE at $(date '+%Y-%m-%d %H:%M:%S')"
    exit 0
  fi
  # also detect abnormal exit: process gone and no sentinel
  if ! pgrep -f "$PyName" >/dev/null 2>&1; then
    if ! grep -qF "$SENT" "$LOG" 2>/dev/null; then
      echo "BACKFILL_PROCESS_GONE_NO_SENTINEL at $(date '+%Y-%m-%d %H:%M:%S')"
      exit 2
    fi
  fi
  sleep 20
done
echo "WATCHER_TIMEOUT at $(date '+%Y-%m-%d %H:%M:%S')"
exit 3
