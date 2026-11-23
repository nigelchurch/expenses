"""One-off upload of history.xlsx into the Supabase expenses table.

  python tools/import_history.py            dry run: show what would be imported / skipped
  python tools/import_history.py --upload   sign in with an app name + password and upload

Columns: MONTH (Excel date) | MONEY IN | MONEY OUT | DESCRIPTION (category) | DETAIL (comment)
Rules: 'Incoming' rows and rows without a category or amount are skipped;
money in becomes a negative amount; category spelling is matched case-insensitively.
Re-running is safe: every row has a fixed client_id, duplicates are ignored by the database.
"""
import argparse, collections, datetime, getpass, hashlib, json, re, sys, urllib.error, urllib.request, uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
XLSX = ROOT / "history.xlsx"
OLD_CATEGORIES = ["NOVA", "Relocation", "Car Repayment"]  # only in past data
SKIP_CATEGORIES = {"incoming"}


def read_config():
    src = (ROOT / "config.js").read_text(encoding="utf-8")
    get = lambda k: re.search(rf"{k}:\s*'([^']*)'", src).group(1)
    cats = re.findall(r"^\s*'([^']+)',\s*$", src.split("CATEGORIES:")[1], re.M)
    return {"url": get("SUPABASE_URL").rstrip("/"), "key": get("SUPABASE_ANON_KEY"),
            "domain": get("USER_DOMAIN"), "categories": cats}


def to_month(v):
    if isinstance(v, (int, float)):
        d = datetime.date(1899, 12, 30) + datetime.timedelta(days=int(v))
    elif isinstance(v, datetime.datetime):
        d = v.date()
    elif isinstance(v, datetime.date):
        d = v
    else:
        return None
    return f"{d.year}-{d.month:02d}-01"


def num(v):
    if v is None or (isinstance(v, str) and not v.strip()):
        return None
    try:
        return round(float(str(v).replace(",", "")), 2)
    except ValueError:
        return None


def build_rows(path=XLSX, categories=None):
    """Return (rows ready for the database, list of (sheet_row, reason, values) skipped)."""
    import openpyxl
    categories = categories or read_config()["categories"]
    known = {c.lower(): c for c in categories + OLD_CATEGORIES}
    ws = openpyxl.load_workbook(path, read_only=True, data_only=True).worksheets[0]
    rows, skipped = [], []
    for n, vals in enumerate(ws.iter_rows(min_row=2, max_col=5, values_only=True), start=2):
        m, money_in, money_out, desc, detail = (list(vals) + [None] * 5)[:5]
        if all(v is None for v in vals):
            continue
        cat = (str(desc).strip() if desc is not None else "")
        month = to_month(m)
        a_in, a_out = num(money_in), num(money_out)
        if cat.lower() in SKIP_CATEGORIES:
            skipped.append((n, "Incoming", vals)); continue
        if not cat:
            skipped.append((n, "no category", vals)); continue
        if not month:
            skipped.append((n, "no date", vals)); continue
        if a_in is None and a_out is None:
            skipped.append((n, "no amount", vals)); continue
        amount = (a_out or 0) - (a_in or 0)
        comment = "" if detail is None else str(detail).strip()
        category = known.get(cat.lower(), cat)
        key = f"history.xlsx|{n}|{month}|{category}|{amount}|{comment}"
        cid = str(uuid.UUID(bytes=hashlib.sha256(key.encode()).digest()[:16], version=4))
        rows.append({"month": month, "category": category, "amount": amount, "comment": comment,
                     "created_by": "history", "client_id": cid})
    return rows, skipped


def post(url, key, body, token=None, prefer=None):
    headers = {"apikey": key, "Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if prefer:
        headers["Prefer"] = prefer
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req) as r:
            txt = r.read().decode()
            return json.loads(txt) if txt else None
    except urllib.error.HTTPError as e:
        sys.exit(f"Server said {e.code}: {e.read().decode()[:300]}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--upload", action="store_true")
    ap.add_argument("--file", default=str(XLSX))
    args = ap.parse_args()
    cfg = read_config()
    rows, skipped = build_rows(Path(args.file), cfg["categories"])

    by_cat = collections.Counter(r["category"] for r in rows)
    by_year = collections.defaultdict(float)
    for r in rows:
        by_year[r["month"][:4]] += r["amount"]
    print(f"{len(rows)} rows to import, {len(skipped)} skipped "
          f"({', '.join(f'{k}: {v}' for k, v in collections.Counter(s[1] for s in skipped).items())})")
    print(f"Months {min(r['month'] for r in rows)} .. {max(r['month'] for r in rows)}")
    print("\nPer category:")
    for c, k in by_cat.most_common():
        flag = "" if c in cfg["categories"] else "   (old category, not in drop-down)"
        print(f"  {k:5}  {c}{flag}")
    print("\nTotal per year:")
    for y in sorted(by_year):
        print(f"  {y}  {by_year[y]:>14,.2f}")
    print("\nSkipped rows (sheet row, reason, values):")
    for s in skipped:
        print(f"  {s[0]:5}  {s[1]:12} {s[2]}")

    if not args.upload:
        print("\nDry run only. Add --upload to send to Supabase.")
        return
    if "YOUR-PROJECT" in cfg["url"]:
        sys.exit("Fill in SUPABASE_URL and SUPABASE_ANON_KEY in config.js first.")
    name = input("\nApp login name: ").strip()
    pw = getpass.getpass("Password: ")
    auth = post(f"{cfg['url']}/auth/v1/token?grant_type=password", cfg["key"],
                {"email": f"{name.lower()}@{cfg['domain']}", "password": pw})
    token = auth["access_token"]
    for i in range(0, len(rows), 500):
        post(f"{cfg['url']}/rest/v1/expenses?on_conflict=client_id", cfg["key"], rows[i:i + 500], token,
             "resolution=ignore-duplicates,return=minimal")
        print(f"  uploaded {min(i + 500, len(rows))}/{len(rows)}")
    print("Done. Re-running will not create duplicates.")


if __name__ == "__main__":
    main()
