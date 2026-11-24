-- Foreign-currency entries. Run once in Supabase > SQL Editor (safe to run again).
-- amount stays in THB (used everywhere); these keep what was actually typed on the Add page.
alter table public.expenses add column if not exists orig_amount numeric(14,2);  -- e.g. 45.00 (same sign as amount)
alter table public.expenses add column if not exists currency    text;           -- e.g. 'EUR'; empty = THB
alter table public.expenses add column if not exists fx_rate     numeric(14,6);  -- THB per 1 unit used, incl. the 2% bank margin
