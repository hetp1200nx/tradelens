-- =====================================================================================
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
  ('360ONE', 'Cap Mkts', false, false, true),
  ('3MINDIA', 'Cap Goods', false, false, false),
  ('AARTIDRUGS', 'Pharma', false, false, false),
  ('AARTIIND', 'Chemicals', false, false, true),
  ('ABB', 'Cap Goods', false, false, true),
  ('ABCAPITAL', 'NBFC', false, false, true),
  ('ABFRL', 'Consumer', false, false, false),
  ('ADANIENSOL', 'Power', false, false, true),
  ('ADANIENT', 'Diversified', true, false, true),
  ('ADANIGREEN', 'Power', false, false, true),
  ('ADANIPORTS', 'Infra', true, true, true),
  ('AJANTPHARM', 'Pharma', false, false, false),
  ('ALEMBICLTD', 'Pharma', false, false, false),
  ('ALKEM', 'Pharma', false, false, true),
  ('ALOKINDS', 'Other', false, false, false),
  ('AMBER', 'Consumer', false, false, true),
  ('AMBUJACEM', 'Cement', false, false, true),
  ('ANGELONE', 'Cap Mkts', false, false, true),
  ('APLAPOLLO', 'Metal', false, false, true),
  ('APLLTD', 'Pharma', false, false, false),
  ('APOLLOHOSP', 'Healthcare', true, false, true),
  ('ARVIND', 'Consumer', false, false, false),
  ('ASHOKLEY', 'Auto', false, false, true),
  ('ASIANPAINT', 'Consumer', true, true, true),
  ('ASTRAL', 'Cap Goods', false, false, true),
  ('ATGL', 'Oil & Gas', false, false, false),
  ('ATULAUTO', 'Auto', false, false, false),
  ('AUBANK', 'Bank', false, false, true),
  ('AUROPHARMA', 'Pharma', false, false, true),
  ('AXISBANK', 'Bank', true, true, true),
  ('BAJAJ-AUTO', 'Auto', true, false, true),
  ('BAJAJFINSV', 'NBFC', true, true, true),
  ('BAJAJHLDNG', 'NBFC', false, false, true),
  ('BAJFINANCE', 'NBFC', true, true, true),
  ('BANDHANBNK', 'Bank', false, false, true),
  ('BANKBARODA', 'PSU Bank', false, false, true),
  ('BANKINDIA', 'PSU Bank', false, false, true),
  ('BATAINDIA', 'Consumer', false, false, false),
  ('BDL', 'Defence', false, false, true),
  ('BEL', 'Defence', true, true, true),
  ('BEML', 'Defence', false, false, false),
  ('BHARATFORG', 'Auto', false, false, true),
  ('BHARTIARTL', 'Telecom', true, true, true),
  ('BHEL', 'Cap Goods', false, false, true),
  ('BIOCON', 'Pharma', false, false, true),
  ('BLUESTARCO', 'Consumer', false, false, true),
  ('BOSCHLTD', 'Auto', false, false, true),
  ('BPCL', 'Oil & Gas', false, false, true),
  ('BRITANNIA', 'FMCG', false, false, true),
  ('BSE', 'Cap Mkts', false, false, true),
  ('BSOFT', 'IT', false, false, false),
  ('CAMPUS', 'Consumer', false, false, false),
  ('CAMS', 'Cap Mkts', false, false, true),
  ('CANBK', 'PSU Bank', false, false, true),
  ('CAPLIPOINT', 'Pharma', false, false, false),
  ('CARBORUNIV', 'Cap Goods', false, false, false),
  ('CASTROLIND', 'Oil & Gas', false, false, false),
  ('CDSL', 'Cap Mkts', false, false, true),
  ('CENTRALBK', 'PSU Bank', false, false, false),
  ('CESC', 'Power', false, false, true),
  ('CGPOWER', 'Cap Goods', false, false, true),
  ('CHAMBLFERT', 'Chemicals', false, false, false),
  ('CHENNPETRO', 'Oil & Gas', false, false, false),
  ('CHOLAFIN', 'NBFC', false, false, true),
  ('CIPLA', 'Pharma', true, false, true),
  ('COALINDIA', 'Metal', true, false, true),
  ('COCHINSHIP', 'Defence', false, false, false),
  ('COFORGE', 'IT', false, false, true),
  ('COLPAL', 'FMCG', false, false, true),
  ('CONCOR', 'Infra', false, false, true),
  ('COROMANDEL', 'Chemicals', false, false, false),
  ('CROMPTON', 'Consumer', false, false, true),
  ('CUMMINSIND', 'Cap Goods', false, false, true),
  ('CYIENT', 'IT', false, false, true),
  ('DABUR', 'FMCG', false, false, true),
  ('DALBHARAT', 'Cement', false, false, true),
  ('DEEPAKFERT', 'Chemicals', false, false, false),
  ('DEEPAKNTR', 'Chemicals', false, false, false),
  ('DELHIVERY', 'Infra', false, false, true),
  ('DIVISLAB', 'Pharma', false, false, true),
  ('DIXON', 'Consumer', false, false, true),
  ('DLF', 'Realty', false, false, true),
  ('DMART', 'Consumer', false, false, true),
  ('DRREDDY', 'Pharma', true, false, true),
  ('EICHERMOT', 'Auto', true, false, true),
  ('ELGIEQUIP', 'Cap Goods', false, false, false),
  ('ENGINERSIN', 'Infra', false, false, false),
  ('EQUITASBNK', 'Bank', false, false, false),
  ('ERIS', 'Pharma', false, false, false),
  ('ESCORTS', 'Auto', false, false, false),
  ('ETERNAL', 'Consumer', true, true, true),
  ('EXIDEIND', 'Auto', false, false, true),
  ('FACT', 'Chemicals', false, false, false),
  ('FEDERALBNK', 'Bank', false, false, true),
  ('FORCEMOT', 'Auto', false, false, false),
  ('GAIL', 'Oil & Gas', false, false, true),
  ('GLENMARK', 'Pharma', false, false, true),
  ('GMRAIRPORT', 'Infra', false, false, true),
  ('GNFC', 'Chemicals', false, false, false),
  ('GODREJCP', 'FMCG', false, false, true),
  ('GODREJPROP', 'Realty', false, false, true),
  ('GRANULES', 'Pharma', false, false, false),
  ('GRASIM', 'Cement', true, false, true),
  ('GREAVESCOT', 'Auto', false, false, false),
  ('GRINDWELL', 'Cap Goods', false, false, false),
  ('GRSE', 'Defence', false, false, false),
  ('GSFC', 'Chemicals', false, false, false),
  ('GSPL', 'Oil & Gas', false, false, false),
  ('GTLINFRA', 'Telecom', false, false, false),
  ('GUJGASLTD', 'Oil & Gas', false, false, false),
  ('GULFOILLUB', 'Oil & Gas', false, false, false),
  ('HAL', 'Defence', false, false, true),
  ('HAPPSTMNDS', 'IT', false, false, false),
  ('HAVELLS', 'Consumer', false, false, true),
  ('HBLENGINE', 'Cap Goods', false, false, false),
  ('HCLTECH', 'IT', true, true, true),
  ('HDFCAMC', 'Cap Mkts', false, false, true),
  ('HDFCBANK', 'Bank', true, true, true),
  ('HDFCLIFE', 'Insurance', true, false, true),
  ('HEROMOTOCO', 'Auto', false, false, true),
  ('HFCL', 'Telecom', false, false, true),
  ('HINDALCO', 'Metal', true, false, true),
  ('HINDCOPPER', 'Metal', false, false, true),
  ('HINDPETRO', 'Oil & Gas', false, false, true),
  ('HINDUNILVR', 'FMCG', true, true, true),
  ('HINDZINC', 'Metal', false, false, true),
  ('HONAUT', 'Cap Goods', false, false, false),
  ('HSCL', 'Infra', false, false, false),
  ('HUDCO', 'NBFC', false, false, true),
  ('ICICIBANK', 'Bank', true, true, true),
  ('ICICIGI', 'Insurance', false, false, true),
  ('ICICIPRULI', 'Insurance', false, false, true),
  ('IDBI', 'Bank', false, false, false),
  ('IDEA', 'Telecom', false, false, true),
  ('IDFCFIRSTB', 'Bank', false, false, true),
  ('IEX', 'Cap Mkts', false, false, true),
  ('IGL', 'Oil & Gas', false, false, true),
  ('IIFL', 'NBFC', false, false, true),
  ('INDHOTEL', 'Consumer', false, false, true),
  ('INDIANB', 'PSU Bank', false, false, true),
  ('INDIGO', 'Aviation', true, false, true),
  ('INDUSINDBK', 'Bank', false, false, true),
  ('INDUSTOWER', 'Telecom', false, false, true),
  ('INFY', 'IT', true, true, true),
  ('INOXWIND', 'Power', false, false, true),
  ('INTELLECT', 'IT', false, false, false),
  ('IOB', 'PSU Bank', false, false, false),
  ('IOC', 'Oil & Gas', false, false, true),
  ('IPCALAB', 'Pharma', false, false, false),
  ('IRB', 'Infra', false, false, false),
  ('IRCON', 'Infra', false, false, false),
  ('IRCTC', 'Consumer', false, false, true),
  ('IREDA', 'NBFC', false, false, true),
  ('IRFC', 'NBFC', false, false, true),
  ('ITC', 'FMCG', true, true, true),
  ('J&KBANK', 'Bank', false, false, false),
  ('JBCHEPHARM', 'Pharma', false, false, false),
  ('JBMA', 'Auto', false, false, false),
  ('JINDALSTEL', 'Metal', false, false, true),
  ('JIOFIN', 'NBFC', true, false, true),
  ('JPPOWER', 'Power', false, false, false),
  ('JSWENERGY', 'Power', false, false, true),
  ('JSWINFRA', 'Infra', false, false, true),
  ('JSWSTEEL', 'Metal', true, false, true),
  ('JUBLFOOD', 'Consumer', false, false, true),
  ('JWL', 'Infra', false, false, false),
  ('KALYANKJIL', 'Consumer', false, false, true),
  ('KARURVYSYA', 'Bank', false, false, false),
  ('KAYNES', 'Cap Goods', false, false, true),
  ('KEI', 'Cap Goods', false, false, true),
  ('KFINTECH', 'Cap Mkts', false, false, true),
  ('KIRLOSENG', 'Cap Goods', false, false, false),
  ('KOTAKBANK', 'Bank', true, true, true),
  ('KPIGREEN', 'Power', false, false, false),
  ('KPITTECH', 'IT', false, false, true),
  ('KPRMILL', 'Consumer', false, false, false),
  ('KSB', 'Cap Goods', false, false, false),
  ('LAURUSLABS', 'Pharma', false, false, true),
  ('LICHSGFIN', 'NBFC', false, false, true),
  ('LICI', 'Insurance', false, false, true),
  ('LODHA', 'Realty', false, false, true),
  ('LT', 'Cap Goods', true, true, true),
  ('LTF', 'NBFC', false, false, true),
  ('LTIM', 'IT', false, false, true),
  ('LTTS', 'IT', false, false, true),
  ('LUPIN', 'Pharma', false, false, true),
  ('M&M', 'Auto', true, true, true),
  ('MAHABANK', 'PSU Bank', false, false, false),
  ('MANAPPURAM', 'NBFC', false, false, true),
  ('MANKIND', 'Pharma', false, false, true),
  ('MARICO', 'FMCG', false, false, true),
  ('MARKSANS', 'Pharma', false, false, false),
  ('MARUTI', 'Auto', true, true, true),
  ('MASTEK', 'IT', false, false, false),
  ('MAXHEALTH', 'Healthcare', true, false, true),
  ('MAZDOCK', 'Defence', false, false, true),
  ('MCX', 'Cap Mkts', false, false, true),
  ('METROBRAND', 'Consumer', false, false, false),
  ('MFSL', 'Insurance', false, false, true),
  ('MGL', 'Oil & Gas', false, false, true),
  ('MOTHERSON', 'Auto', false, false, true),
  ('MPHASIS', 'IT', false, false, true),
  ('MRPL', 'Oil & Gas', false, false, false),
  ('MUTHOOTFIN', 'NBFC', false, false, true),
  ('NATCOPHARM', 'Pharma', false, false, false),
  ('NATIONALUM', 'Metal', false, false, true),
  ('NAUKRI', 'Internet', false, false, true),
  ('NBCC', 'Infra', false, false, true),
  ('NCC', 'Infra', false, false, true),
  ('NESTLEIND', 'FMCG', true, false, true),
  ('NETWORK18', 'Media', false, false, false),
  ('NEULANDLAB', 'Pharma', false, false, false),
  ('NEWGEN', 'IT', false, false, false),
  ('NFL', 'Chemicals', false, false, false),
  ('NHPC', 'Power', false, false, true),
  ('NLCINDIA', 'Power', false, false, false),
  ('NMDC', 'Metal', false, false, true),
  ('NTPC', 'Power', true, true, true),
  ('NUVAMA', 'Cap Mkts', false, false, true),
  ('NYKAA', 'Consumer', false, false, true),
  ('OBEROIRLTY', 'Realty', false, false, true),
  ('OFSS', 'IT', false, false, true),
  ('OIL', 'Oil & Gas', false, false, true),
  ('OLECTRA', 'Auto', false, false, false),
  ('ONGC', 'Oil & Gas', true, false, true),
  ('PAGEIND', 'Consumer', false, false, true),
  ('PATANJALI', 'FMCG', false, false, true),
  ('PAYTM', 'Internet', false, false, true),
  ('PERSISTENT', 'IT', false, false, true),
  ('PETRONET', 'Oil & Gas', false, false, true),
  ('PFC', 'NBFC', false, false, true),
  ('PGEL', 'Cap Goods', false, false, true),
  ('PHOENIXLTD', 'Realty', false, false, true),
  ('PIDILITIND', 'Consumer', false, false, true),
  ('PIIND', 'Chemicals', false, false, true),
  ('PNB', 'PSU Bank', false, false, true),
  ('PNBHOUSING', 'NBFC', false, false, true),
  ('POLICYBZR', 'Insurance', false, false, true),
  ('POLYCAB', 'Cap Goods', false, false, true),
  ('POWERGRID', 'Power', true, true, true),
  ('POWERINDIA', 'Cap Goods', false, false, true),
  ('PPLPHARMA', 'Pharma', false, false, true),
  ('PREMIERENE', 'Power', false, false, true),
  ('PRESTIGE', 'Realty', false, false, true),
  ('RAILTEL', 'Infra', false, false, false),
  ('RAYMOND', 'Consumer', false, false, false),
  ('RBLBANK', 'Bank', false, false, true),
  ('RCF', 'Chemicals', false, false, false),
  ('RECLTD', 'NBFC', false, false, true),
  ('RELAXO', 'Consumer', false, false, false),
  ('RELIANCE', 'Oil & Gas', true, true, true),
  ('RITES', 'Infra', false, false, false),
  ('ROUTE', 'IT', false, false, false),
  ('RPOWER', 'Power', false, false, false),
  ('RTNINDIA', 'Other', false, false, false),
  ('RVNL', 'Infra', false, false, true),
  ('SAIL', 'Metal', false, false, true),
  ('SAMMAANCAP', 'NBFC', false, false, true),
  ('SBICARD', 'NBFC', false, false, true),
  ('SBILIFE', 'Insurance', true, false, true),
  ('SBIN', 'PSU Bank', true, true, true),
  ('SCHAEFFLER', 'Cap Goods', false, false, false),
  ('SHOPERSTOP', 'Consumer', false, false, false),
  ('SHREECEM', 'Cement', false, false, true),
  ('SHRIRAMFIN', 'NBFC', true, false, true),
  ('SIEMENS', 'Cap Goods', false, false, true),
  ('SJVN', 'Power', false, false, false),
  ('SKFINDIA', 'Cap Goods', false, false, false),
  ('SMLISUZU', 'Auto', false, false, false),
  ('SOLARA', 'Pharma', false, false, false),
  ('SOLARINDS', 'Defence', false, false, true),
  ('SONACOMS', 'Auto', false, false, true),
  ('SONATSOFTW', 'IT', false, false, false),
  ('SOUTHBANK', 'Bank', false, false, false),
  ('SPARC', 'Pharma', false, false, false),
  ('SRF', 'Chemicals', false, false, true),
  ('SUNPHARMA', 'Pharma', true, true, true),
  ('SUPREMEIND', 'Cap Goods', false, false, true),
  ('SUVENPHAR', 'Pharma', false, false, false),
  ('SUZLON', 'Power', false, false, true),
  ('SWIGGY', 'Consumer', false, false, true),
  ('SYNGENE', 'Pharma', false, false, true),
  ('TANLA', 'IT', false, false, false),
  ('TATACHEM', 'Chemicals', false, false, true),
  ('TATACONSUM', 'FMCG', true, false, true),
  ('TATAELXSI', 'IT', false, false, true),
  ('TATAPOWER', 'Power', false, false, true),
  ('TATASTEEL', 'Metal', true, true, true),
  ('TATATECH', 'IT', false, false, true),
  ('TCS', 'IT', true, true, true),
  ('TECHM', 'IT', true, true, true),
  ('TEXRAIL', 'Infra', false, false, false),
  ('THERMAX', 'Cap Goods', false, false, false),
  ('TIINDIA', 'Auto', false, false, true),
  ('TIMKEN', 'Cap Goods', false, false, false),
  ('TITAGARH', 'Infra', false, false, true),
  ('TITAN', 'Consumer', true, true, true),
  ('TMCV', 'Auto', false, false, true),
  ('TMPV', 'Auto', true, true, true),
  ('TORNTPHARM', 'Pharma', false, false, true),
  ('TORNTPOWER', 'Power', false, false, true),
  ('TRENT', 'Consumer', true, true, true),
  ('TRIDENT', 'Consumer', false, false, false),
  ('TRIVENI', 'Cap Goods', false, false, false),
  ('TV18BRDCST', 'Media', false, false, false),
  ('TVSMOTOR', 'Auto', false, false, true),
  ('UCOBANK', 'PSU Bank', false, false, false),
  ('UJJIVANSFB', 'Bank', false, false, false),
  ('ULTRACEMCO', 'Cement', true, true, true),
  ('UNIONBANK', 'PSU Bank', false, false, true),
  ('UNITDSPR', 'FMCG', false, false, true),
  ('UNOMINDA', 'Auto', false, false, true),
  ('UPL', 'Chemicals', false, false, true),
  ('VBL', 'FMCG', false, false, true),
  ('VEDL', 'Metal', false, false, true),
  ('VMART', 'Consumer', false, false, false),
  ('VOLTAS', 'Consumer', false, false, true),
  ('VTL', 'Consumer', false, false, false),
  ('WAAREEENER', 'Power', false, false, true),
  ('WELSPUNLIV', 'Consumer', false, false, false),
  ('WIPRO', 'IT', true, false, true),
  ('WOCKPHARMA', 'Pharma', false, false, false),
  ('YESBANK', 'Bank', false, false, true),
  ('ZENSARTECH', 'IT', false, false, false),
  ('ZENTEC', 'Defence', false, false, false),
  ('ZYDUSLIFE', 'Pharma', false, false, true)
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
