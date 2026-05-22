#!/bin/bash
# COT report fetcher — runs every Friday at 3:30 PM EST (20:30 WET/WEST)
# Logs to cot/data/cot_YYYY-MM-DD.log

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_FILE="$SCRIPT_DIR/data/cot_$(date +%Y-%m-%d).log"

echo "===== COT fetch started at $(date) =====" >> "$LOG_FILE"
/usr/bin/python3 "$SCRIPT_DIR/fetch_cot.py" >> "$LOG_FILE" 2>&1
echo "===== COT fetch finished at $(date) =====" >> "$LOG_FILE"
