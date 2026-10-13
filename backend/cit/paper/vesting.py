"""Presale vesting model (pure).

Schedule (from the presale record, claimed): tge_unlock_pct at TGE, then a cliff
of `cliff_months`, then linear unlock over `vesting_months`. Months are 30 days.
Anything unknown is treated conservatively: no TGE date or no schedule means
nothing is unlocked, so the position cannot be sold or counted as liquid value.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

MONTH_DAYS = Decimal(30)


@dataclass(frozen=True)
class Vesting:
    tge_at: datetime | None
    tge_unlock_pct: Decimal | None
    cliff_months: Decimal | None
    vesting_months: Decimal | None

    @classmethod
    def from_terms(cls, tge_at: datetime | None, terms: dict | None) -> Vesting:
        t = terms or {}

        def d(k: str) -> Decimal | None:
            v = t.get(k)
            return None if v is None else Decimal(str(v))

        return cls(tge_at, d("tge_unlock_pct"), d("cliff_months"), d("vesting_months"))

    @property
    def known(self) -> bool:
        return self.tge_at is not None and self.tge_unlock_pct is not None and self.vesting_months is not None


def unlocked_fraction(v: Vesting, now: datetime) -> Decimal:
    if not v.known or v.tge_at is None or now < v.tge_at:
        return Decimal(0)
    tge = min(Decimal(100), max(Decimal(0), v.tge_unlock_pct or Decimal(0))) / 100
    months = Decimal((now - v.tge_at).total_seconds()) / Decimal(86400) / MONTH_DAYS
    after_cliff = months - (v.cliff_months or Decimal(0))
    if after_cliff <= 0:
        return tge
    vest = v.vesting_months or Decimal(0)
    linear = Decimal(1) if vest <= 0 else min(Decimal(1), after_cliff / vest)
    return tge + (1 - tge) * linear
