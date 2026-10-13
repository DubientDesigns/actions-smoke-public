from __future__ import annotations

import os

import psycopg
import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from cit.db import engine as engine_mod
from cit.db.migrate import migrate, to_psycopg_dsn

TEST_DSN = os.environ.get("CIT_TEST_DATABASE_URL", "postgresql+psycopg://cit:cit@localhost:5432/cit_test")


def reset_database(dsn: str = TEST_DSN) -> None:
    with psycopg.connect(to_psycopg_dsn(dsn), autocommit=True) as conn:
        conn.execute("drop schema if exists public cascade")
        conn.execute("drop schema if exists cit_meta cascade")
        conn.execute("create schema public")
        conn.execute("grant usage on schema public to public")
    migrate(dsn, local_bootstrap=True)


@pytest.fixture(scope="session")
def migrated_db() -> str:
    reset_database()
    return TEST_DSN


@pytest.fixture
def sync_conn(migrated_db: str):
    with psycopg.connect(to_psycopg_dsn(migrated_db), autocommit=True) as conn:
        yield conn


@pytest.fixture
async def engine(migrated_db: str):
    eng = create_async_engine(migrated_db, pool_size=2)
    engine_mod.set_engine(eng)
    yield eng
    engine_mod.set_engine(None)
    await eng.dispose()


TRUNCATE_TABLES = (
    "paper_fills, paper_orders, paper_positions, paper_portfolios, strategy_evaluations, strategy_definitions, "
    "watchlist_items, watchlists, alerts, research_reports, opportunity_scores, security_assessments, "
    "mention_outcomes, social_mentions, social_channels, influencers, wallet_events, tracked_wallets, "
    "presale_claims, presales, pool_latest, market_snapshots, pools, tokens, ingestion_runs, api_usage, "
    "system_health, app_settings, app_users, audit_log, saved_views"
)


@pytest.fixture
def clean_db(sync_conn):
    sync_conn.execute(f"truncate {TRUNCATE_TABLES} restart identity cascade")
    sync_conn.execute(
        "update data_sources set last_attempt_at = null, last_success_at = null, last_failure_at = null, "
        "last_error = null, consecutive_failures = 0, circuit_state = 'closed', circuit_open_until = null, "
        "enabled = slug not in ('rugcheck', 'telegram_bot', 'anthropic')"
    )
    return sync_conn
