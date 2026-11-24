-- Jop's kitty (the cash float she holds). Run once in Supabase > SQL Editor (safe to run again).
-- Balance = latest 'opening' amount + transfers since then - (everything jop has entered since then).
-- Everyone signed in can read it; nigel and jop can add transfers; only nigel can reset the opening balance.

create table if not exists public.kitty (
  id          bigint generated always as identity primary key,
  kind        text          not null check (kind in ('opening', 'transfer')),
  amount      numeric(12,2) not null,
  note        text          not null default '',
  created_by  text,
  created_at  timestamptz   not null default now()
);

alter table public.kitty enable row level security;
grant select, insert, update, delete on public.kitty to authenticated;
revoke all on public.kitty from anon;

drop policy if exists "signed-in read kitty" on public.kitty;
drop policy if exists "nigel edits kitty"    on public.kitty;
drop policy if exists "jop adds transfers"   on public.kitty;
create policy "signed-in read kitty" on public.kitty for select to authenticated using (true);
create policy "nigel edits kitty" on public.kitty for all to authenticated
  using      ((auth.jwt() ->> 'email') = 'nigel@expenses.local')
  with check ((auth.jwt() ->> 'email') = 'nigel@expenses.local');
create policy "jop adds transfers" on public.kitty for insert to authenticated
  with check ((auth.jwt() ->> 'email') = 'jop@expenses.local' and kind = 'transfer');

-- Each expense can say whether it comes off / adds to the kitty (the tick on the Add page).
-- Empty (older entries) = the old rule: jop's entries count, nigel's don't.
alter table public.expenses add column if not exists kitty boolean;

-- Starting balance, counted from the moment this runs
insert into public.kitty (kind, amount, note, created_by)
select 'opening', 72966, 'Starting float', 'setup'
where not exists (select 1 from public.kitty where kind = 'opening');
