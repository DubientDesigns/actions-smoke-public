-- Phase 5: alert delivery bookkeeping, research report read model, defaults.

alter table alerts add column if not exists digest_sent_at timestamptz;
create index if not exists alerts_dedup_created_idx on alerts (dedup_key, created_at desc);

create view v_research_reports with (security_invoker = true) as
select r.id, r.token_id, r.presale_id, c.slug as chain, t.address, t.symbol, t.name, r.status, r.prompt_version,
       r.model, r.research_priority, r.input_tokens, r.output_tokens, r.cost_usd, r.error, r.created_at,
       r.completed_at
from research_reports r
left join tokens t on t.id = r.token_id
left join chains c on c.id = t.chain_id;

create view v_spend_month with (security_invoker = true) as
select s.slug as source, date_trunc('month', u.occurred_at) as month,
       count(*) as calls, coalesce(sum(u.input_tokens), 0) as input_tokens,
       coalesce(sum(u.output_tokens), 0) as output_tokens, coalesce(sum(u.cost_usd), 0) as cost_usd
from api_usage u join data_sources s on s.id = u.source_id
where u.occurred_at >= date_trunc('month', now()) - interval '2 months'
group by s.slug, date_trunc('month', u.occurred_at);

grant select on v_research_reports, v_spend_month to authenticated;
revoke all on v_research_reports, v_spend_month from anon;

-- Operator-approved defaults (2026-10-13): AI and alert delivery on, still gated
-- by API keys and source switches; batch API not used.
update app_settings set value = (value - 'use_batch_api') || '{"enabled": true}'::jsonb where key = 'ai.budget';
update app_settings set value = value || '{"enabled": true}'::jsonb where key = 'alerts';
