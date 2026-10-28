# Shared helpers for the run scripts (sourced, not executed).
# free_pct: free memory in percent. macOS: memory_pressure; Linux: MemAvailable / MemTotal.
free_pct() {
  if command -v memory_pressure >/dev/null 2>&1; then
    memory_pressure | awk -F': ' '/free percentage/{gsub("%","",$2);print $2}'
  elif [ -r /proc/meminfo ]; then
    awk '/MemTotal/{t=$2}/MemAvailable/{a=$2}END{if(t>0)printf "%d\n", a*100/t}' /proc/meminfo
  fi
}
# load_env FILE: export KEY=VALUE lines without echoing them (values never reach logs).
load_env() {
  [ -f "$1" ] || return 0
  set -a; . "$1"; set +a
}
