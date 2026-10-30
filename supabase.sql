-- Run this once in Supabase: Dashboard -> SQL Editor -> New query -> paste -> Run
create table if not exists users (
  id text primary key,
  data jsonb not null,            -- profile; password/passcode are scrypt hashes; Angel details are encrypted
  updated_at timestamptz default now()
);
create table if not exists trades (
  id text primary key,
  data jsonb not null,            -- includes "user" = owner's id
  updated_at timestamptz default now()
);
create table if not exists app_kv (
  key text primary key,           -- per-user settings use keys like "u:<user id>:watchlist"
  value jsonb,
  updated_at timestamptz default now()
);
-- Lock the tables: only the server (using the secret service_role key) can read/write.
alter table users enable row level security;
alter table trades enable row level security;
alter table app_kv enable row level security;
