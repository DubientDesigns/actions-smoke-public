-- Row-level security.
--
-- Model: a single private deployment. The browser uses the Supabase anon key +
-- the signed-in user's JWT, so every browser query runs as role
-- `authenticated` and is filtered by these policies. Only users present in
-- app_users can read anything. Workers use a privileged database connection
-- (table owner / service_role) which bypasses RLS and is never sent to the
-- browser.

create or replace function public.is_app_user() returns boolean
language sql stable security definer set search_path = public as $$
  select exists (select 1 from app_users where user_id = auth.uid())
$$;

create or replace function public.is_app_owner() returns boolean
language sql stable security definer set search_path = public as $$
  select exists (select 1 from app_users where user_id = auth.uid() and role = 'owner')
$$;

revoke all on function public.is_app_user() from public;
revoke all on function public.is_app_owner() from public;
grant execute on function public.is_app_user() to authenticated;
grant execute on function public.is_app_owner() to authenticated;

-- Enable RLS everywhere; anon gets nothing.
do $$
declare
  t text;
begin
  for t in
    select tablename from pg_tables where schemaname = 'public'
  loop
    execute format('alter table public.%I enable row level security', t);
    execute format('revoke all on public.%I from anon', t);
  end loop;
end
$$;

-- Read-only research tables: any allowlisted user may read; only workers write.
do $$
declare
  t text;
begin
  foreach t in array array[
    'chains', 'data_sources', 'ingestion_runs', 'tokens', 'pools', 'market_snapshots',
    'pool_latest', 'security_assessments', 'presale_claims', 'influencers', 'social_channels',
    'social_mentions', 'mention_outcomes', 'wallet_events', 'opportunity_scores',
    'research_reports', 'alerts', 'strategy_definitions', 'strategy_evaluations',
    'api_usage', 'system_health', 'app_settings', 'paper_equity_marks'
  ]
  loop
    execute format('grant select on public.%I to authenticated', t);
    execute format(
      'create policy %I on public.%I for select to authenticated using (public.is_app_user())',
      t || '_read', t);
  end loop;
end
$$;

grant select on public.api_usage_daily to authenticated;
alter view public.api_usage_daily set (security_invoker = true);

-- Users can see their own allowlist row only.
grant select on public.app_users to authenticated;
create policy app_users_self on public.app_users for select to authenticated
  using (user_id = auth.uid());

-- Audit log: owners only.
grant select on public.audit_log to authenticated;
create policy audit_log_owner_read on public.audit_log for select to authenticated
  using (public.is_app_owner());

-- Operator-curated tables: allowlisted users read, owners write.
do $$
declare
  t text;
begin
  foreach t in array array['presales', 'tracked_wallets']
  loop
    execute format('grant select, insert, update, delete on public.%I to authenticated', t);
    execute format(
      'create policy %I on public.%I for select to authenticated using (public.is_app_user())',
      t || '_read', t);
    execute format(
      'create policy %I on public.%I for all to authenticated using (public.is_app_owner()) with check (public.is_app_owner())',
      t || '_owner_write', t);
  end loop;
end
$$;

-- Per-user tables.
grant select, insert, update, delete on public.watchlists, public.saved_views to authenticated;
create policy watchlists_own on public.watchlists for all to authenticated
  using (owner_id = auth.uid() and public.is_app_user())
  with check (owner_id = auth.uid() and public.is_app_user());
create policy saved_views_own on public.saved_views for all to authenticated
  using (owner_id = auth.uid() and public.is_app_user())
  with check (owner_id = auth.uid() and public.is_app_user());

grant select, insert, update, delete on public.watchlist_items to authenticated;
create policy watchlist_items_own on public.watchlist_items for all to authenticated
  using (exists (select 1 from public.watchlists w where w.id = watchlist_id and w.owner_id = auth.uid()))
  with check (exists (select 1 from public.watchlists w where w.id = watchlist_id and w.owner_id = auth.uid()));

-- Paper trading: readable by app users (system strategy portfolios have NULL
-- owner). Manual orders are created through the backend so execution-delay
-- and look-ahead rules are always applied; the browser cannot insert fills.
grant select on public.paper_portfolios, public.paper_positions, public.paper_orders, public.paper_fills to authenticated;
create policy paper_portfolios_read on public.paper_portfolios for select to authenticated
  using (public.is_app_user() and (owner_id is null or owner_id = auth.uid()));
create policy paper_positions_read on public.paper_positions for select to authenticated
  using (exists (select 1 from public.paper_portfolios p where p.id = portfolio_id
                 and public.is_app_user() and (p.owner_id is null or p.owner_id = auth.uid())));
create policy paper_orders_read on public.paper_orders for select to authenticated
  using (exists (select 1 from public.paper_portfolios p where p.id = portfolio_id
                 and public.is_app_user() and (p.owner_id is null or p.owner_id = auth.uid())));
create policy paper_fills_read on public.paper_fills for select to authenticated
  using (exists (select 1 from public.paper_orders o join public.paper_portfolios p on p.id = o.portfolio_id
                 where o.id = order_id and public.is_app_user() and (p.owner_id is null or p.owner_id = auth.uid())));
