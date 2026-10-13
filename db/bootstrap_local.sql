-- Local/dev/test ONLY. Never run against Supabase.
--
-- Creates the minimal subset of Supabase objects that our migrations reference
-- (auth schema, auth.uid(), and the anon/authenticated/service_role roles) so
-- the exact same migration files can be applied to a plain PostgreSQL 15+/16
-- instance in CI and local development.
--
-- Every statement is guarded so it is a no-op when the object already exists.

do $$
begin
  if not exists (select 1 from pg_roles where rolname = 'anon') then
    create role anon nologin;
  end if;
  if not exists (select 1 from pg_roles where rolname = 'authenticated') then
    create role authenticated nologin;
  end if;
  if not exists (select 1 from pg_roles where rolname = 'service_role') then
    create role service_role nologin bypassrls;
  end if;
end
$$;

create schema if not exists auth;

create table if not exists auth.users (
  id uuid primary key,
  email text
);

do $$
begin
  if not exists (
    select 1 from pg_proc p join pg_namespace n on n.oid = p.pronamespace
    where n.nspname = 'auth' and p.proname = 'uid'
  ) then
    -- Mirrors Supabase: reads the JWT "sub" claim from a request GUC.
    execute $f$
      create function auth.uid() returns uuid
      language sql stable
      as $body$
        select nullif(
          coalesce(
            current_setting('request.jwt.claim.sub', true),
            (nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'sub')
          ),
          ''
        )::uuid
      $body$
    $f$;
  end if;
end
$$;
