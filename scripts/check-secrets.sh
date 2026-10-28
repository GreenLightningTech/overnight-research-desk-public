#!/bin/bash
# Secrets check: fails if staged (default) or all tracked files (--all) contain anything that looks like a credential.
# Used by .githooks/pre-commit and by tests. Patterns only; it never prints the matched secret value itself.
set -u
cd "$(git rev-parse --show-toplevel)" || exit 2
if [ "${1:-}" = "--all" ]; then FILES=$(git ls-files); else FILES=$(git diff --cached --name-only --diff-filter=ACM); fi
[ -n "$FILES" ] || exit 0
PAT='(api[_-]?key|client[_-]?secret|secret[_-]?key|access[_-]?token|password)["'"'"' ]*[:=]["'"'"' ]*[A-Za-z0-9_\-]{12,}|Token [0-9a-f]{40}|[0-9a-f]{32}\b|ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----|Bearer [A-Za-z0-9._\-]{20,}'
BAD=0
for f in $FILES; do
  [ -f "$f" ] || continue
  case "$f" in tests/fixtures/*|scripts/check-secrets.sh) continue;; esac
  case "$(basename "$f")" in .env.example) ;; *.env|.env*) echo "secrets-check: env file must not be committed: $f"; BAD=1; continue;; esac
  if grep -I -n -E "$PAT" "$f" >/dev/null 2>&1; then
    grep -I -n -E "$PAT" "$f" | cut -d: -f1 | while read -r ln; do echo "secrets-check: possible secret in $f line $ln"; done
    BAD=1
  fi
  # Email addresses: only the placeholder you@example.com (or other example.com/.org addresses) may be committed
  if grep -I -n -o -E "[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}" "$f" | grep -v -q -E "@example\.(com|org)"; then
    echo "secrets-check: real-looking email address in $f (use you@example.com)"; BAD=1
  fi
done
[ $BAD -eq 0 ] && echo "secrets-check: clean ($(echo "$FILES" | wc -l | tr -d ' ') files)"
exit $BAD
