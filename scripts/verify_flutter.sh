#!/usr/bin/env bash
# Flutter verification: pub get -> analyze -> test -> build web.
# Each step prints a clear marker; set STOP_ON_FAIL=0 to continue past failures.
set -uo pipefail
export PATH="$HOME/development/flutter/bin:$PATH"
export NO_PROXY="localhost,127.0.0.1" no_proxy="localhost,127.0.0.1"
cd "$(dirname "$0")/../mobile"

run() {
  echo "=== $* ==="
  "$@"
  local rc=$?
  echo "=== exit $rc ==="
  if [ $rc -ne 0 ] && [ "${STOP_ON_FAIL:-1}" = "1" ]; then exit $rc; fi
}

run flutter pub get
run flutter analyze
run flutter test
run flutter build web --release
echo "FLUTTER_VERIFY_DONE"
