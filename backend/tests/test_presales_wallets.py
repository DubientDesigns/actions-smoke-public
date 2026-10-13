from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest
import respx

from cit.config import Settings
from cit.providers import alchemy, helius
from cit.scoring.presale_v1 import PresaleInputs, score_presale
from cit.services import presales, wallets
from cit.services.runtime import ProviderRuntime

from .helpers import synthetic

NOW = datetime(2026, 10, 13, tzinfo=UTC)
FULL = PresaleInputs(
    presale_id=1,
    as_of=NOW,
    status="upcoming",
    sale_type="public",
    verification_status="partially_verified",
    official_website="https://proj.example",
    platform="selfhosted",
    team_info="doxxed team (claimed)",
    vesting_terms={"tge_unlock_pct": 20, "cliff_months": 3, "vesting_months": 12},
    lockup_terms="LP locked 1y",
    audit_claims=("AuditCo report (claimed)",),
    sale_price_usd=Decimal("0.01"),
    claimed_valuation_usd=Decimal(20_000_000),
    hard_cap_usd=Decimal(2_000_000),
    sale_start_at=NOW + timedelta(days=3),
    sale_end_at=NOW + timedelta(days=10),
    source_domains=("proj.example", "launchpad.example", "news.example"),
    claims_total=4,
    claims_contradicted=0,
    updated_at=NOW,
)
EMPTY = PresaleInputs(
    presale_id=2,
    as_of=NOW,
    status="unknown",
    sale_type="unknown",
    verification_status="unverified",
    official_website=None,
    platform=None,
    team_info=None,
    vesting_terms=None,
    lockup_terms=None,
    audit_claims=(),
    sale_price_usd=None,
    claimed_valuation_usd=None,
    hard_cap_usd=None,
    sale_start_at=None,
    sale_end_at=None,
    source_domains=(),
    claims_total=0,
    claims_contradicted=0,
    updated_at=NOW,
)


def test_presale_scorecard_rewards_documentation_not_hype():
    full, empty = score_presale(FULL), score_presale(EMPTY)
    assert full.total > 80 and full.risk_flags == []
    assert empty.total == pytest.approx(0) and "no_official_website" in empty.risk_flags
    assert any("TGE unlock unknown" in m for m in empty.missing_data)
    assert full.scoring_version == "presale-heuristic-v1"


def test_presale_red_flags():
    r = score_presale(
        replace(
            FULL,
            verification_status="red_flag",
            claims_contradicted=1,
            vesting_terms={"tge_unlock_pct": 80, "vesting_months": 1},
            sale_end_at=NOW - timedelta(days=1),
        )
    )
    assert {"verification_red_flag", "contradicted_claims", "high_tge_unlock", "sale_end_passed"} <= set(r.risk_flags)
    assert r.total < score_presale(FULL).total - 30


async def test_score_presales_job_dedupes_by_input_hash(engine, clean_db):
    pid = clean_db.execute(
        "insert into presales (project_name, slug, official_website, verification_status, created_by, source_urls) "
        "values ('Proj', 'proj', 'https://proj.example', 'official_source_seen', 'test', "
        "'{https://proj.example/sale}') returning id"
    ).fetchone()[0]
    clean_db.execute(
        "insert into presale_claims (presale_id, field, value, source_url, source_kind) "
        "values (%s, 'hard_cap_usd', '2000000', 'https://launchpad.example/p', 'launchpad')",
        (pid,),
    )
    rt = ProviderRuntime(Settings(), engine, http=httpx.AsyncClient())
    assert (await presales.score_presales(rt))["stored"] == 1
    assert (await presales.score_presales(rt))["stored"] == 0
    clean_db.execute("update presales set team_info = 'named founders' where id = %s", (pid,))
    assert (await presales.score_presales(rt))["stored"] == 1
    total = clean_db.execute("select total from v_presale_score_latest where presale_id = %s", (pid,)).fetchone()[0]
    assert float(total) > 0
    await rt.http.aclose()


def test_alchemy_and_helius_parsers():
    out, _ = alchemy.parse_transfers(
        synthetic("alchemy_transfers_out.json"), "0x9999999999999999999999999999999999999999"
    )
    assert out[0].direction == "out" and out[0].log_index == 12 and out[0].block_number == 0x1312D00
    assert out[0].token_address == "0x2222222222222222222222222222222222222222" and out[0].tx_hash == "0xaaa1"
    ev = helius.parse_transactions(synthetic("helius_transactions.json"), "WalletSol111111111111111111111111111111111")
    kinds = [(e.event_type, e.mint) for e in ev]
    assert ("buy", "SyntheticMint1111111111111111111111111111") in kinds
    assert ("transfer_out", "So11111111111111111111111111111111111111112") in kinds  # SOL leg of swap
    assert ("transfer_in", None) in kinds and [e.amount for e in ev if e.mint is None] == [Decimal("1.5")]


@respx.mock
async def test_sync_wallets_end_to_end(engine, clean_db):
    clean_db.execute(
        "update data_sources set enabled = true, rate_limit_per_minute = 100000 where slug in ('alchemy', 'helius')"
    )
    tok = clean_db.execute(
        "insert into tokens (chain_id, address, symbol) values (2, "
        "'0x2222222222222222222222222222222222222222', 'FOO') returning id"
    ).fetchone()[0]
    pool = clean_db.execute(
        "insert into pools (chain_id, address, base_token_id) values (2, '0xp', %s) returning id", (tok,)
    ).fetchone()[0]
    clean_db.execute(
        "insert into pool_latest (pool_id, token_id, source_id, observed_at, price_usd, liquidity_usd) "
        "values (%s, %s, 1, now(), 2, 100000)",
        (pool, tok),
    )
    evm = clean_db.execute(
        "insert into tracked_wallets (chain_id, address, label, created_by) values (2, "
        "'0x9999999999999999999999999999999999999999', 'deployer', 't') returning id"
    ).fetchone()[0]
    sol = clean_db.execute(
        "insert into tracked_wallets (chain_id, address, label, created_by) values (3, "
        "'WalletSol111111111111111111111111111111111', 'sm', 't') returning id"
    ).fetchone()[0]

    from_blocks: list[int] = []

    def rpc(request):
        import json as _j

        body = _j.loads(request.content)
        if body["method"] == "eth_blockNumber":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": hex(20_000_000)})
        p = body["params"][0]
        from_blocks.append(int(p["fromBlock"], 16))
        name = "alchemy_transfers_out.json" if "fromAddress" in p else "alchemy_transfers_in.json"
        return httpx.Response(200, json=synthetic(name))

    respx.post("https://eth-mainnet.g.alchemy.com/v2/AKEY").mock(side_effect=rpc)
    respx.get("https://api.helius.xyz/v0/addresses/WalletSol111111111111111111111111111111111/transactions").mock(
        return_value=httpx.Response(200, json=synthetic("helius_transactions.json"))
    )
    rt = ProviderRuntime(
        Settings(global_rate_limit_per_minute=100000, alchemy_api_key="AKEY", helius_api_key="HKEY"),
        engine,
        http=httpx.AsyncClient(),
    )
    res = await wallets.sync_wallets(rt)
    assert res["events"] == 5 and res["errors"] == 0
    out = clean_db.execute(
        "select event_type, token_id, value_usd from wallet_events where wallet_id = %s "
        "and event_type = 'transfer_out'",
        (evm,),
    ).fetchone()
    assert out[0] == "transfer_out" and out[1] == tok and float(out[2]) == pytest.approx(3001.0)
    cursor = clean_db.execute("select sync_cursor from tracked_wallets where id = %s", (evm,)).fetchone()[0]
    assert cursor == str(0x1312D05)
    assert clean_db.execute("select sync_cursor from tracked_wallets where id = %s", (sol,)).fetchone()[0] == "sigNEW"
    # Re-running inserts nothing new (dedup on tx hash + log index).
    await wallets.sync_wallets(rt)
    assert clean_db.execute("select count(*) from wallet_events").fetchone()[0] == 5
    # First sync looks back ~7 days; the next one resumes after the newest block seen.
    first = 20_000_000 - alchemy.INITIAL_LOOKBACK_BLOCKS["ethereum"]
    assert from_blocks == [first, first, 0x1312D05 + 1, 0x1312D05 + 1]
    await rt.http.aclose()


async def test_sync_wallets_skips_without_keys(engine, clean_db):
    clean_db.execute(
        "insert into tracked_wallets (chain_id, address, label, created_by) values (2, "
        "'0x9999999999999999999999999999999999999999', 'w', 't')"
    )
    res = await wallets.sync_wallets(ProviderRuntime(Settings(), engine, http=httpx.AsyncClient()))
    assert res["events"] == 0 and len(res["skipped"]) == 2
