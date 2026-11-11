#!/usr/bin/env bash
# Run every test: the app's assert script, then the unittest suites. Non-zero on any failure.
set -u
cd "$(dirname "$0")/.."
rc=0
[ -f app/tests.py ] && { python3 app/tests.py || rc=1; }
compgen -G "tests/test_*.py" >/dev/null && { python3 -m unittest discover -s tests -v || rc=1; }
exit $rc
