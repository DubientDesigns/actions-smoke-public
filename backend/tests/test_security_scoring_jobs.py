"""assess_security and score_tokens end to end: mocked GoPlus (SYNTHETIC payloads) -> real Postgres."""

from __future__ import annotations

import httpx
import respx

from cit.config import Settings
from cit.services import scoring, security
from cit.services.runtime import ProviderRuntime

from .helpers import synthetic

GP = "https://api.gopluslabs.io/api/v1"
CLEAN = "0x2222222222222222222222222222222222222222"
HONEY = "0x4444444444444444444444444444444444444444"
MINT = "SyntheticMint1111111111111111111111111111"


def runtime(engine) -> ProviderRuntime:
    return ProviderRuntime(Settings(global_rate_limit_per_minute=100000), engine, http=httpx.AsyncClient())


def add_token(conn, chain_id, address, liquidity, pool_address):
    tid = conn.execute("insert into tokens (chain_id, address, symbol) values (%s, %s, 'T') returning id",
                       (chain_id, address)).fetchone()[0]
    pid = conn.execute("insert into pools (chain_id, address, base_token_id, pool_created_at) "
                       "values (%s, %s, %s, now() - interval '2 days') returning id",
                       (chain_id, pool_address, tid)).fetchone()[0]
    conn.execute("insert into pool_latest (pool_id, token_id, source_id, observed_at, liquidity_usd, volume_h24_usd,"
                 " buys_h24, sells_h24, price_change_h24, fdv_usd) values (%s, %s, 1, now(), %s, 50000, 300, 200,"
                 " 5, 1000000)", (pid, tid, liquidity))
    return tid


def setup(conn):
    conn.execute("update data_sources set rate_limit_per_minute = 100000")
    ids = {
        "clean": add_token(conn, 1, CLEAN, 30000, "0x1111111111111111111111111111111111111111"),
        "honey": add_token(conn, 2, HONEY, 30000, "0x9999999999999999999999999999999999999999"),
        "illiquid": add_token(conn, 1, "0x7777777777777777777777777777777777777777", 100,
                              "0x8888888888888888888888888888888888888888"),
        "mint": add_token(conn, 3, MINT, 30000, "SyntheticPool11111111111111111111111111111"),
    }
    return ids


def mock_goplus(not_found_for=None, rate_limit=False):
    def evm(request):
        addr = request.url.params["contract_addresses"]
        if rate_limit:
            return httpx.Response(200, json=synthetic("goplus_rate_limited.json"))
        if addr == not_found_for:
            return httpx.Response(200, json=synthetic("goplus_not_found.json"))
        name = {CLEAN: "goplus_evm_clean.json", HONEY: "goplus_evm_honeypot.json"}[addr]
        return httpx.Response(200, json=synthetic(name))

    respx.get(url__regex=rf"{GP}/token_security/\d+").mock(side_effect=evm)
    respx.get(f"{GP}/solana/token_security").mock(
        return_value=httpx.Response(200, json=synthetic("goplus_solana_freeze.json")))


@respx.mock
async def test_assess_security_end_to_end(engine, clean_db):
    ids = setup(clean_db)
    mock_goplus()
    rt = runtime(engine)
    res = await security.assess_security(rt)
    assert res["candidates"] == 3 and res["assessed"] == 3 and res["hard_excluded"] == 2  # illiquid skipped
    rows = dict(clean_db.execute(
        "select token_id, risk_level from v_security_latest").fetchall())
    assert rows == {ids["clean"]: "low", ids["honey"]: "critical", ids["mint"]: "critical"}
    # Pool address excluded from concentration via the pools table.
    top10 = clean_db.execute("select top10_holder_pct from security_assessments where token_id = %s",
                             (ids["clean"],)).fetchone()[0]
    assert float(top10) == 9.0

    # Fresh assessments are not repeated...
    assert (await security.assess_security(rt))["candidates"] == 0
    # ...stale ones are, comparing total supply with the previous assessment.
    clean_db.execute("update security_assessments set valid_until = now() - interval '1 minute' where token_id = %s",
                     (ids["clean"],))
    assert (await security.assess_security(rt))["assessed"] == 1
    checks = clean_db.execute("select checks from v_security_latest where token_id = %s",
                              (ids["clean"],)).fetchone()[0]
    assert {c["key"]: c["status"] for c in checks}["supply_change"] == "pass"
    run = clean_db.execute("select status, http_calls from ingestion_runs order by id desc limit 1").fetchone()
    assert run == ("success", 1)
    await rt.http.aclose()


@respx.mock
async def test_not_found_retried_sooner(engine, clean_db):
    ids = setup(clean_db)
    mock_goplus(not_found_for=CLEAN)
    rt = runtime(engine)
    await security.assess_security(rt)
    cov, hours = clean_db.execute(
        "select coverage, extract(epoch from valid_until - assessed_at) / 3600 from security_assessments "
        "where token_id = %s", (ids["clean"],)).fetchone()
    assert cov == "not_found" and float(hours) == 6
    await rt.http.aclose()


@respx.mock
async def test_rate_limited_envelope_records_no_assessment(engine, clean_db):
    setup(clean_db)
    clean_db.execute("delete from tokens where chain_id = 3")  # EVM only
    mock_goplus(rate_limit=True)
    rt = runtime(engine)
    res = await security.assess_security(rt)
    assert res["assessed"] == 0 and res["errors"] == 2
    assert clean_db.execute("select count(*) from security_assessments").fetchone()[0] == 0
    run = clean_db.execute("select status, error from ingestion_runs").fetchone()
    assert run[0] == "failed" and "4029" in run[1]
    src = clean_db.execute("select consecutive_failures from data_sources where slug = 'goplus'").fetchone()[0]
    assert src == 1
    await rt.http.aclose()


async def test_disabled_source_is_skipped(engine, clean_db):
    setup(clean_db)
    clean_db.execute("update data_sources set enabled = false where slug = 'goplus'")
    assert (await security.assess_security(runtime(engine)))["skipped"]


@respx.mock
async def test_score_tokens_stores_only_material_changes(engine, clean_db):
    ids = setup(clean_db)
    mock_goplus()
    rt = runtime(engine)
    assert (await security.assess_security(rt))["assessed"] == 3
    first = await scoring.score_tokens(rt)
    assert first["scored"] == 3 and first["stored"] == 3
    again = await scoring.score_tokens(rt)
    assert again["stored"] == 0  # nothing material changed
    over = dict(clean_db.execute(
        "select token_id, score_total from v_token_overview where score_total is not null").fetchall())
    assert set(over) == {ids["clean"], ids["honey"], ids["mint"]}
    assert over[ids["clean"]] > over[ids["honey"]]  # hard exclusion zeroes security
    comps, flags = clean_db.execute(
        "select components, risk_flags from v_score_latest where token_id = %s", (ids["honey"],)).fetchone()
    assert comps["security"]["score"] == 0 and "hard_excluded" in flags
    # A material change (liquidity collapse) produces a new row.
    clean_db.execute("update pool_latest set liquidity_usd = 2500 where token_id = %s", (ids["clean"],))
    assert (await scoring.score_tokens(rt))["stored"] == 1
    await rt.http.aclose()
