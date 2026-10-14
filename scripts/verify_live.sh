#!/usr/bin/env bash
# Verifies the provider adapters against REAL responses (run on the VPS).
# 1) captures live responses with curl, 2) runs `pytest -m live` in a throwaway
# Python container (the production image has no test dependencies).
# Free public endpoints only; ~20 requests. Writes nothing to the database.
set -euo pipefail
cd "$(dirname "$0")/.."
bash scripts/capture_fixtures.sh
docker run --rm -v "$PWD":/src -w /src/backend python:3.12-slim sh -c '
  pip install -q uv >/dev/null && uv sync --frozen -q && uv run pytest -m live -v -p no:cacheprovider' \
  | tee /tmp/cit-live-results.txt
echo
echo "Results saved to /tmp/cit-live-results.txt (contains no secrets): share the summary line."
