#!/usr/bin/env sh
set -eu

if command -v python3 >/dev/null 2>&1; then
  PYTHON=python3
elif command -v python >/dev/null 2>&1; then
  PYTHON=python
else
  echo 'Python 3.11+ is required but was not found on PATH.' >&2
  exit 127
fi

HARNESS_SCRIPT="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)/harness.py"
case "${1-}" in
  remote-actions|remote-exec|release-seal|release-check)
    exec "$PYTHON" -I -S -B "$HARNESS_SCRIPT" "$@"
    ;;
  *)
    exec "$PYTHON" "$HARNESS_SCRIPT" "$@"
    ;;
esac
