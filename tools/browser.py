"""Test the PWA in real Edge with a mock Supabase backend.

  python tools/browser.py --check      run automated checks + screenshots (tools/screenshots/)
  python tools/browser.py              serve on http://127.0.0.1:8765 and open Edge (real config.js)

The --check mode serves a test config.js pointing at a fake Supabase that Playwright answers,
so it needs no real project and touches no real data.
"""
import argparse, datetime, http.server, json, re, socketserver, sys, tempfile, threading, time, uuid
from functools import partial
from pathlib import Path
from urllib.parse import urlparse, parse_qs

ROOT = Path(__file__).resolve().parent.parent
SHOTS = Path(__file__).resolve().parent / "screenshots"
PORT = 8765
MOCK = "https://mock-project.supabase.co"
APP_FILES = ["./", "index.html", "styles.css", "app.js", "config.js", "manifest.webmanifest",
             "icons/icon-192.png", "icons/icon-512.png", "icons/icon-maskable-512.png"]
SIZES = {"iphone13": (390, 844), "fold7-outer": (411, 960), "fold7-inner": (750, 832), "fold5-outer": (344, 882), "desktop": (1100, 800)}


class Handler(http.server.SimpleHTTPRequestHandler):
    test_mode = False

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_GET(self):
        if self.test_mode and self.path.split("?")[0] == "/config.js":
            src = (ROOT / "config.js").read_text(encoding="utf-8")
            src = re.sub(r"SUPABASE_URL: '[^']*'", f"SUPABASE_URL: '{MOCK}'", src)
            src = re.sub(r"SUPABASE_ANON_KEY: '[^']*'", "SUPABASE_ANON_KEY: 'test-anon'", src)
            body = src.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/javascript")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()

    def log_message(self, *a):
        pass


def serve(test_mode):
    Handler.test_mode = test_mode
    socketserver.TCPServer.allow_reuse_address = True
    httpd = socketserver.ThreadingTCPServer(("127.0.0.1", PORT), partial(Handler, directory=str(ROOT)))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


class MockSupabase:
    def __init__(self):
        self.rows, self.offline, self.next_id = [], False, 1
        self.kitty = [{"kind": "opening", "amount": 72966, "note": "Starting float", "created_by": "setup",
                       "created_at": "2026-11-01T00:00:00+00:00"}]
        cfg = (ROOT / "config.js").read_text(encoding="utf-8").split("BUDGETS: {")[1].split("}")[0]
        self.budgets = [{"category": c, "amount": float(v), "from_month": "2020-02-01"}
                        for c, v in re.findall(r"'([^']+)':\s*([\d.]+)", cfg)]
        cats = ["Groceries (food)", "Eating Out", "Beer", "Car Expenses", "Digital", "Cat expenses"]
        xlsx = ROOT / "history.xlsx"
        if xlsx.exists():  # the real history (6.6k rows) via the import script's own row builder
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            from import_history import build_rows
            for r in build_rows(xlsx)[0]:
                self.add(r)
            cats = []
        # otherwise 1,150 made-up rows over ~2 years so paging (1,000-row pages) is exercised
        for i in range(1150 if cats else 0):
            y, m = 2026, 10 - (i % 24)
            while m < 1:
                m += 12; y -= 1
            self.add({"month": f"{y}-{m:02d}-01", "category": cats[i % len(cats)], "amount": round(5 + (i * 7.31) % 120, 2),
                      "comment": f"seed {i}", "created_by": "seed", "client_id": str(uuid.uuid4())})
        self.add({"month": "2026-11-01", "category": "Beer", "amount": 12.5, "comment": "Pub quiz", "created_by": "jo", "client_id": str(uuid.uuid4())})

    def add(self, r):
        if any(x["client_id"] == r["client_id"] for x in self.rows if r.get("client_id")):
            return
        self.rows.append({"created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(), **r, "id": self.next_id})
        self.next_id += 1

    def handle(self, route):
        req = route.request
        cors = {"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Headers": "*",
                "Access-Control-Allow-Methods": "GET,POST,PATCH,DELETE,OPTIONS", "Access-Control-Expose-Headers": "Content-Range"}
        if self.offline:
            return route.abort("internetdisconnected")
        if req.method == "OPTIONS":
            return route.fulfill(status=204, headers=cors)
        u = urlparse(req.url)
        q = parse_qs(u.query)

        def ok(data, status=200):
            route.fulfill(status=status, headers={**cors, "Content-Type": "application/json"},
                          body=json.dumps(data) if data is not None else "")

        if u.path == "/auth/v1/token":
            body = json.loads(req.post_data or "{}")
            if q.get("grant_type") == ["password"]:
                if body.get("email") == "jop@expenses.local" and body.get("password") == "secret":
                    return ok({"access_token": "tok", "refresh_token": "ref", "expires_in": 3600})
                if body.get("email") == "nigel@expenses.local" and body.get("password") == "secret":
                    return ok({"access_token": "tokN", "refresh_token": "refN", "expires_in": 3600})
                return ok({"error": "invalid_grant", "error_description": "Invalid login credentials"}, 400)
            return ok({"access_token": "tok2", "refresh_token": "ref2", "expires_in": 3600})
        if u.path == "/auth/v1/logout":
            return ok(None, 204)
        if u.path == "/rest/v1/expenses":
            if req.headers.get("authorization", "") not in ("Bearer tok", "Bearer tok2", "Bearer tokN"):
                return ok({"message": "JWT invalid"}, 401)
            if req.method == "POST":
                for r in json.loads(req.post_data):
                    self.add(r)
                return ok(None, 201)
            if req.method in ("PATCH", "DELETE"):
                rid = int(q["id"][0].removeprefix("eq."))
                if req.method == "DELETE":
                    self.rows = [r for r in self.rows if r["id"] != rid]
                else:
                    for r in self.rows:
                        if r["id"] == rid:
                            r.update(json.loads(req.post_data))
                return ok(None, 204)
            rows = sorted(self.rows, key=lambda r: (r["month"], r["id"]), reverse=True)
            a, b = map(int, req.headers.get("range", f"0-{len(rows)}").split("-"))
            cols = q.get("select", ["*"])[0].split(",")  # like the real database: only the columns asked for
            return ok([r if cols == ["*"] else {c: r.get(c) for c in cols} for r in rows[a:b + 1]])
        if u.path == "/rest/v1/kitty":
            authz = req.headers.get("authorization", "")
            if authz not in ("Bearer tok", "Bearer tok2", "Bearer tokN"):
                return ok({"message": "JWT invalid"}, 401)
            if req.method == "POST":
                rows_in = json.loads(req.post_data)
                if authz != "Bearer tokN" and any(r.get("kind") != "transfer" for r in rows_in):
                    return ok({"message": "new row violates row-level security policy"}, 403)
                for r in rows_in:
                    self.kitty.append({**r, "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat()})
                return ok(None, 201)
            return ok(sorted(self.kitty, key=lambda k: k["created_at"]))
        if u.path == "/rest/v1/budgets":
            authz = req.headers.get("authorization", "")
            if authz not in ("Bearer tok", "Bearer tok2", "Bearer tokN"):
                return ok({"message": "JWT invalid"}, 401)
            if req.method == "POST":
                if authz != "Bearer tokN":  # only nigel (row-level security in the real database)
                    return ok({"message": "new row violates row-level security policy"}, 403)
                for r in json.loads(req.post_data):
                    self.budgets = [b for b in self.budgets if not (b["category"] == r["category"] and b["from_month"] == r["from_month"])]
                    self.budgets.append({k: r[k] for k in ("category", "amount", "from_month")})
                return ok(None, 201)
            return ok(sorted(self.budgets, key=lambda b: b["from_month"]))
        return ok({"message": "not found"}, 404)


# Deprecated / problem markup that Edge only reports with DevTools open, so check the files directly.
LINT_RULES = [
    ("index.html", lambda s: 'name="apple-mobile-web-app-capable"' in s and 'name="mobile-web-app-capable"' not in s,
     'apple-mobile-web-app-capable without the standard <meta name="mobile-web-app-capable" content="yes">'),
    ("index.html", lambda s: "user-scalable=no" in s or "maximum-scale=1" in s, "zoom disabled in viewport meta (accessibility)"),
    ("index.html", lambda s: 'name="viewport"' not in s, "missing viewport meta"),
    ("index.html", lambda s: 'rel="manifest"' not in s, "missing manifest link"),
]


def rec_lint(rec):
    problems = [msg for f, bad, msg in LINT_RULES if bad((ROOT / f).read_text(encoding="utf-8"))]
    rec("no deprecated / missing page tags", not problems, "; ".join(problems))


def check():
    from playwright.sync_api import sync_playwright
    SHOTS.mkdir(exist_ok=True)
    httpd = serve(test_mode=True)
    mock = MockSupabase()
    results, errors = [], []

    def rec(name, passed, detail=""):
        results.append((name, passed, detail))
        print(f"[{'PASS' if passed else 'FAIL'}] {name}" + (f" - {detail}" if detail else ""))

    with sync_playwright() as p, tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as prof:
        ctx = p.chromium.launch_persistent_context(prof, channel="msedge", headless=True,
                                                   viewport={"width": 411, "height": 960}, device_scale_factor=2,
                                                   permissions=["clipboard-read", "clipboard-write"])
        ctx.route(f"{MOCK}/**", mock.handle)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        # Collect errors AND warnings from every channel: page console, browser log, DevTools "Issues"
        page.on("console", lambda m: m.type in ("error", "warning") and errors.append(f"console {m.type}: {m.text}"))
        page.on("pageerror", lambda e: errors.append(f"page error: {e}"))
        logcdp = ctx.new_cdp_session(page)
        logcdp.on("Log.entryAdded", lambda e: e["entry"]["level"] in ("error", "warning")
                  and errors.append(f"browser {e['entry']['level']}: {e['entry']['text']}"))
        logcdp.on("Audits.issueAdded", lambda e: errors.append(f"DevTools issue: {e['issue']['code']} {json.dumps(e['issue'].get('details', {}))[:200]}"))
        logcdp.send("Log.enable"); logcdp.send("Audits.enable")
        rec_lint(rec)
        base = f"http://127.0.0.1:{PORT}/?sw"  # ?sw = keep the service worker on for the checks

        page.goto(base)
        page.wait_for_selector("#login:not([hidden])")
        page.screenshot(path=str(SHOTS / "01-login.png"))

        page.fill("#login-name", "jop"); page.fill("#login-pass", "wrong"); page.click("#login-form button")
        page.wait_for_function("document.querySelector('#login-error').textContent.length > 0")
        rec("wrong password rejected", "Wrong name or password" in page.text_content("#login-error"))

        page.fill("#login-pass", "secret"); page.click("#login-form button")
        page.wait_for_selector("#app:not([hidden])")
        rec("login with name + password", True)

        # Add: one entry form; "+ New line" moves it into a list below; upload sends list + form
        n0 = len(mock.rows)
        rec("form starts on Groceries", page.input_value("#entry .l-cat") == "Groceries (food)")
        order = page.eval_on_selector_all("#entry .l-cat option", "os => os.map(o => o.value)")
        rec("drop-down in new order", order[:3] == ["Groceries (food)", "Eating Out", "Domestic"] and order[10] == "Pocket Money (JOP)", str(order))
        page.fill("#entry .l-amount", "54.20"); page.fill("#entry .l-comment", "Tesco weekly shop")
        page.click("#add-line")
        rec("new line moves entry to list, form cleared",
            page.locator("#staged .staged").count() == 1 and page.input_value("#entry .l-amount") == ""
            and page.input_value("#entry .l-cat") == "Groceries (food)")
        page.select_option("#entry .l-cat", "Beer"); page.fill("#entry .l-amount", "9"); page.fill("#entry .l-comment", "beer edit me")
        page.click("#add-line")
        rec("newest entry at top of list", "beer edit me" in page.text_content("#staged .staged:first-child"))
        page.click("#staged .staged:first-child .s-edit")
        rec("Edit puts entry back in form", page.input_value("#entry .l-comment") == "beer edit me"
            and page.locator("#staged .staged").count() == 1)
        rec("kitty ticked by default for jop", page.is_checked("#entry .l-kittybox"))
        page.fill("#entry .l-amount", ""); page.fill("#entry .l-comment", ""); page.select_option("#entry .l-cat", "Groceries (food)")
        page.select_option("#entry .l-cat", "Investment (+/-)")
        rec("type button starts on Expense", page.text_content("#entry .l-type") == "Expense")
        page.fill("#entry .l-amount", "250"); page.click("#entry .l-type")
        rec("type button switches to Income", page.text_content("#entry .l-type") == "Income")
        page.fill("#entry .l-comment", "Fund withdrawal")
        page.reload(); page.wait_for_selector("#app:not([hidden])")
        rec("list and half-filled form (Income) kept after reopening", page.locator("#staged .staged").count() == 1
            and page.input_value("#entry .l-amount") == "250" and page.text_content("#entry .l-type") == "Income")
        page.click("#add-line")
        card = page.locator("#staged .staged:first-child .s-amt")
        rec("income shown green without minus", card.text_content() == "\u0e3f250.00" and card.locator(".inc").count() == 1,
            card.text_content())
        page.click("#staged .staged:first-child .s-edit")
        page.screenshot(path=str(SHOTS / "02-add.png"))
        page.click("#upload")
        page.wait_for_function("document.querySelector('#add-msg').textContent.includes('uploaded')")
        new = mock.rows[n0:]
        rec("upload sends list + form (2 rows)", len(new) == 2, f"{len(new)} new")
        rec("month stored as 1st of month", all(r["month"] == "2026-11-01" for r in new), str([r["month"] for r in new]))
        rec("negative amount kept", any(r["amount"] == -250 for r in new))
        rec("list emptied after upload", page.locator("#staged .staged").count() == 0)

        # Validation + defaults after reopening
        page.fill("#entry .l-comment", "no amount given")
        page.click("#add-line")
        rec("entry without amount is flagged", page.locator("#entry.invalid").count() == 1)
        page.fill("#entry .l-comment", "")
        page.select_option("#entry .l-cat", "Beer")  # blank form, category changed
        page.reload(); page.wait_for_selector("#app:not([hidden])")
        rec("blank form back to Groceries after reopening", page.input_value("#entry .l-cat") == "Groceries (food)")

        # History
        total_rows = len(mock.rows)
        page.click(".tabs button[data-page=history]")
        page.wait_for_function("document.querySelectorAll('#history-list details').length > 0")
        page.wait_for_function(f"cache.rows.length === {total_rows}", timeout=10000)
        info = page.text_content("#history-info")
        rec("history top shows only 'Last synced'", info.startswith("Last synced") and "expenses" not in info, info)
        opened = page.eval_on_selector_all("#history-list details[open]", "els => els.map(e => e.dataset.month)")
        rec(f"all {total_rows} rows loaded (paging past 1000)", True)
        ms = page.evaluate("(() => { const t = performance.now(); renderHistory(); return performance.now() - t; })()")
        rec("history redraw is fast", ms < 150, f"{ms:.0f} ms, {page.locator('#history-list .row').count()} rows in page")
        rec("only current month expanded", opened == ["2026-11-01"], str(opened))
        main = ["Pocket Money (NIG)", "Pocket Money (JOP)", "Groceries (food)", "Eating Out", "Domestic", "Beer", "Car Expenses",
                "Cat expenses", "Health expenses", "Digital", "Travel and Holiday", "One-off expenses", "Quintara"]
        exp_nov = sum(r["amount"] for r in mock.rows if r["month"] == "2026-11-01" and r["category"] in main)
        meta = page.text_content("#history-list details[data-month='2026-11-01'] .m-meta")
        rec("month total = main categories only", f"{abs(exp_nov):,.2f}" in meta, f"{meta} expected {exp_nov:,.2f}")
        page.screenshot(path=str(SHOTS / "03-history.png"))
        page.click("#history-list details[data-month='2026-10-01'] summary")
        page.screenshot(path=str(SHOTS / "04-history-oct-open.png"))

        # Filter
        page.click(".tabs button[data-page=filter]")
        page.select_option("#f-cat", "Beer")
        page.select_option("#f-month", "2026-11-01")
        summ = page.text_content("#f-summary")
        exp = [r for r in mock.rows if r["category"] == "Beer" and r["month"] == "2026-11-01"]
        exp_total = f"{int(abs(sum(r['amount'] for r in exp)) + 0.5):,}"  # round half up, like the app
        rec("filter category + month", summ.startswith(f"{len(exp)} item") and exp_total in summ, f"{summ} (expected {len(exp)}, {exp_total})")
        rec("filter: whole baht, button says Copy", ".00" not in summ and page.text_content("#f-copy") == "Copy"
            and ".00" not in page.text_content("#f-list"), summ)
        rec("amounts shown in baht", "฿" in summ)
        page.select_option("#f-month", "")
        page.screenshot(path=str(SHOTS / "05-filter.png"))
        page.select_option("#f-cat", "")
        rec("filter list capped at 300 with note", page.locator("#f-list .row").count() == 300 and page.is_visible("#f-more"),
            page.text_content("#f-more"))
        page.select_option("#f-month", "2026-11-01"); page.select_option("#f-cat", "")
        page.click("#f-copy")
        clip = page.evaluate("navigator.clipboard.readText()")
        rec("copy for Excel (TSV, '1 NOV 26' dates)", clip.splitlines()[1].startswith("1 NOV 26\t"), clip.splitlines()[1])

        # Budget tab + % in Add drop-down
        groc = sum(r["amount"] for r in mock.rows if r["month"] == "2026-11-01" and r["category"] == "Groceries (food)")
        exp_pct = round(groc / 14000 * 100)
        page.click(".tabs button[data-page=budget]")
        page.wait_for_selector("#b-list .b-row")
        first = page.text_content("#b-list .b-row:first-child")
        rec("budget tab: Groceries % for this month", f"{exp_pct}%" in first and "Groceries" in first, f"{first.split()[:6]} expected {exp_pct}%")
        rec("budget tab lists 13 budgeted categories", page.locator("#b-list .b-row").count() == 13)
        btxt = page.text_content("#b-total") + page.text_content("#b-list")
        rec("budget page: no decimals, no 'Budgeted categories' label", ".00" not in btxt and "Budgeted" not in btxt,
            page.text_content("#b-total"))
        page.screenshot(path=str(SHOTS / "09-budget.png"), full_page=True)
        page.click("#b-prev")
        rec("budget month back to October", page.text_content("#b-month") == "October 2026")
        page.click("#b-next")
        page.click(".tabs button[data-page=add]")
        lbl = page.eval_on_selector("#entry .l-cat", "s => s.options[s.selectedIndex].textContent")
        rec("Add drop-down shows % used", lbl == f"Groceries (food) · {exp_pct}%", lbl)
        page.click(".tabs button[data-page=filter]")

        # Kitty: everything jop enters comes off (spend) / adds to (income) the kitty
        def kitty_expected():
            start = [k for k in mock.kitty if k["kind"] == "opening"][-1]
            t0 = start["created_at"]
            bal = start["amount"] + sum(k["amount"] for k in mock.kitty if k["kind"] == "transfer" and k["created_at"] >= t0)
            in_k = lambda r: r["kitty"] if r.get("kitty") is not None else str(r.get("created_by", "")).lower() == "jop"
            bal -= sum(r["amount"] for r in mock.rows if in_k(r) and r["created_at"] >= t0)
            return bal
        page.wait_for_function("document.querySelector('#kitty-pill').textContent.startsWith('\u0e3f')")
        exp_k = kitty_expected()
        pill = page.text_content("#kitty-pill")
        rec("kitty pill = 72,966 - jop's spending + jop's income (number only)", pill == f"\u0e3f{int(exp_k + 0.5):,}", f"{pill} expected {exp_k:,.2f}")
        # jop unticks Kitty on one entry: it then doesn't touch the kitty
        page.click(".tabs button[data-page=add]")
        page.fill("#entry .l-amount", "700"); page.fill("#entry .l-comment", "paid by card, not kitty"); page.uncheck("#entry .l-kittybox")
        page.click("#upload")
        page.wait_for_function("document.querySelector('#add-msg').textContent.includes('uploaded')")
        page.wait_for_timeout(500)
        rec("jop's entry with Kitty unticked leaves the kitty alone", page.text_content("#kitty-pill") == pill
            and mock.rows[-1]["kitty"] is False, page.text_content("#kitty-pill"))
        rec("tick back on for jop's next entry", page.is_checked("#entry .l-kittybox"))
        page.click(".tabs button[data-page=history]")
        note_row = page.locator("#history-list .row:has-text('paid by card, not kitty') .r-note")
        rec("history labels jop's entry 'not from kitty'", note_row.count() == 1 and note_row.text_content() == "not from kitty")
        rec("normal entries have no kitty label", page.locator("#history-list .row:has-text('Fund withdrawal') .r-note").count() == 0)
        page.screenshot(path=str(SHOTS / "16-history-kitty-note.png"))
        rec("history rows don't touch the kitty", all(str(r.get("created_by")) != "jop" for r in mock.rows[:6600]))
        page.click("#kitty-pill")
        klist = page.text_content("#k-list")
        rec("pill opens the kitty page", page.text_content("#page-title") == "Jop's kitty" and "Starting balance" in klist)
        rec("statement: spending one line per month, income on its own",
            klist.count("Spending · November 2026") == 1 and "Investment (+/-) · Fund withdrawal" in klist, klist[:160])
        page.screenshot(path=str(SHOTS / "13-kitty.png"))
        page.click(".tabs button[data-page=filter]")

        # Edit + delete synced rows (from Filter, Nov 2026)
        page.select_option("#f-month", "2026-11-01")
        page.click("#f-list .row:has-text('Fund withdrawal')")
        page.wait_for_selector("#edit-dlg[open]")
        page.screenshot(path=str(SHOTS / "08-edit-dialog.png"))
        rec("edit dialog shows Income for money in", page.text_content("#e-type") == "Income"
            and page.input_value("#e-amount") == "250.00")
        page.fill("#e-amount", "300")
        page.select_option("#e-cat", "Planned expenses")
        page.fill("#e-comment", "Fund withdrawal (fixed)")
        page.click("#e-save")
        page.wait_for_selector("#edit-dlg:not([open])", state="attached")
        fw = [r for r in mock.rows if r["comment"].startswith("Fund withdrawal")]
        rec("edit saves to database", bool(fw) and fw[0]["amount"] == -300 and fw[0]["category"] == "Planned expenses", str(fw[:1]))
        rec("edited row shown", page.locator("#f-list .row:has-text('Fund withdrawal (fixed)')").count() == 1)
        n_before = len(mock.rows)
        page.once("dialog", lambda d: d.accept())
        page.click("#f-list .row:has-text('Tesco weekly shop')")
        page.click("#e-del")
        page.wait_for_selector("#edit-dlg:not([open])", state="attached")
        rec("delete removes from database", len(mock.rows) == n_before - 1 and not any(r["comment"] == "Tesco weekly shop" for r in mock.rows))
        rec("deleted row gone from list", page.locator("#f-list .row:has-text('Tesco weekly shop')").count() == 0)

        # Service worker / cache / installability
        page.wait_for_function("navigator.serviceWorker.controller !== null || (navigator.serviceWorker.ready && true)")
        page.evaluate("navigator.serviceWorker.ready")
        sw_active = page.evaluate("navigator.serviceWorker.ready.then(r => !!r.active)")
        rec("service worker active", sw_active)
        cached = page.evaluate("caches.keys().then(ks => caches.open(ks[0])).then(c => c.keys()).then(rs => rs.map(r => new URL(r.url).pathname))")
        missing = [f for f in APP_FILES if "/" + f.lstrip("./") not in cached]
        rec("cache holds every app file", not missing, f"missing {missing}" if missing else f"{len(cached)} files")
        cdp = ctx.new_cdp_session(page)
        inst = cdp.send("Page.getInstallabilityErrors")["installabilityErrors"]
        rec("installable", not inst, str(inst))

        # Offline: reload, add, then reconnect
        page.reload(); page.wait_for_selector("#app:not([hidden])")
        mock.offline = True
        ctx.set_offline(True)
        page.reload(); page.wait_for_selector("#app:not([hidden])")
        page.wait_for_function("document.querySelector('#net-status').textContent === 'Offline'", timeout=5000)
        rec("app opens offline and shows Offline", True)
        page.click(".tabs button[data-page=add]")
        page.select_option("#entry .l-cat", "Cat expenses")
        page.fill("#entry .l-amount", "18.99")
        page.fill("#entry .l-comment", "Litter")
        n1 = len(mock.rows)
        page.click("#upload")
        page.wait_for_selector("#outbox-banner:not([hidden])")
        page.screenshot(path=str(SHOTS / "06-offline-queued.png"))
        rec("offline upload is queued on phone", len(mock.rows) == n1 and "1 expense" in page.text_content("#outbox-banner"))
        page.click(".tabs button[data-page=history]")
        rec("history works offline (saved copy + pending)", page.locator(".row.pending").count() == 1)
        page.click(".row.pending")
        page.fill("#e-amount", "21.50"); page.click("#e-save")
        page.wait_for_selector("#edit-dlg:not([open])", state="attached")
        ob = page.evaluate("JSON.parse(localStorage.getItem('exp.outbox'))")
        rec("edit waiting (offline) expense on phone", bool(ob) and ob[0]["amount"] == 21.5, str(ob))
        page.click("#history-list .row:not(.pending)")
        page.fill("#e-amount", "1"); page.click("#e-save")
        page.wait_for_function("document.querySelector('#e-msg').textContent.includes('needs the internet')")
        rec("offline edit of uploaded expense explains it needs connection", True)
        page.click("#e-cancel")
        mock.offline = False
        ctx.set_offline(False)
        page.wait_for_selector("#outbox-banner[hidden]", state="attached", timeout=30000)
        rec("queued expense uploads on reconnect", len(mock.rows) == n1 + 1 and mock.rows[-1]["amount"] == 21.5)

        # Import
        page.click("#menu-btn"); page.click("#menu button[data-action=import]")
        page.fill("#imp-text", "Date\tCategory\tAmount\tComment\n1 Oct 25\tBeer\t9.80\tLocal\n01/09/2025\tdigital\t7,99\tNetflix\nAug-25\tEating Out\t£45.00\tBirthday\n45870\tDomestic\t20\tExcel serial date")
        page.click("#imp-check")
        page.wait_for_function("!document.querySelector('#imp-go').disabled")
        n2 = len(mock.rows)
        page.click("#imp-go")
        page.wait_for_function("document.querySelector('#imp-result').textContent.includes('uploaded')")
        imp = mock.rows[n2:]
        rec("import 4 pasted rows", len(imp) == 4, str([(r["month"], r["category"], r["amount"]) for r in imp]))
        rec("import parses date formats", [r["month"] for r in imp] == ["2025-10-01", "2025-09-01", "2025-08-01", "2025-08-01"])
        page.fill("#imp-text", "Date\tCategory\tAmount\tComment\n1 Oct 25\tBeer\t9.80\tLocal\n01/09/2025\tdigital\t7,99\tNetflix\nAug-25\tEating Out\t£45.00\tBirthday\n45870\tDomestic\t20\tExcel serial date")
        page.click("#imp-check"); page.wait_for_function("!document.querySelector('#imp-go').disabled")
        page.click("#imp-go"); page.wait_for_function("document.querySelector('#imp-result').textContent.includes('uploaded')")
        rec("re-importing same paste adds no duplicates", len(mock.rows) == n2 + 4)
        page.screenshot(path=str(SHOTS / "07-import.png"))

        # Swipe between tabs (touch, page follows the finger)
        page.click(".tabs button[data-page=add]")
        cdp.send("Emulation.setTouchEmulationEnabled", {"enabled": True, "maxTouchPoints": 1})

        def swipe(x0, x1, y=700, steps=8, check_mid=False):
            cdp.send("Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": [{"x": x0, "y": y}]})
            mid = None
            for k in range(1, steps + 1):
                cdp.send("Input.dispatchTouchEvent", {"type": "touchMove", "touchPoints": [{"x": x0 + (x1 - x0) * k / steps, "y": y}]})
                if check_mid and k == steps // 2:
                    page.screenshot(path=str(SHOTS / "10-mid-swipe.png"))
                    mid = page.evaluate("[document.querySelector('#page-add').style.transform, !document.querySelector('#page-history').hidden]")
            cdp.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
            page.wait_for_timeout(400)
            return mid

        mid = swipe(330, 60, check_mid=True)
        rec("page follows the finger mid-swipe", mid and mid[0].startswith("translateX(-") and mid[1], str(mid))
        rec("swipe left: Add -> History", page.text_content("#page-title") == "History")
        swipe(60, 330)
        rec("swipe right: History -> Add", page.text_content("#page-title") == "Add expenses")
        swipe(300, 260)
        rec("short drag springs back", page.text_content("#page-title") == "Add expenses"
            and page.evaluate("document.querySelector('#page-history').hidden"))
        swipe(60, 330)
        rec("no page before Add (stays put)", page.text_content("#page-title") == "Add expenses")
        box = page.locator("#entry .l-comment").bounding_box()
        swipe(box["x"] + box["width"] - 10, 40, y=box["y"] + box["height"] / 2)
        rec("swipe starting on a text box is ignored", page.text_content("#page-title") == "Add expenses")
        swipe(330, 60); swipe(330, 60)
        rec("swipe order Add > History > Budget", page.text_content("#page-title") == "Budget")
        swipe(330, 60)
        rec("then Filter (last)", page.text_content("#page-title") == "Filter")
        rec("tab buttons in order Add, History, Budget, Filter",
            page.eval_on_selector_all(".tabs button", "bs => bs.map(b => b.textContent)") == ["Add", "History", "Budget", "Filter"])
        cdp.send("Emulation.setTouchEmulationEnabled", {"enabled": False})

        # Screen sizes
        for name, (w, h) in SIZES.items():
            page.set_viewport_size({"width": w, "height": h})
            for tab in ["add", "history", "filter", "budget"]:
                page.click(f".tabs button[data-page={tab}]")
                page.wait_for_timeout(150)
                page.screenshot(path=str(SHOTS / f"size-{name}-{tab}.png"))
            page.click(".tabs button[data-page=history]")
            page.click("#history-list details[open] .row")
            page.wait_for_selector("#edit-dlg[open]")
            page.screenshot(path=str(SHOTS / f"size-{name}-edit.png"))
            page.click("#e-cancel")
            overflow = page.evaluate("document.documentElement.scrollWidth > document.documentElement.clientWidth")
            rec(f"no sideways scroll at {name} {w}x{h}", not overflow)

        # Edit budgets: hidden for jo, available to nigel
        page.click("#menu-btn")
        rec("Edit budgets hidden for jo", not page.is_visible("#menu button[data-action=budgets]"))
        rec("Transfer to kitty shown for jop too", page.is_visible("#menu button[data-action=transfer]"))
        k_before = kitty_expected()
        page.click("#menu button[data-action=transfer]")
        page.fill("#t-amount", "1000"); page.fill("#t-note", "from savings"); page.click("#t-save")
        page.wait_for_selector("#kitty-dlg:not([open])", state="attached")
        rec("jop's transfer adds to the kitty", page.text_content("#kitty-pill") == f"\u0e3f{int(k_before + 1000 + 0.5):,}",
            page.text_content("#kitty-pill"))
        page.click("#menu-btn")
        page.click("#menu button[data-action=logout]")
        page.wait_for_selector("#login:not([hidden])")
        rec("sign out", True)
        page.fill("#login-name", "nigel"); page.fill("#login-pass", "secret"); page.click("#login-form button")
        page.wait_for_selector("#app:not([hidden])")
        page.click("#menu-btn")
        rec("Edit budgets shown for nigel", page.is_visible("#menu button[data-action=budgets]"))
        page.click("#menu button[data-action=budgets]")
        page.wait_for_selector("#be-list .be-row")
        rec("edit list has the 13 categories with averages", page.locator("#be-list .be-row").count() == 13
            and "3-mo" in page.text_content("#be-list .be-row:first-child"))
        page.screenshot(path=str(SHOTS / "11-edit-budgets-list.png"))
        page.click("#be-list .be-row:first-child .be-edit")
        rec("Edit opens a page for just that category", page.locator("#be-list .be-row").count() == 0
            and page.text_content("#page-title") == "Groceries (food)" and page.locator("#be-list .be-m").count() == 12)
        rec("no 'use average' button", page.locator("#be-avg").count() == 0)
        page.screenshot(path=str(SHOTS / "12-edit-budget-one.png"))
        page.click("#be-back")
        rec("back returns to all 13", page.locator("#be-list .be-row").count() == 13)
        page.click("#be-list .be-row:first-child .be-edit")
        page.fill("#be-amount", "16000")
        page.click("#be-save")
        page.wait_for_function("!document.querySelector('#be-list .be-detail')")
        saved = [b for b in mock.budgets if b["category"] == "Groceries (food)"]
        rec("budget change saved with its start month", any(b["amount"] == 16000 and b["from_month"] == "2026-11-01" for b in saved), str(saved))
        page.click(".tabs button[data-page=budget]")
        nov = page.text_content("#b-list .b-row:first-child")
        page.click("#b-prev")
        octo = page.text_content("#b-list .b-row:first-child")
        rec("new budget from Nov; October keeps the old one", "of ฿16,000" in nov and "of ฿14,000" in octo, f"{nov[-40:]} | {octo[-40:]}")
        # Kitty transfer by nigel; nigel's own entries don't touch the kitty
        before_k = kitty_expected()
        page.click(".tabs button[data-page=add]")
        page.fill("#entry .l-amount", "500"); page.fill("#entry .l-comment", "nigel lunch"); page.click("#upload")
        page.wait_for_function("document.querySelector('#add-msg').textContent.includes('uploaded')")
        page.wait_for_timeout(500)
        rec("nigel's own spending leaves the kitty alone", page.text_content("#kitty-pill") == f"\u0e3f{int(before_k + 0.5):,}",
            page.text_content("#kitty-pill"))
        rec("kitty unticked by default for nigel", not page.is_checked("#entry .l-kittybox"))
        page.fill("#entry .l-amount", "300"); page.fill("#entry .l-comment", "paid for jop"); page.check("#entry .l-kittybox")
        page.click("#upload")
        page.wait_for_function("document.querySelector('#add-msg').textContent.includes('uploaded')")
        page.wait_for_timeout(500)
        rec("nigel's entry with Kitty ticked comes off the kitty", page.text_content("#kitty-pill") == f"\u0e3f{int(before_k - 300 + 0.5):,}"
            and mock.rows[-1]["kitty"] is True, page.text_content("#kitty-pill"))
        before_k = kitty_expected()
        page.click(".tabs button[data-page=history]")
        rec("nigel's ticked entry has no label", page.locator("#history-list .row:has-text('paid for jop') .r-note").count() == 0)
        n3 = page.locator("#history-list .row:has-text('nigel lunch') .r-note")
        rec("nigel's unticked entry says 'not from kitty'", n3.count() == 1 and n3.text_content() == "not from kitty")
        page.click("#menu-btn")
        rec("Transfer to kitty shown for nigel", page.is_visible("#menu button[data-action=transfer]"))
        page.click("#menu button[data-action=transfer]")
        page.fill("#t-amount", "20000"); page.fill("#t-note", "top up")
        page.screenshot(path=str(SHOTS / "14-transfer.png"))
        page.click("#t-save")
        page.wait_for_selector("#kitty-dlg:not([open])", state="attached")
        rec("transfer saved", any(k["kind"] == "transfer" and k["amount"] == 20000 for k in mock.kitty))
        rec("transfer adds to the kitty", page.text_content("#kitty-pill") == f"\u0e3f{int(before_k + 20000 + 0.5):,}",
            page.text_content("#kitty-pill"))
        page.click("#kitty-pill")
        rec("transfer on the statement, newest first", "Transfer from nigel · top up" in page.text_content("#k-list .k-row:first-child"))
        page.screenshot(path=str(SHOTS / "15-kitty-statement.png"))
        page.click("#menu-btn"); page.click("#menu button[data-action=logout]")
        page.wait_for_selector("#login:not([hidden])")

        expected = ("internetdisconnected", "err_internet_disconnected",  # the deliberate offline tests
                    "status of 400")                                      # the deliberate wrong-password test
        errs = list(dict.fromkeys(e for e in errors if not any(x in e.lower() for x in expected)))
        rec("no console errors or warnings (page, browser log, DevTools issues)", not errs, " | ".join(errs[:8]))
        ctx.close()
    httpd.shutdown()
    failed = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(failed)}/{len(results)} passed. Screenshots in {SHOTS}")
    return 1 if failed else 0


def demo():
    """Visible Edge with the mock backend (real history.xlsx if present). Sign in as jo / secret."""
    from playwright.sync_api import sync_playwright
    httpd = serve(test_mode=True)
    mock = MockSupabase()
    with sync_playwright() as p, tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as prof:
        ctx = p.chromium.launch_persistent_context(prof, channel="msedge", headless=False, no_viewport=True,
                                                   args=["--window-size=460,980"])
        ctx.route(f"{MOCK}/**", mock.handle)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(f"http://127.0.0.1:{PORT}/")
        print(f"Demo running with {len(mock.rows)} expenses (nothing is saved anywhere real).")
        print("Sign in with name: jo   password: secret")
        print("Close the Edge window to stop.")
        try:
            while ctx.pages:
                ctx.pages[0].wait_for_timeout(500)
        except Exception:
            pass
    httpd.shutdown()


def interactive():
    from playwright.sync_api import sync_playwright
    httpd = serve(test_mode=False)
    with sync_playwright() as p, tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as prof:
        ctx = p.chromium.launch_persistent_context(prof, channel="msedge", headless=False, viewport={"width": 411, "height": 860})
        (ctx.pages[0] if ctx.pages else ctx.new_page()).goto(f"http://127.0.0.1:{PORT}/")
        print(f"Serving http://127.0.0.1:{PORT}/ - close the browser window to stop.")
        while ctx.pages:
            time.sleep(0.5)
    httpd.shutdown()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--demo", action="store_true", help="try the app with a fake backend (jo / secret)")
    a = ap.parse_args()
    sys.exit(check() if a.check else demo() if a.demo else interactive())
