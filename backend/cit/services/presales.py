"""score_presales job: presale scorecard for every non-cancelled presale.

A row is stored only when the inputs change (hash differs from the latest
score), so re-running is cheap and the history shows each material change.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import text

from cit.scoring.presale_v1 import PresaleInputs, score_presale
from cit.services import runs
from cit.services.runtime import ProviderRuntime

_ROWS = text("""
select p.*,
  (select count(*) from presale_claims c where c.presale_id = p.id) as claims_total,
  (select count(*) from presale_claims c where c.presale_id = p.id and c.verification = 'contradicted') as contradicted,
  (select array_agg(c.source_url) from presale_claims c where c.presale_id = p.id and c.source_url is not null)
    as claim_urls,
  (select inputs_hash from opportunity_scores o where o.presale_id = p.id and o.scorecard = 'presale'
     order by scored_at desc limit 1) as last_hash
from presales p where p.status <> 'cancelled'
""")


def domains(urls: list[str]) -> tuple[str, ...]:
    out = set()
    for u in urls:
        host = (urlparse(u).hostname or "").lower().removeprefix("www.")
        if host:
            out.add(host)
    return tuple(sorted(out))


def build(row: Any, now: datetime) -> PresaleInputs:
    audits = tuple(str(a) for a in (row.audit_claims or []))
    return PresaleInputs(
        presale_id=row.id,
        as_of=now,
        status=row.status,
        sale_type=row.sale_type,
        verification_status=row.verification_status,
        official_website=row.official_website,
        platform=row.platform,
        team_info=row.team_info,
        vesting_terms=row.vesting_terms,
        lockup_terms=row.lockup_terms,
        audit_claims=audits,
        sale_price_usd=Decimal(str(row.sale_price_usd)) if row.sale_price_usd is not None else None,
        claimed_valuation_usd=Decimal(str(row.claimed_valuation_usd))
        if row.claimed_valuation_usd is not None
        else None,
        hard_cap_usd=Decimal(str(row.hard_cap_usd)) if row.hard_cap_usd is not None else None,
        sale_start_at=row.sale_start_at,
        sale_end_at=row.sale_end_at,
        source_domains=domains(list(row.source_urls or []) + list(row.claim_urls or [])),
        claims_total=row.claims_total,
        claims_contradicted=row.contradicted,
        updated_at=row.updated_at,
    )


async def score_presales(rt: ProviderRuntime) -> dict[str, Any]:
    now = datetime.now(UTC)
    stored = 0
    async with rt.engine.begin() as conn:
        rows = (await conn.execute(_ROWS)).all()
        for r in rows:
            res = score_presale(build(r, now))
            if res.inputs_hash == r.last_hash:
                continue
            await conn.execute(
                text("""
                insert into opportunity_scores (presale_id, scorecard, scoring_version, scored_at, data_cutoff_at,
                  total, components, missing_data, risk_flags, inputs_hash)
                values (:p, 'presale', :v, :now, :cut, :t, cast(:c as jsonb), :m, :f, :h)
            """),
                {
                    "p": r.id,
                    "v": res.scoring_version,
                    "now": now,
                    "cut": res.data_cutoff_at,
                    "t": res.total,
                    "c": json.dumps(res.components),
                    "m": res.missing_data,
                    "f": res.risk_flags,
                    "h": res.inputs_hash,
                },
            )
            stored += 1
        await runs.heartbeat(conn, "presale_scoring", "ok", f"{len(rows)} presales, {stored} rescored")
    return {"presales": len(rows), "stored": stored}
