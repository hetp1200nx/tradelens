"""Generates supabase.sql: every table TradeLens uses, security, readable views, and starting data.
Run from the tradelens folder:  python tools/make_supabase_sql.py
"""
import hashlib
import json
import os
import secrets
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from backend.universe import DEMO_EXTRA_FNO, DEMO_MORE, NIFTY50, SECTOR_OF, SENSEX30  # noqa: E402




def scrypt_hash(pw: str) -> str:
    """Same format as backend/users.py hash_secret()."""
    salt = secrets.token_bytes(16)
    h = hashlib.scrypt(pw.encode(), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)
    return f"scrypt${salt.hex()}${h.hex()}"


def q(s: str) -> str:
    return "'" + str(s).replace("'", "''") + "'"



stocks = sorted(set(NIFTY50) | set(SENSEX30) | set(DEMO_EXTRA_FNO) | set(DEMO_MORE))
fno = set(NIFTY50) | set(SENSEX30) | set(DEMO_EXTRA_FNO)
rows = ",\n".join(
    f"  ({q(s)}, {q(SECTOR_OF.get(s, 'Other'))}, {str(s in NIFTY50).lower()}, {str(s in SENSEX30).lower()}, {str(s in fno).lower()})"
    for s in stocks)

sql = f"""-- =====================================================================================
--  TradeLens database for Supabase
--  How to use: Supabase dashboard -> SQL Editor -> New query -> paste ALL of this -> Run.
--  Safe to run again: it never deletes or overwrites your users, trades or watchlists.
-- =====================================================================================


-- -------------------------------------------------------------------------------------
-- 1. TABLES THE APP USES
--    TradeLens stores each record as JSON in "data", so new app features never need
--    a database change. Readable column views are created in section 5.
-- -------------------------------------------------------------------------------------

-- Accounts. Passwords and passcodes are one-way scrypt hashes (nobody can read them).
-- Angel One API key, PIN and TOTP secret are encrypted by the app with SECRET_KEY from .env.
create table if not exists public.users (
  id          text primary key,
  data        jsonb not null,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);

-- Trades each user logs in "My Trades". data->>'user' is the owner's user id.
create table if not exists public.trades (
  id          text primary key,
  data        jsonb not null,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);

-- Settings and lists. Global keys: "data_user" (whose API powers live prices), "scorecard".
-- Per-user keys: "u:<user id>:watchlist", "u:<user id>:price_alerts", "u:<user id>:settings".
create table if not exists public.app_kv (
  key         text primary key,
  value       jsonb,
  updated_at  timestamptz not null default now()
);


-- -------------------------------------------------------------------------------------
-- 2. INDEXES (fast lookups as data grows)
-- -------------------------------------------------------------------------------------
create unique index if not exists users_username_lower_idx on public.users (lower(data->>'username'));
create index if not exists trades_user_idx    on public.trades ((data->>'user'));
create index if not exists trades_status_idx  on public.trades ((data->>'status'));
create index if not exists trades_symbol_idx  on public.trades ((data->>'symbol'));
create index if not exists app_kv_prefix_idx  on public.app_kv (key text_pattern_ops);


-- -------------------------------------------------------------------------------------
-- 3. KEEP updated_at CURRENT AUTOMATICALLY
-- -------------------------------------------------------------------------------------
create or replace function public.tl_touch_updated_at() returns trigger
language plpgsql set search_path = '' as $$
begin
  new.updated_at := now();
  return new;
end $$;

drop trigger if exists users_touch  on public.users;
drop trigger if exists trades_touch on public.trades;
drop trigger if exists app_kv_touch on public.app_kv;
create trigger users_touch  before update on public.users  for each row execute function public.tl_touch_updated_at();
create trigger trades_touch before update on public.trades for each row execute function public.tl_touch_updated_at();
create trigger app_kv_touch before update on public.app_kv for each row execute function public.tl_touch_updated_at();


-- -------------------------------------------------------------------------------------
-- 4. REFERENCE DATA: shares with sector and index membership
--    For browsing and reports in Supabase. (The app keeps its own copy, so editing this
--    table does not change the app; tell me if you want the app to read it.)
-- -------------------------------------------------------------------------------------
create table if not exists public.stocks (
  symbol     text primary key,
  sector     text not null default 'Other',
  nifty50    boolean not null default false,
  sensex     boolean not null default false,
  fno        boolean not null default false
);

insert into public.stocks (symbol, sector, nifty50, sensex, fno) values
{rows}
on conflict (symbol) do update
  set sector = excluded.sector, nifty50 = excluded.nifty50, sensex = excluded.sensex, fno = excluded.fno;


-- -------------------------------------------------------------------------------------
-- 5. READABLE VIEWS (open them in Table Editor; they never show password hashes or secrets)
-- -------------------------------------------------------------------------------------
create or replace function public.tl_num(t text) returns numeric
language plpgsql immutable set search_path = '' as $$
begin
  return nullif(trim(t), '')::numeric;
exception when others then
  return null;
end $$;

create or replace function public.tl_ist(epoch text) returns timestamp
language sql immutable set search_path = '' as $$
  select case when public.tl_num(epoch) is null then null
              else (to_timestamp(public.tl_num(epoch)::double precision) at time zone 'Asia/Kolkata') end
$$;

-- Users: profile, Angel API status (no secrets), counts
create or replace view public.v_users with (security_invoker = true) as
select
  u.id,
  u.data->>'role'                                   as role,
  u.data->>'first_name'                             as first_name,
  u.data->>'last_name'                              as last_name,
  u.data->>'username'                               as username,
  u.data->>'email'                                  as email,
  u.data->>'phone'                                  as mobile,
  (u.data->'angel') is not null                     as angel_api_added,
  u.data->'angel'->>'client_code'                   as angel_client_id,
  coalesce(u.data->'angel'->>'status', 'not added') as angel_status,
  coalesce((u.data->>'disabled')::boolean, false)   as disabled,
  public.tl_ist(u.data->>'created')                 as joined_ist,
  public.tl_ist(u.data->>'last_login')              as last_login_ist,
  (select count(*) from public.trades t where t.data->>'user' = u.id)                                 as trades_total,
  (select count(*) from public.trades t where t.data->>'user' = u.id and t.data->>'status' = 'open')  as trades_open,
  coalesce(jsonb_array_length(k.value), 0)          as watchlist_count
from public.users u
left join public.app_kv k
  on k.key = 'u:' || u.id || ':watchlist' and jsonb_typeof(k.value) = 'array';

-- Trades: one row per trade with owner, prices and gross P&L for closed trades (before charges)
create or replace view public.v_trades with (security_invoker = true) as
select
  t.id,
  u.data->>'username'                         as username,
  t.data->>'symbol'                           as symbol,
  t.data->>'side'                             as side,
  t.data->>'segment'                          as trade_type,
  public.tl_num(t.data->>'opt_strike')        as strike,
  nullif(t.data->>'opt_type', '')             as ce_pe,
  public.tl_num(t.data->>'qty')               as qty,
  public.tl_num(t.data->>'entry')             as entry,
  public.tl_num(t.data->>'sl')                as stop_loss,
  public.tl_num(t.data->>'t1')                as target1,
  public.tl_num(t.data->>'t2')                as target2,
  t.data->>'status'                           as status,
  public.tl_num(t.data->>'exit_price')        as exit_price,
  case when t.data->>'status' = 'closed' then
    round((public.tl_num(t.data->>'exit_price') - public.tl_num(t.data->>'entry'))
          * public.tl_num(t.data->>'qty') * case when t.data->>'side' = 'SELL' then -1 else 1 end, 2)
  end                                         as gross_pnl_closed,
  t.data->>'notes'                            as notes,
  public.tl_ist(t.data->>'created_at')        as opened_ist,
  public.tl_ist(t.data->>'exit_time')         as closed_ist
from public.trades t
left join public.users u on u.id = t.data->>'user';

-- Watchlists: one row per user per share
create or replace view public.v_watchlists with (security_invoker = true) as
select
  u.data->>'username'  as username,
  w.ord                as position,
  w.symbol,
  s.sector
from public.app_kv k
join public.users u on k.key = 'u:' || u.id || ':watchlist'
cross join lateral jsonb_array_elements_text(case when jsonb_typeof(k.value) = 'array' then k.value else '[]'::jsonb end)
  with ordinality as w(symbol, ord)
left join public.stocks s on s.symbol = w.symbol;

-- Price alerts
create or replace view public.v_price_alerts with (security_invoker = true) as
select
  u.data->>'username'                  as username,
  a->>'sym'                            as symbol,
  a->>'op'                             as condition,
  public.tl_num(a->>'price')           as price,
  coalesce((a->>'done')::boolean, false) as triggered,
  a->>'note'                           as note,
  public.tl_ist(a->>'created')         as created_ist
from public.app_kv k
join public.users u on k.key = 'u:' || u.id || ':price_alerts'
cross join lateral jsonb_array_elements(case when jsonb_typeof(k.value) = 'array' then k.value else '[]'::jsonb end) as a;


-- -------------------------------------------------------------------------------------
-- 6. SECURITY
--    Row Level Security ON with no policies = the public API keys (anon / authenticated)
--    can read nothing. Only your server, using the SECRET key, can read and write.
-- -------------------------------------------------------------------------------------
alter table public.users  enable row level security;
alter table public.trades enable row level security;
alter table public.app_kv enable row level security;
alter table public.stocks enable row level security;

revoke all on public.users, public.trades, public.app_kv, public.stocks from anon, authenticated;
revoke all on public.v_users, public.v_trades, public.v_watchlists, public.v_price_alerts from anon, authenticated;
revoke execute on function public.tl_num(text), public.tl_ist(text), public.tl_touch_updated_at() from anon, authenticated, public;

grant all on public.users, public.trades, public.app_kv, public.stocks to service_role;
grant select on public.v_users, public.v_trades, public.v_watchlists, public.v_price_alerts to service_role;
grant execute on function public.tl_num(text), public.tl_ist(text) to service_role;


-- -------------------------------------------------------------------------------------
-- 7. STARTING DATA
-- -------------------------------------------------------------------------------------

-- Admin account: not created here on purpose (this file may be public on GitHub).
-- TradeLens creates it automatically on first start from ADMIN_USERNAME / ADMIN_PASSWORD in your .env.

-- Global settings
insert into public.app_kv (key, value) values
  ('scorecard', '[]'::jsonb),
  ('data_user', 'null'::jsonb)
on conflict (key) do nothing;


-- -------------------------------------------------------------------------------------
-- 8. CHECK: the result grid should show one row per table with its row count
-- -------------------------------------------------------------------------------------
select 'users' as table_name, count(*) as rows from public.users
union all select 'trades', count(*) from public.trades
union all select 'app_kv', count(*) from public.app_kv
union all select 'stocks', count(*) from public.stocks;
"""

out = os.path.join(os.path.dirname(__file__), "..", "supabase.sql")
with open(out, "w") as f:
    f.write(sql)
print(f"wrote supabase.sql ({len(stocks)} stocks; admin is created by the app from .env)")
