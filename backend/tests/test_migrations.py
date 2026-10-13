from __future__ import annotations

import json
import uuid

import psycopg
import pytest

from cit.chains import CHAINS
from cit.db.migrate import MigrationError, migrate, to_psycopg_dsn

REQUIRED_TABLES = {
    "chains",
    "tokens",
    "pools",
    "market_snapshots",
    "presales",
    "data_sources",
    "ingestion_runs",
    "security_assessments",
    "influencers",
    "social_mentions",
    "tracked_wallets",
    "wallet_events",
    "opportunity_scores",
    "research_reports",
    "watchlists",
    "alerts",
    "paper_portfolios",
    "paper_positions",
    "paper_orders",
    "paper_fills",
    "strategy_definitions",
    "strategy_evaluations",
    "api_usage",
    "system_health",
}


def test_all_required_tables_exist(sync_conn):
    rows = sync_conn.execute("select tablename from pg_tables where schemaname = 'public'").fetchall()
    assert REQUIRED_TABLES <= {r[0] for r in rows}


def test_rls_enabled_on_every_public_table(sync_conn):
    rows = sync_conn.execute(
        "select relname from pg_class c join pg_namespace n on n.oid = c.relnamespace "
        "where n.nspname = 'public' and c.relkind = 'r' and not c.relrowsecurity"
    ).fetchall()
    assert rows == []


def test_migrations_are_idempotent(migrated_db):
    assert migrate(migrated_db, local_bootstrap=True) == []


def test_modified_migration_is_refused(migrated_db, tmp_path):
    from cit.db import migrate as m

    for src in m.discover():
        (tmp_path / src.path.name).write_text(src.sql)
    first = sorted(tmp_path.glob("*.sql"))[0]
    first.write_text(first.read_text() + "\n-- edited\n")
    with pytest.raises(MigrationError, match="modified"):
        migrate(migrated_db, directory=tmp_path)


def test_chain_seed_matches_python_registry(sync_conn):
    rows = sync_conn.execute(
        "select id, slug, evm_chain_id, geckoterminal_network, dexscreener_chain, goplus_chain from chains order by id"
    ).fetchall()
    assert rows == [
        (c.id, c.slug, c.evm_chain_id, c.geckoterminal_network, c.dexscreener_chain, c.goplus_chain) for c in CHAINS
    ]


def test_token_uniqueness_per_chain(clean_db):
    clean_db.execute("insert into tokens (chain_id, address) values (1, '0xabc')")
    clean_db.execute("insert into tokens (chain_id, address) values (4, '0xabc')")  # same address, other chain ok
    with pytest.raises(psycopg.errors.UniqueViolation):
        clean_db.execute("insert into tokens (chain_id, address) values (1, '0xabc')")


def _as_user(conn, user_id: uuid.UUID | None, role: str = "authenticated"):
    conn.execute(f"set role {role}")
    claims = json.dumps({"sub": str(user_id)}) if user_id else ""
    conn.execute("select set_config('request.jwt.claims', %s, false)", (claims,))


def test_rls_blocks_non_allowlisted_and_anon(migrated_db, clean_db):
    clean_db.execute("insert into tokens (chain_id, address, symbol) values (1, '0x01', 'AAA')")
    member, stranger = uuid.uuid4(), uuid.uuid4()
    clean_db.execute("insert into app_users (user_id, email, role) values (%s, 'me@example.com', 'owner')", (member,))
    with psycopg.connect(to_psycopg_dsn(migrated_db), autocommit=True) as c:
        _as_user(c, None, "anon")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            c.execute("select count(*) from tokens").fetchone()
        c.execute("reset role")
        _as_user(c, stranger)
        assert c.execute("select count(*) from tokens").fetchone()[0] == 0
        c.execute("reset role")
        _as_user(c, member)
        assert c.execute("select count(*) from tokens").fetchone()[0] == 1
        # Research tables are read-only for browser users.
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            c.execute("insert into tokens (chain_id, address) values (1, '0x02')")


def test_rls_watchlists_are_private_per_user(migrated_db, clean_db):
    a, b = uuid.uuid4(), uuid.uuid4()
    for u, e in ((a, "a@example.com"), (b, "b@example.com")):
        clean_db.execute("insert into app_users (user_id, email) values (%s, %s)", (u, e))
    clean_db.execute("insert into watchlists (owner_id, name) values (%s, 'mine')", (a,))
    with psycopg.connect(to_psycopg_dsn(migrated_db), autocommit=True) as c:
        _as_user(c, b)
        assert c.execute("select count(*) from watchlists").fetchone()[0] == 0
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            c.execute("insert into watchlists (owner_id, name) values (%s, 'spoof')", (a,))
        c.execute("reset role")
        _as_user(c, a)
        assert c.execute("select count(*) from watchlists").fetchone()[0] == 1


def test_paper_fill_lookahead_is_rejected_by_database(clean_db):
    tok = clean_db.execute("insert into tokens (chain_id, address) values (1, '0x01') returning id").fetchone()[0]
    pf = clean_db.execute("insert into paper_portfolios (name) values ('t') returning id").fetchone()[0]
    order = clean_db.execute(
        "insert into paper_orders (portfolio_id, token_id, side, order_type, origin, signal_at, earliest_fill_at, "
        "requested_notional_usd) values (%s, %s, 'buy', 'market', 'manual', "
        "'2026-01-01 00:00Z', '2026-01-01 00:01Z', 100) returning id",
        (pf, tok),
    ).fetchone()[0]
    with pytest.raises(psycopg.errors.CheckViolation, match="look-ahead"):
        clean_db.execute(
            "insert into paper_fills (order_id, price_observed_at, reference_price_usd, executed_price_usd, quantity)"
            " values (%s, '2026-01-01 00:00:30Z', 1, 1, 1)",
            (order,),
        )
    clean_db.execute(
        "insert into paper_fills (order_id, price_observed_at, reference_price_usd, executed_price_usd, quantity)"
        " values (%s, '2026-01-01 00:01:00Z', 1, 1, 1)",
        (order,),
    )


def test_order_cannot_fill_before_signal(clean_db):
    pf = clean_db.execute("insert into paper_portfolios (name) values ('t') returning id").fetchone()[0]
    tok = clean_db.execute("insert into tokens (chain_id, address) values (1, '0x09') returning id").fetchone()[0]
    with pytest.raises(psycopg.errors.CheckViolation):
        clean_db.execute(
            "insert into paper_orders (portfolio_id, token_id, side, order_type, origin, signal_at, earliest_fill_at)"
            " values (%s, %s, 'buy', 'market', 'manual', '2026-01-01 00:01Z', '2026-01-01 00:00Z')",
            (pf, tok),
        )


def test_opportunity_score_requires_matching_target(clean_db):
    with pytest.raises(psycopg.errors.CheckViolation):
        clean_db.execute(
            "insert into opportunity_scores (scorecard, scoring_version, data_cutoff_at, total, components, "
            "inputs_hash) values ('token', 'v1', now(), 50, '{}', 'h')"
        )


def test_dashboard_views_respect_rls(migrated_db, clean_db):
    clean_db.execute("insert into tokens (chain_id, address, symbol) values (1, '0x01', 'AAA')")
    member = uuid.uuid4()
    clean_db.execute("insert into app_users (user_id, email) values (%s, 'm@example.com')", (member,))
    with psycopg.connect(to_psycopg_dsn(migrated_db), autocommit=True) as c:
        _as_user(c, uuid.uuid4())
        assert c.execute("select count(*) from v_token_overview").fetchone()[0] == 0
        c.execute("reset role")
        _as_user(c, member)
        assert c.execute("select count(*) from v_token_overview").fetchone()[0] == 1


def test_phase3_views_respect_rls(migrated_db, clean_db):
    tok = clean_db.execute("insert into tokens (chain_id, address) values (1, '0x01') returning id").fetchone()[0]
    clean_db.execute(
        "insert into security_assessments (token_id, source_id, valid_until, coverage, risk_level, ruleset_version) "
        "values (%s, 1, now() + interval '1 day', 'complete', 'low', 'v')",
        (tok,),
    )
    clean_db.execute(
        "insert into opportunity_scores (token_id, scorecard, scoring_version, data_cutoff_at, total, components, "
        "inputs_hash) values (%s, 'token', 'v', now(), 50, '{}', 'h')",
        (tok,),
    )
    member = uuid.uuid4()
    clean_db.execute("insert into app_users (user_id, email) values (%s, 'm@example.com')", (member,))
    with psycopg.connect(to_psycopg_dsn(migrated_db), autocommit=True) as c:
        for view in ("v_security_latest", "v_score_latest"):
            _as_user(c, uuid.uuid4())
            assert c.execute(f"select count(*) from {view}").fetchone()[0] == 0, view
            c.execute("reset role")
            _as_user(c, member)
            assert c.execute(f"select count(*) from {view}").fetchone()[0] == 1, view
            c.execute("reset role")
        _as_user(c, member)
        row = c.execute("select risk_level, score_total from v_token_overview").fetchone()
        assert row[0] == "low" and float(row[1]) == 50


def test_phase4_owner_can_curate_viewer_cannot(migrated_db, clean_db):
    owner, viewer = uuid.uuid4(), uuid.uuid4()
    clean_db.execute(
        "insert into app_users (user_id, email, role) values (%s, 'o@example.com', 'owner'), "
        "(%s, 'v@example.com', 'viewer')",
        (owner, viewer),
    )
    with psycopg.connect(to_psycopg_dsn(migrated_db), autocommit=True) as c:
        _as_user(c, owner)
        c.execute("insert into influencers (display_name) values ('X')")
        c.execute(
            "insert into social_channels (platform, external_id, access_basis) values ('telegram', '-1', 'public')"
        )
        c.execute("reset role")
        _as_user(c, viewer)
        assert c.execute("select count(*) from social_channels").fetchone()[0] == 1
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            c.execute("insert into influencers (display_name) values ('Y')")
        c.execute("reset role")
        _as_user(c, owner)
        # Workers' private state is never readable from the browser roles.
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            c.execute("select * from worker_state")
