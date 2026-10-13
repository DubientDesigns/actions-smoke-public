"""Long-lived provider clients shared by all jobs in a worker process.

Keeping clients alive across job runs preserves rate-limiter and circuit
breaker state, so a provider that is down is not hammered every schedule tick.
"""

from __future__ import annotations

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from cit.config import Settings
from cit.providers import dexscreener, geckoterminal, goplus, telegram
from cit.providers.http import ApiCall, ProviderClient, ProviderPolicy, TokenBucket
from cit.services import runs


class ProviderRuntime:
    def __init__(self, settings: Settings, engine: AsyncEngine, http: httpx.AsyncClient | None = None):
        self.settings = settings
        self.engine = engine
        self.http = http or httpx.AsyncClient(
            timeout=settings.http_timeout_seconds,
            headers={"User-Agent": settings.user_agent},
            follow_redirects=False,
        )
        self.global_bucket = TokenBucket(settings.global_rate_limit_per_minute)
        self._usage: list[ApiCall] = []
        self._clients: dict[str, ProviderClient] = {}

    def _sink(self, call: ApiCall) -> None:
        self._usage.append(call)

    async def client(self, pol: ProviderPolicy) -> ProviderClient:
        # Keyed by name AND base URL: one provider can have several endpoints
        # (e.g. Alchemy has one host per network), each with its own limiter.
        key = f"{pol.name}|{pol.base_url}"
        c = self._clients.get(key)
        if c is None:
            async with self.engine.connect() as conn:
                today = await runs.calls_today(conn, pol.name)
                row = (
                    await conn.execute(
                        text("select rate_limit_per_minute, daily_call_cap from data_sources where slug = :s"),
                        {"s": pol.name},
                    )
                ).one_or_none()
            # data_sources is the operator-editable source of truth for budgets.
            if row is not None:
                if row.rate_limit_per_minute:
                    pol.rate_per_minute = row.rate_limit_per_minute
                pol.daily_cap = row.daily_call_cap
            c = ProviderClient(
                pol, http=self.http, global_bucket=self.global_bucket, usage_sink=self._sink, calls_today=today
            )
            self._clients[key] = c
        return c

    async def geckoterminal(self) -> geckoterminal.GeckoTerminal:
        return geckoterminal.GeckoTerminal(await self.client(geckoterminal.policy()))

    async def dexscreener(self) -> dexscreener.DexScreener:
        return dexscreener.DexScreener(await self.client(dexscreener.policy()))

    async def goplus(self) -> goplus.GoPlus:
        return goplus.GoPlus(await self.client(goplus.policy()))

    async def telegram(self) -> telegram.TelegramBot:
        token = self.settings.telegram_bot_token
        if token is None or not token.get_secret_value():
            raise RuntimeError("CIT_TELEGRAM_BOT_TOKEN is not set")
        return telegram.TelegramBot(await self.client(telegram.policy(token.get_secret_value())))

    async def flush_usage(self) -> int:
        calls, self._usage = self._usage, []
        if not calls:
            return 0
        async with self.engine.begin() as conn:
            return await runs.flush_usage(conn, calls)

    def reset_daily_counters(self) -> None:
        for c in self._clients.values():
            c.calls_today = 0

    async def aclose(self) -> None:
        await self.flush_usage()
        await self.http.aclose()
