"""Minimal, ordered SQL migration runner.

The SQL files in db/migrations are the single source of truth for the schema.
Applied versions are tracked in cit_meta.schema_migrations together with a
checksum, so an edited, already-applied migration is detected and refused.

Do not mix this runner with `supabase db push` on the same database.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

import psycopg

REPO_ROOT = Path(__file__).resolve().parents[3]
DB_DIR = Path(os.environ.get("CIT_DB_DIR", REPO_ROOT / "db"))
MIGRATIONS_DIR = DB_DIR / "migrations"
LOCAL_BOOTSTRAP = DB_DIR / "bootstrap_local.sql"


@dataclass(frozen=True)
class Migration:
    version: str
    path: Path

    @property
    def sql(self) -> str:
        return self.path.read_text()

    @property
    def checksum(self) -> str:
        return hashlib.sha256(self.path.read_bytes()).hexdigest()


class MigrationError(RuntimeError):
    pass


def discover(directory: Path = MIGRATIONS_DIR) -> list[Migration]:
    files = sorted(p for p in directory.glob("*.sql"))
    versions = [p.stem.split("_", 1)[0] for p in files]
    if len(set(versions)) != len(versions):
        raise MigrationError(f"duplicate migration version numbers in {directory}")
    return [Migration(v, p) for v, p in zip(versions, files, strict=True)]


def to_psycopg_dsn(url: str) -> str:
    """Accept SQLAlchemy-style URLs (postgresql+psycopg://) as well as plain DSNs."""
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def migrate(dsn: str, *, local_bootstrap: bool = False, directory: Path = MIGRATIONS_DIR) -> list[str]:
    """Apply pending migrations; return the versions applied."""
    applied_now: list[str] = []
    with psycopg.connect(to_psycopg_dsn(dsn), autocommit=False) as conn:
        if local_bootstrap:
            conn.execute(LOCAL_BOOTSTRAP.read_text())
            conn.commit()
        conn.execute("create schema if not exists cit_meta")
        conn.execute(
            """
            create table if not exists cit_meta.schema_migrations (
              version    text primary key,
              filename   text not null,
              checksum   text not null,
              applied_at timestamptz not null default now()
            )
            """
        )
        # Serialise concurrent runners (e.g. worker + api starting together).
        conn.execute("select pg_advisory_xact_lock(hashtext('cit_migrations'))")
        rows = conn.execute("select version, checksum from cit_meta.schema_migrations").fetchall()
        done = {v: c for v, c in rows}
        for m in discover(directory):
            if m.version in done:
                if done[m.version] != m.checksum:
                    raise MigrationError(
                        f"migration {m.path.name} was modified after being applied; add a new migration instead"
                    )
                continue
            conn.execute(m.sql)  # type: ignore[arg-type]
            conn.execute(
                "insert into cit_meta.schema_migrations (version, filename, checksum) values (%s, %s, %s)",
                (m.version, m.path.name, m.checksum),
            )
            applied_now.append(m.version)
        conn.commit()
    return applied_now
