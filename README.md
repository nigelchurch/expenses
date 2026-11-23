# Expenses PWA

Phone app (installable PWA) for logging family expenses into a shared online table.
Backend: **Supabase** free tier (Postgres + login). Hosting: any static host, e.g. **GitHub Pages** (free, HTTPS).

## One-time setup

1. **Create the database** – sign up at supabase.com → *New project* (free plan, pick a region near you).
   SQL Editor → New query → paste `supabase/schema.sql` → Run (safe to re-run after app updates).
2. **Turn off public sign-up** – Authentication → Sign In / Providers → *Email*: turn **off** "Allow new users to sign up"
   (so only users you create can log in). Keep Email provider enabled.
3. **Create the users** – Authentication → Users → *Add user → Create new user*:
   email `jo@expenses.local` (login name `jo`), a password, tick **Auto confirm user**. Repeat for yourself.
   Login is the part before `@`, not case-sensitive.
4. **Connect the app** – Project Settings → API: copy *Project URL* and the *anon public* key into `config.js`.
5. **Load the history** – `python tools/import_history.py` shows what will be imported (dry run);
   `python tools/import_history.py --upload` asks for an app login and uploads `history.xlsx`
   (~6,600 rows; 'Incoming' rows and rows without a category or amount are skipped; money in becomes negative).
   Safe to run twice – no duplicates.
6. **Publish** – push this folder to a GitHub repo → Settings → Pages → deploy from `main` / root.
   Open the `https://<you>.github.io/<repo>/` link on the phone → Chrome menu → *Install app*.

Note: Supabase pauses a free project after ~7 days with **no** activity; normal daily use keeps it awake.
If it does pause, click *Restore* in the dashboard (no data lost).

## Using it

- **Add** – one card per expense (month, amount, category, comment). *+ New line* for more, *Upload expenses* sends them all.
  Negative amounts are allowed (e.g. Investment +/-). With no signal, they're saved on the phone and upload automatically later.
- **History** – everything, grouped by month with totals; current month open, others collapsed. Refreshes on every open/connection.
- **Filter** – category and/or month, total, and *Copy for Excel* (tab-separated; dates as `1 NOV 26`).
- **⋮ menu → Import history** – paste rows from Excel: Date, Category, Amount, Comment. Pasting the same rows twice doesn't duplicate.
- **Fix a mistake** – tap any expense in History or Filter → change it, or Delete. Needs a connection
  (expenses still waiting to upload can be changed offline).
- Amounts show in baht (`CURRENCY` in `config.js`); Copy for Excel gives plain numbers.
- Old categories from the history (NOVA, Relocation, Car Repayment) appear in History/Filter but not in the drop-down.

## Changing the app

- Categories: `config.js` → `CATEGORIES`.
- After changing any file, bump `VERSION` in `sw.js` so installed phones update.
- Test: `python tools/browser.py --check` (Edge + mock backend, screenshots in `tools/screenshots/`).
  `python tools/make_icons.py` regenerates the icons.
