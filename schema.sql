-- AI with AI — CEAL Platform Schema
-- Paste into Supabase SQL Editor and Run

create table if not exists users (
  id uuid default gen_random_uuid() primary key,
  name text not null,
  email text unique not null,
  tier text not null check (tier in ('foundation','professional','full')),
  token text unique not null,
  created_at timestamptz default now()
);

create table if not exists progress (
  id uuid default gen_random_uuid() primary key,
  user_id uuid references users(id) on delete cascade unique,
  data jsonb default '{}'::jsonb,
  scores jsonb default '{}'::jsonb,
  decisions jsonb default '{}'::jsonb,
  ghost_missed boolean default false,
  updated_at timestamptz default now()
);

create index if not exists users_email_idx on users(email);
create index if not exists users_token_idx on users(token);
create index if not exists progress_user_idx on progress(user_id);

create or replace function update_updated_at()
returns trigger as $$
begin new.updated_at = now(); return new; end;
$$ language plpgsql;

drop trigger if exists progress_updated_at on progress;
create trigger progress_updated_at
  before update on progress
  for each row execute function update_updated_at();

alter table users disable row level security;
alter table progress disable row level security;
