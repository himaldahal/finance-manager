#!/usr/bin/env bash
# One-command setup: virtualenv, dependencies, .env, database, and (optionally) demo data.
#
#   scripts/bootstrap.sh            set everything up
#   scripts/bootstrap.sh --demo     also create a demo user (demo / demo-password-123) with sample data
#   scripts/bootstrap.sh --run      start the development server when done
set -eu
cd "$(dirname "$0")/.."

demo=0
run=0
for arg in "$@"; do
  case "$arg" in
    --demo) demo=1 ;;
    --run) run=1 ;;
    -h|--help) sed -n '2,7p' "$0"; exit 0 ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

PYTHON="${PYTHON:-python3}"
if ! "$PYTHON" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)'; then
  echo "Python 3.9 or newer is required." >&2
  exit 1
fi

if [ ! -d .venv ]; then
  "$PYTHON" -m venv .venv
fi
# shellcheck disable=SC1091
. .venv/bin/activate
python -m pip install --quiet --upgrade pip
python -m pip install --quiet -r requirements.txt

if [ ! -f .env ]; then
  key=$(python -c 'from django.core.management.utils import get_random_secret_key as k; print(k())')
  cp .env.example .env
  # a development setup: debug on, with a fresh random secret key
  sed -i.bak -e "s|^SECRET_KEY=.*|SECRET_KEY=${key}|" -e 's|^DEBUG=.*|DEBUG=1|' .env && rm -f .env.bak
  echo "Created .env with a new secret key (DEBUG=1 for local use)."
fi

python manage.py migrate
if [ "$demo" -eq 1 ]; then
  python manage.py seed_demo || echo "Demo user already exists, skipping."
fi
python manage.py check

echo
echo "All set. Start the server with:"
echo "  . .venv/bin/activate && python manage.py runserver"
if [ "$run" -eq 1 ]; then
  exec python manage.py runserver
fi
