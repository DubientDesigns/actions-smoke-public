# Synthetic provider payloads — NOT real API captures

These JSON files were hand-written from the providers' published response
schemas because the development sandbox could not reach the provider hosts
(egress policy). Addresses are made up; numbers are arbitrary. This includes
the goplus_*.json security payloads, whose field names follow the GoPlus docs
but are UNVERIFIED against a live response.

They test our parsers' handling of the *documented* shape and of edge cases
(missing fields, bad addresses, market cap equal to FDV). They do NOT prove
the integration works against the live API.

Real captures go in `../live/` via `scripts/capture_fixtures.sh` and are
exercised by `pytest -m live` / `tests/test_live_fixtures.py`.
