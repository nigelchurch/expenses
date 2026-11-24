-- Run in Supabase > SQL Editor > New query. Safe to run again (e.g. after an app update).

create table if not exists public.expenses (
  id          bigint generated always as identity primary key,
  month       date        not null check (extract(day from month) = 1), -- always the 1st of the month
  category    text        not null,
  amount      numeric(12,2) not null,
  comment     text        not null default '',
  created_by  text,
  created_at  timestamptz not null default now(),
  client_id   uuid unique  -- set by the app so a retried upload never creates duplicates
);
alter table public.expenses add column if not exists updated_at timestamptz;
alter table public.expenses add column if not exists kitty boolean; -- comes off / adds to Jop's kitty (null = jop's entries)

create index if not exists expenses_month_idx on public.expenses (month desc);

alter table public.expenses enable row level security;

-- Newer Supabase projects don't grant table access automatically: allow signed-in users only.
grant select, insert, update, delete on public.expenses to authenticated;
revoke all on public.expenses from anon;

-- Any signed-in user of the app can read, add, change and delete expenses. Nobody anonymous can.
drop policy if exists "signed-in read"   on public.expenses;
drop policy if exists "signed-in insert" on public.expenses;
drop policy if exists "signed-in update" on public.expenses;
drop policy if exists "signed-in delete" on public.expenses;
create policy "signed-in read"   on public.expenses for select to authenticated using (true);
create policy "signed-in insert" on public.expenses for insert to authenticated with check (true);
create policy "signed-in update" on public.expenses for update to authenticated using (true) with check (true);
create policy "signed-in delete" on public.expenses for delete to authenticated using (true);
