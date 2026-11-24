"""Test the PWA in real Edge with a mock Supabase backend.

  python tools/browser.py --check      run automated checks + screenshots (tools/screenshots/)
  python tools/browser.py              serve on http://127.0.0.1:8765 and open Edge (real config.js)

The --check mode serves a test config.js pointing at a fake Supabase that Playwright answers,
so it needs no real project and touches no real data.
"""
import argparse, http.server, json, re, socketserver, sys, tempfile, threading, time, uuid
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
        self.rows.append({**r, "id": self.next_id, "created_at": "2026-11-22T10:00:00Z"})
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
                if body.get("email") == "jo@expenses.local" and body.get("password") == "secret":
                    return ok({"access_token": "tok", "refresh_token": "ref", "expires_in": 3600})
                return ok({"error": "invalid_grant", "error_description": "Invalid login credentials"}, 400)
            return ok({"access_token": "tok2", "refresh_token": "ref2", "expires_in": 3600})
        if u.path == "/auth/v1/logout":
            return ok(None, 204)
        if u.path == "/rest/v1/expenses":
            if req.headers.get("authorization", "") not in ("Bearer tok", "Bearer tok2"):
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
            return ok(rows[a:b + 1])
        return ok({"message": "not found"}, 404)


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
        page.on("console", lambda m: m.type == "error" and errors.append(m.text))
        page.on("pageerror", lambda e: errors.append(str(e)))
        base = f"http://127.0.0.1:{PORT}/?sw"  # ?sw = keep the service worker on for the checks

        page.goto(base)
        page.wait_for_selector("#login:not([hidden])")
        page.screenshot(path=str(SHOTS / "01-login.png"))

        page.fill("#login-name", "Jo"); page.fill("#login-pass", "wrong"); page.click("#login-form button")
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
        page.click("#entry .l-del")
        rec("clear button empties form", page.input_value("#entry .l-amount") == "" and page.input_value("#entry .l-cat") == "Groceries (food)")
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
        page.click("#entry .l-del")
        page.select_option("#entry .l-cat", "Beer")  # blank form, category changed
        page.reload(); page.wait_for_selector("#app:not([hidden])")
        rec("blank form back to Groceries after reopening", page.input_value("#entry .l-cat") == "Groceries (food)")

        # History
        total_rows = len(mock.rows)
        page.click(".tabs button[data-page=history]")
        page.wait_for_function("document.querySelectorAll('#history-list details').length > 0")
        page.wait_for_function(f"document.querySelector('#history-info').textContent.includes('{total_rows} expenses')", timeout=10000)
        opened = page.eval_on_selector_all("#history-list details[open]", "els => els.map(e => e.dataset.month)")
        rec(f"all {total_rows} rows loaded (paging past 1000)", True)
        ms = page.evaluate("(() => { const t = performance.now(); renderHistory(); return performance.now() - t; })()")
        rec("history redraw is fast", ms < 150, f"{ms:.0f} ms, {page.locator('#history-list .row').count()} rows in page")
        rec("only current month expanded", opened == ["2026-11-01"], str(opened))
        page.screenshot(path=str(SHOTS / "03-history.png"))
        page.click("#history-list details[data-month='2026-10-01'] summary")
        page.screenshot(path=str(SHOTS / "04-history-oct-open.png"))

        # Filter
        page.click(".tabs button[data-page=filter]")
        page.select_option("#f-cat", "Beer")
        page.select_option("#f-month", "2026-11-01")
        summ = page.text_content("#f-summary")
        exp = [r for r in mock.rows if r["category"] == "Beer" and r["month"] == "2026-11-01"]
        exp_total = f"{sum(r['amount'] for r in exp):,.2f}"
        rec("filter category + month", summ.startswith(f"{len(exp)} item") and exp_total in summ, f"{summ} (expected {len(exp)}, {exp_total})")
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
        page.screenshot(path=str(SHOTS / "09-budget.png"), full_page=True)
        page.click("#b-prev")
        rec("budget month back to October", page.text_content("#b-month") == "October 2026")
        page.click("#b-next")
        page.click(".tabs button[data-page=add]")
        lbl = page.eval_on_selector("#entry .l-cat", "s => s.options[s.selectedIndex].textContent")
        rec("Add drop-down shows % used", lbl == f"Groceries (food) · {exp_pct}%", lbl)
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

        # Sign out
        page.click("#menu-btn"); page.click("#menu button[data-action=logout]")
        page.wait_for_selector("#login:not([hidden])")
        rec("sign out", True)

        errs = [e for e in errors if "internetdisconnected" not in e.lower() and "ERR_INTERNET_DISCONNECTED" not in e
                and "status of 400" not in e]  # 400 = the deliberate wrong-password test
        rec("no JavaScript/console errors", not errs, "; ".join(errs[:5]))
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
