"""Add (or replace) a sheet holding a live, refreshable copy of the expenses table in an Excel workbook.

  python tools/excel_sheet.py history.xlsx            -> sheet "App data" in history.xlsx
  python tools/excel_sheet.py "C:\\path\\Work.xlsx" --sheet "Expenses"

A backup copy (<name>.backup-<date>.xlsx) is made first. Needs Excel for Windows (drives it via COM).
The query reads the secret export code from private/excel_export.sql (never committed to git).
Afterwards, in Excel: Data > Refresh All updates the table from the database.
"""
import argparse, datetime, re, shutil, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
QUERY_NAME = "ExpensesFromApp"


HEADERS = ("MONTH", "MONEY IN…", "MONEY OUT…", "DESCRIPTION", "DETAIL")


def m_query(headers=HEADERS):
    h_month, h_in, h_out, h_desc, h_detail = headers
    cfg = (ROOT / "config.js").read_text(encoding="utf-8")
    url = re.search(r"SUPABASE_URL:\s*'([^']*)'", cfg).group(1).rstrip("/")
    key = re.search(r"SUPABASE_ANON_KEY:\s*'([^']*)'", cfg).group(1)
    token = re.search(r"is distinct from '([^']*)'", (ROOT / "private" / "excel_export.sql").read_text(encoding="utf-8")).group(1)
    # Same layout as the original workbook table: everything goes in MONEY OUT (income / refunds as negatives),
    # except bank transfers (category "Incoming"), which go in MONEY IN as positive numbers, as they always did.
    return f'''let
    Source = Json.Document(Web.Contents(
        "{url}/rest/v1/rpc/excel_export",
        [Headers = [apikey = "{key}", #"Content-Type" = "application/json"],
         Content = Text.ToBinary("{{""token"":""{token}""}}")])),
    Rows = Table.FromRecords(Source, {{"month", "category", "amount", "comment", "created_by", "id"}}, MissingField.UseNull),
    Typed = Table.TransformColumnTypes(Rows, {{{{"month", type date}}, {{"amount", type number}}, {{"category", type text}}, {{"comment", type text}}}}),
    AddIn = Table.AddColumn(Typed, "{h_in}", each if [category] = "Incoming" then -[amount] else null, type number),
    AddOut = Table.AddColumn(AddIn, "{h_out}", each if [category] = "Incoming" then null else [amount], type number),
    Picked = Table.SelectColumns(AddOut, {{"month", "{h_in}", "{h_out}", "category", "comment"}}),
    Named = Table.RenameColumns(Picked, {{{{"month", "{h_month}"}}, {{"category", "{h_desc}"}}, {{"comment", "{h_detail}"}}}})
in
    Named'''


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("workbook")
    ap.add_argument("--sheet", default="App data")
    a = ap.parse_args()
    wb_path = Path(a.workbook).resolve()
    if not wb_path.exists():
        sys.exit(f"Not found: {wb_path}")
    backup = wb_path.with_name(f"{wb_path.stem}.backup-{datetime.datetime.now():%Y%m%d-%H%M%S}{wb_path.suffix}")
    shutil.copy2(wb_path, backup)
    print("Backup:", backup)

    import win32com.client as win32
    xl = win32.DispatchEx("Excel.Application")  # private Excel instance, doesn't touch any open windows
    xl.Visible = False
    xl.DisplayAlerts = False
    try:
        wb = xl.Workbooks.Open(str(wb_path))
        for q in list(wb.Queries):
            if q.Name == QUERY_NAME:
                q.Delete()
        for ws in list(wb.Worksheets):
            if ws.Name == a.sheet:
                ws.Delete()
        wb.Queries.Add(QUERY_NAME, m_query())
        ws = wb.Worksheets.Add()
        ws.Name = a.sheet
        ws.Move(None, wb.Worksheets(wb.Worksheets.Count))  # put it last (positional: Before=None, After=last)
        conn = (f"OLEDB;Provider=Microsoft.Mashup.OleDb.1;Data Source=$Workbook$;"
                f"Location={QUERY_NAME};Extended Properties=\"\"")
        # positional: SourceType=xlSrcExternal, Source, LinkSource, XlListObjectHasHeaders=xlYes, Destination
        lo = ws.ListObjects.Add(0, conn, True, 1, ws.Range("$A$1"))
        lo.Name = "AppExpenses"
        qt = lo.QueryTable
        qt.CommandType = 2  # xlCmdSql
        qt.CommandText = [f"SELECT * FROM [{QUERY_NAME}]"]
        qt.RowNumbers = False
        qt.PreserveFormatting = True
        qt.RefreshOnFileOpen = False
        qt.AdjustColumnWidth = True
        qt.Refresh(False)
        ws.Range("A:A").NumberFormat = "mmm yy"  # month only (always the 1st) - suits pivot tables
        ws.Range("B:C").NumberFormat = "#,##0"
        rows = lo.ListRows.Count
        wb.Save()
        print(f"Sheet '{a.sheet}' added with {rows} rows. In Excel: Data > Refresh All to update.")
        wb.Close(False)
    finally:
        xl.Quit()


if __name__ == "__main__":
    main()
