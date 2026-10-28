#!/bin/bash
# Overnight research desk: collector runner.
#   run/run-collector.sh [YYYY-MM-DD]      (default: today, local date)
# Settings (environment, all optional):
#   DESK_ENV_FILE   env file with SEC_USER_AGENT and the free API keys   (default: <repo>/.env)
#   DESK_OUTPUTS    where results go: $DESK_OUTPUTS/<date>/                (default: <repo>/outputs)
#   DESK_EARNINGS   your hand-entered earnings CSV                         (default: <repo>/inputs/earnings-dates.csv)
#   DESK_FLOOR      memory floor in percent; the run stops below it        (default: 10)
#   DESK_WRAPPER    command prefix to run the collector somewhere else, e.g. inside a firewalled container
#                   (see firewall/README.md). Default: run python3 directly; collector/desk/net.py still refuses
#                   every host outside its allow-list.
# Writes brief-inputs.md, flags.md, data.json, sources.csv, status.json, STATUS.md, requests.jsonl, run.log,
# run-meta.json. On any failure it writes STATUS-FAILED.md there. Never prints secrets.
set -u
D=$(cd "$(dirname "$0")/.." && pwd)
. "$D/run/common.sh"
DATE=${1:-$(date +%F)}
FLOOR=${DESK_FLOOR:-10}
OUT=${DESK_OUTPUTS:-$D/outputs}/$DATE
EARN=${DESK_EARNINGS:-$D/inputs/earnings-dates.csv}
mkdir -p "$OUT"; LOG=$OUT/run.log
log() { echo "$(date '+%F %T %Z') $*" | tee -a "$LOG"; }
fail() {
  log "FAILED: $1"
  { echo "# Research desk collector FAILED, $DATE"; echo; echo "- When: $(date '+%F %T %Z')"; echo "- Why: $1";
    echo "- Log: $LOG"; echo "- Fix, then rerun: $D/run/run-collector.sh $DATE"; } > "$OUT/STATUS-FAILED.md"
  exit "${2:-1}"
}
load_env "${DESK_ENV_FILE:-$D/.env}"
[ -n "${SEC_USER_AGENT:-}" ] || fail "SEC_USER_AGENT is not set (copy .env.example to .env and fill it in)" 2
[ -f "$EARN" ] || { mkdir -p "$(dirname "$EARN")"; cp "$D/inputs/earnings-dates.example.csv" "$EARN"; log "created $EARN from the example (header only)"; }
F0=$(free_pct); [ "${F0:-100}" -ge "$FLOOR" ] || fail "free memory ${F0}% < ${FLOOR}% floor; not starting" 4
rm -f "$OUT/STATUS-FAILED.md"
log "start date=$DATE floor=${FLOOR}% free=${F0:-?}% out=$OUT"
START=$(date +%s)
PYTHONDONTWRITEBYTECODE=1 ${DESK_WRAPPER:-} python3 "$D/collector/collect.py" --date "$DATE" --out "$OUT" \
  --config "$D/config/desk.json" --earnings "$EARN" >> "$LOG" 2>&1 &
PID=$!; MINF=${F0:-100}; N=0; ABORT=""
while kill -0 $PID 2>/dev/null; do
  F=$(free_pct); N=$((N+1)); [ -n "$F" ] && [ "$F" -lt "$MINF" ] && MINF=$F
  if [ -n "$F" ] && [ "$F" -lt "$FLOOR" ]; then ABORT="free ${F}% < ${FLOOR}%"; log "watchdog: $ABORT, stopping"; kill $PID 2>/dev/null; fi
  sleep 5
done
wait $PID; RC=$?; END=$(date +%s)
cat > "$OUT/run-meta.json" <<JSON
{"date": "$DATE", "elapsed_s": $((END-START)), "exit_code": $RC, "floor_pct": $FLOOR, "free_pct_start": "${F0:-}",
 "free_pct_min": $MINF, "watchdog_samples": $N, "aborted": "${ABORT}"}
JSON
[ -n "$ABORT" ] && fail "watchdog stopped the run ($ABORT)" 6
[ -f "$OUT/status.json" ] || fail "collector exited $RC without writing status.json (see run.log)" 7
OVERALL=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["overall"])' "$OUT/status.json" 2>/dev/null)
log "done exit=$RC overall=$OVERALL elapsed=$((END-START))s min_free=${MINF}%"
[ "$RC" -eq 0 ] || fail "collector exit $RC (overall=$OVERALL)" "$RC"
exit 0
