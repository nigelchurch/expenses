"""Add a live "kitty from the app" figure to an Excel workbook (refreshes with Data > Refresh All).

  python tools/excel_kitty.py "C:\\Users\\nigel\\OneDrive\\Documents\\BUDGET.xlsm" --sheet Float --cell E1 --link B2

Puts a one-row table (Kitty, As of) at --cell and, with --link, points that cell at the kitty figure
(e.g. Float!B2, which the Finance Dashboard reads). Makes a backup first; the workbook must be closed.
The secret export code comes from private/excel_kitty.sql (never committed).
"""
import argparse, datetime, re, shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
QUERY = "KittyFromApp"
TABLE = "KittyFromApp"


def m_query():
    cfg = (ROOT / "config.js").read_text(encoding="utf-8")
    url = re.search(r"SUPABASE_URL:\s*'([^']*)'", cfg).group(1).rstrip("/")
    key = re.search(r"SUPABASE_ANON_KEY:\s*'([^']*)'", cfg).group(1)
    token = re.search(r"is distinct from '([^']*)'", (ROOT / "private" / "excel_kitty.sql").read_text(encoding="utf-8")).group(1)
    return f'''let
    Source = Json.Document(Web.Contents(
        "{url}/rest/v1/rpc/excel_kitty",
        [Headers = [apikey = "{key}", #"Content-Type" = "application/json"],
         Content = Text.ToBinary("{{""token"":""{token}""}}")])),
    Rows = Table.FromRecords(Source, {{"balance", "as_of"}}, MissingField.UseNull),
    Typed = Table.TransformColumnTypes(Rows, {{{{"balance", type number}}, {{"as_of", type datetimezone}}}}),
    Local = Table.TransformColumns(Typed, {{{{"as_of", each DateTimeZone.RemoveZone(DateTimeZone.ToLocal(_)), type datetime}}}}),
    Named = Table.RenameColumns(Local, {{{{"balance", "Kitty"}}, {{"as_of", "As of"}}}})
in
    Named'''


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("workbook")
    ap.add_argument("--sheet", default="TH Expenses")
    ap.add_argument("--cell", default="J1")
    ap.add_argument("--link", help="cell to point at the kitty figure, e.g. B2 or \"Finance Dashboard!C6\"")
    a = ap.parse_args()
    path = Path(a.workbook).resolve()
    backup = path.with_name(f"{path.stem}.backup-{datetime.datetime.now():%Y%m%d-%H%M%S}{path.suffix}")
    shutil.copy2(path, backup)
    print("Backup:", backup)

    import win32com.client as win32
    xl = win32.DispatchEx("Excel.Application")
    xl.Visible = False
    xl.DisplayAlerts = False
    xl.AutomationSecurity = 3
    saved = False
    try:
        wb = xl.Workbooks.Open(str(path), 0)
        ws = wb.Worksheets(a.sheet)
        for sh in wb.Worksheets:  # replace an earlier copy
            for lo in list(sh.ListObjects):
                if lo.Name == TABLE:
                    lo.Delete()
        for q in list(wb.Queries):
            if q.Name == QUERY:
                q.Delete()
        wb.Queries.Add(QUERY, m_query())
        conn = f'OLEDB;Provider=Microsoft.Mashup.OleDb.1;Data Source=$Workbook$;Location={QUERY};Extended Properties=""'
        lo = ws.ListObjects.Add(0, conn, True, 1, ws.Range(a.cell))
        qt = lo.QueryTable
        qt.CommandType = 2
        qt.CommandText = [f"SELECT * FROM [{QUERY}]"]
        qt.RowNumbers = False
        qt.PreserveFormatting = True
        qt.BackgroundQuery = False
        qt.Refresh(False)
        lo.Name = TABLE
        lo.ListColumns(1).DataBodyRange.NumberFormat = "#,##0"
        lo.ListColumns(2).DataBodyRange.NumberFormat = "d mmm yy hh:mm"
        lo.Range.Columns.AutoFit()
        before = None
        if a.link:
            sheet, _, cell = a.link.rpartition("!")
            target = (wb.Worksheets(sheet.strip("'")) if sheet else ws).Range(cell)
            before = (target.Formula, target.Value)
            target.Formula = f"=INDEX({TABLE}[Kitty],1)"
        xl.Calculate()
        print(f"Kitty table at {a.sheet}!{a.cell}: {lo.DataBodyRange.Cells(1, 1).Text.strip()} as of {lo.DataBodyRange.Cells(1, 2).Text}")
        if a.link:
            print(f"{a.link}: was {before[0]} = {before[1]}, now {target.Formula} = {target.Value}")
        wb.Save()
        saved = True
        wb.Close(False)
    finally:
        if not saved:
            print("Not saved - the workbook is unchanged.")
        xl.Quit()


if __name__ == "__main__":
    main()
