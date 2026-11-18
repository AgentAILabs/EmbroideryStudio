#!/usr/bin/env bash
# The single definition of "all tests". CI runs exactly this script; run it locally before pushing.
set -euo pipefail
cd "$(dirname "$0")/.."
echo "== engine tests";  (cd engine && python3 -m unittest discover -s tests)
echo "== studio tests";  python3 -m unittest discover -s tests
if command -v node >/dev/null 2>&1; then
  echo "== js syntax";   node --check web/app.js && node --check tools/e2e_ui.js
else
  echo "== js syntax skipped (node not installed)"
fi
echo "ALL TESTS PASSED"
