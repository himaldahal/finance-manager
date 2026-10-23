#!/usr/bin/env bash
# Fails when a text file contains an em dash, en dash or horizontal bar, or one of the forbidden words.
# Checks tracked files plus new (untracked, not ignored) files; falls back to find outside a git checkout.
set -u
FORBIDDEN="$(echo Y2xhdWRlfGFudGhyb3BpY3xqdWxlc3xnb29nbGVbIC1dbGFicw== | base64 -d)"  # encoded so the words never appear in the repo
cd "$(dirname "$0")/.."

if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  files=$(git ls-files --cached --others --exclude-standard)
else
  files=$(find . -type f -not -path './.git/*' -not -path './.venv/*' -not -path '*/__pycache__/*' | sed 's|^\./||')
fi

status=0
for f in $files; do
  [ -f "$f" ] || continue
  case "$f" in
    *.png|*.jpg|*.jpeg|*.gif|*.ico|*.woff|*.woff2|*.pyc|*.sqlite3|app/static/app/icons/LICENSE) continue ;;
  esac
  grep -Iq . "$f" 2>/dev/null || continue   # skip binary and empty files
  if grep -nP '\x{2014}|\x{2013}|\x{2015}' "$f" >/dev/null 2>&1 || LC_ALL=C.UTF-8 grep -nP '\xe2\x80[\x93\x94\x95]' "$f" >/dev/null 2>&1; then
    echo "dash character found in $f:"
    grep -nP '\x{2014}|\x{2013}|\x{2015}' "$f" 2>/dev/null | head -3
    status=1
  fi
  if grep -niE "$FORBIDDEN" "$f" >/dev/null 2>&1; then
    echo "forbidden word in $f:"
    grep -niE "$FORBIDDEN" "$f" | head -3
    status=1
  fi
done

if [ "$status" -eq 0 ]; then
  echo "hygiene check passed"
fi
exit "$status"
