"""`cit` command-line entry point."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from cit.config import get_settings
from cit.log import configure_logging


def _cmd_migrate(args: argparse.Namespace) -> int:
    from cit.db.migrate import migrate

    applied = migrate(get_settings().database_url.get_secret_value(), local_bootstrap=args.local_bootstrap)
    print(json.dumps({"applied": applied}))
    return 0


async def _seed() -> list[str]:
    from cit import appsettings
    from cit.db.engine import get_engine

    async with get_engine().begin() as conn:
        return await appsettings.seed_defaults(conn)


async def _run_job(name: str) -> object:
    from cit.db.engine import get_engine
    from cit.services.runtime import ProviderRuntime
    from cit.worker.jobs import run_job

    rt = ProviderRuntime(get_settings(), get_engine())
    try:
        return await run_job(name, rt)
    finally:
        await rt.aclose()


async def _report() -> str:
    from cit.db.engine import get_engine
    from cit.services import ops

    async with get_engine().connect() as conn:
        return ops.format_health_report_text(await ops.build_health_report(conn))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="cit", description="Crypto Intelligence Terminal backend")
    sub = p.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("migrate", help="apply pending SQL migrations")
    m.add_argument(
        "--local-bootstrap",
        action="store_true",
        help="create Supabase stand-ins (auth schema, roles) on plain Postgres; never on Supabase",
    )
    sub.add_parser("seed-settings", help="insert default app_settings rows if missing")
    sub.add_parser("worker", help="run the scheduler")
    a = sub.add_parser("api", help="run the internal API")
    a.add_argument("--host", default="0.0.0.0")  # noqa: S104 - container-internal network only
    a.add_argument("--port", type=int, default=8000)
    j = sub.add_parser("run-job", help="run one job now")
    from cit.worker.jobs import JOBS

    j.add_argument("name", choices=sorted(JOBS))
    sub.add_parser("health-report", help="print the operational health report")
    args = p.parse_args(argv)

    s = get_settings()
    configure_logging(s.log_level, s.log_json)
    if args.cmd == "migrate":
        return _cmd_migrate(args)
    if args.cmd == "seed-settings":
        print(json.dumps({"seeded": asyncio.run(_seed())}))
        return 0
    if args.cmd == "worker":
        from cit.worker.scheduler import run_worker

        asyncio.run(run_worker())
        return 0
    if args.cmd == "api":
        import uvicorn

        uvicorn.run("cit.api.main:app", host=args.host, port=args.port, proxy_headers=False, access_log=False)
        return 0
    if args.cmd == "run-job":
        print(json.dumps(asyncio.run(_run_job(args.name)), default=str, indent=2))
        return 0
    if args.cmd == "health-report":
        print(asyncio.run(_report()))
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
