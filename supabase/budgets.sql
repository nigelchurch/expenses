-- Budgets with history. Run once in Supabase > SQL Editor (safe to run again).
-- Each row: a category's monthly budget from `from_month` onwards (until a later row for that category).
-- Everyone signed in can read budgets; only nigel can add or change them.

create table if not exists public.budgets (
  id          bigint generated always as identity primary key,
  category    text          not null,
  amount      numeric(12,2) not null check (amount >= 0),
  from_month  date          not null check (extract(day from from_month) = 1),
  created_by  text,
  created_at  timestamptz   not null default now(),
  unique (category, from_month)
);

alter table public.budgets enable row level security;
grant select, insert, update, delete on public.budgets to authenticated;
revoke all on public.budgets from anon;

drop policy if exists "signed-in read budgets" on public.budgets;
drop policy if exists "nigel edits budgets"    on public.budgets;
create policy "signed-in read budgets" on public.budgets for select to authenticated using (true);
create policy "nigel edits budgets" on public.budgets for all to authenticated
  using      ((auth.jwt() ->> 'email') = 'nigel@expenses.local')
  with check ((auth.jwt() ->> 'email') = 'nigel@expenses.local');

-- Starting budgets (the ones the app had in config.js), applying from the start of the history
insert into public.budgets (category, amount, from_month, created_by) values
  ('Pocket Money (NIG)', 5000,     '2020-02-01', 'setup'),
  ('Pocket Money (JOP)', 5000,     '2020-02-01', 'setup'),
  ('Groceries (food)',   14000,    '2020-02-01', 'setup'),
  ('Eating Out',         5000,     '2020-02-01', 'setup'),
  ('Domestic',           22343,    '2020-02-01', 'setup'),
  ('Beer',               6000,     '2020-02-01', 'setup'),
  ('Car Expenses',       3000,     '2020-02-01', 'setup'),
  ('Cat expenses',       3000,     '2020-02-01', 'setup'),
  ('Health expenses',    3000,     '2020-02-01', 'setup'),
  ('Digital',            4032.33,  '2020-02-01', 'setup'),
  ('Travel and Holiday', 10000,    '2020-02-01', 'setup'),
  ('One-off expenses',   2000,     '2020-02-01', 'setup'),
  ('Quintara',           15271,    '2020-02-01', 'setup')
on conflict (category, from_month) do nothing;
