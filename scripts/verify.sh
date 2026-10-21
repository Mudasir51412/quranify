#!/usr/bin/env bash
# Quranify verify harness — counts are derived from pytest, never hand-written.
set -euo pipefail
cd "$(dirname "$0")/../backend"
python -m pytest tests/ -q
echo "VERIFY: AI core green"
