#!/bin/bash
# Overnight research desk: offline review of one results folder by a local LLM agent ("the reviewer").
#   run/run-review.sh [YYYY-MM-DD]     (default: today)
# The reviewer should read ONLY the results folder (file tools, no web, no shell) and runs on a local model.
# Settings (environment):
#   REVIEW_CMD      REQUIRED. A command that reads the prompt file given as its last argument and prints the review
#                   (Markdown) on stdout, e.g. a local agent CLI in one-shot mode. Example:
#                     REVIEW_CMD="my-agent chat --oneshot --tools file --query-file"
#   DESK_OUTPUTS    results root (default: <repo>/outputs)
#   DESK_FLOOR      memory floor in percent (default: 10)
#   OLLAMA_UNLOAD   optional Ollama model name to unload afterwards (frees its memory), e.g. "qwen3:8b"
# Writes review.md (first line: the final verdict) and review.log into the results folder.
set -u
D=$(cd "$(dirname "$0")/.." && pwd)
. "$D/run/common.sh"
DATE=${1:-$(date +%F)}
FLOOR=${DESK_FLOOR:-10}
OUT=${DESK_OUTPUTS:-$D/outputs}/$DATE
LOG=$OUT/review.log
log() { echo "$(date '+%F %T %Z') $*" | tee -a "$LOG"; }
fail() { log "FAILED: $1"; { echo "# Review FAILED, $DATE"; echo; echo "- When: $(date '+%F %T %Z')"; echo "- Why: $1";
         echo "- Rerun: $D/run/run-review.sh $DATE"; } > "$OUT/REVIEW-FAILED.md"; exit "${2:-1}"; }
[ -d "$OUT" ] || { echo "no results folder $OUT" >&2; exit 2; }
[ -f "$OUT/brief-inputs.md" ] || fail "collector output missing (brief-inputs.md); see STATUS-FAILED.md / run.log" 2
load_env "${DESK_ENV_FILE:-$D/.env}"
[ -n "${REVIEW_CMD:-}" ] || fail "REVIEW_CMD is not set (see the header of this script)" 3
F0=$(free_pct); [ "${F0:-100}" -ge "$FLOOR" ] || fail "free memory ${F0}% < ${FLOOR}% floor; not starting" 4
rm -f "$OUT/REVIEW-FAILED.md"
P=$OUT/review-prompt.md
sed -e "s#{{RESULTS_DIR}}#$OUT#g" -e "s#{{DATE}}#$DATE#g" "$D/reviewer/review-prompt.md" > "$P"
log "start review date=$DATE free=${F0:-?}% floor=${FLOOR}%"
START=$(date +%s)
$REVIEW_CMD "$P" > "$OUT/review.md.tmp" 2>> "$LOG" &
PID=$!; MINF=${F0:-100}; ABORT=""
while kill -0 $PID 2>/dev/null; do
  F=$(free_pct); [ -n "$F" ] && [ "$F" -lt "$MINF" ] && MINF=$F
  if [ -n "$F" ] && [ "$F" -lt "$FLOOR" ]; then ABORT="free ${F}% < ${FLOOR}%"; log "watchdog: $ABORT, stopping the reviewer"; kill $PID 2>/dev/null; fi
  sleep 5
done
wait $PID; RC=$?; END=$(date +%s)
# Final verdict = stricter of the rule-based verdict (from data.json/status.json) and the reviewer's own verdict.
# Small local models sometimes soften the rule; this keeps the verdict honest.
VERDICT=$(python3 "$D/collector/desk/verdict.py" "$OUT" "$OUT/review.md.tmp" 2>>"$LOG" || echo "Final verdict: not computed (see review.log)")
log "$VERDICT"
{ echo "<!-- review of $OUT; generated $(date '+%F %T %Z'); exit $RC; $((END-START))s; min free ${MINF}% -->"; echo "$VERDICT"; echo; cat "$OUT/review.md.tmp"; } > "$OUT/review.md"
rm -f "$OUT/review.md.tmp"
[ -n "${OLLAMA_UNLOAD:-}" ] && curl -s -m 20 http://127.0.0.1:11434/api/generate -d "{\"model\":\"$OLLAMA_UNLOAD\",\"keep_alive\":0}" >/dev/null 2>&1 && log "unloaded $OLLAMA_UNLOAD"
log "done exit=$RC elapsed=$((END-START))s min_free=${MINF}%"
[ -n "$ABORT" ] && fail "watchdog stopped the review ($ABORT)" 6
[ "$RC" -eq 0 ] || fail "reviewer exit $RC (see $LOG)" "$RC"
[ -s "$OUT/review.md" ] || fail "the reviewer produced an empty review" 8
exit 0
