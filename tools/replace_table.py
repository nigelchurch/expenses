"""Turn an existing Excel table into a live, refreshable copy of the expenses database - same place, same name.

  python tools/replace_table.py "C:\\Users\\nigel\\OneDrive\\Documents\\BUDGET.xlsm" --sheet "TH Expenses" --table Table4

Keeps: the table name and position, extra calculated columns to the right of the 5 data columns,
formulas elsewhere that use the table, pivot tables built on it, number formats and table style.
Makes a backup first. The workbook must be closed in Excel. Afterwards Data > Refresh All updates it.
"""
import argparse, datetime, shutil, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from excel_sheet import QUERY_NAME, m_query  # noqa: E402

N_DATA = 5  # MONTH, MONEY IN, MONEY OUT, DESCRIPTION, DETAIL come from the database; any further columns are formulas


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("workbook")
    ap.add_argument("--sheet", required=True)
    ap.add_argument("--table", required=True)
    a = ap.parse_args()
    path = Path(a.workbook).resolve()
    backup = path.with_name(f"{path.stem}.backup-{datetime.datetime.now():%Y%m%d-%H%M%S}{path.suffix}")
    shutil.copy2(path, backup)
    print("Backup:", backup)

    import win32com.client as win32
    xl = win32.DispatchEx("Excel.Application")
    xl.Visible = False
    xl.DisplayAlerts = False
    xl.AutomationSecurity = 3  # don't run the workbook's macros while we work
    saved = False
    try:
        wb = xl.Workbooks.Open(str(path), 0)  # 0 = don't update links to other workbooks
        ws = wb.Worksheets(a.sheet)
        lo = ws.ListObjects(a.table)
        top_left = lo.Range.Cells(1, 1).Address
        headers = [lo.ListColumns(i).Name for i in range(1, lo.ListColumns.Count + 1)]
        first = lambda i: lo.ListColumns(i).DataBodyRange.Cells(1, 1)
        formats = [first(i).NumberFormat for i in range(1, len(headers) + 1)]
        extra = [(headers[i - 1], first(i).Formula) for i in range(N_DATA + 1, len(headers) + 1)]
        style = lo.TableStyle.Name if lo.TableStyle else None
        rows_before = lo.ListRows.Count

        # formulas anywhere in the workbook that use the table
        refs = []
        for sh in wb.Worksheets:
            try:
                cells = sh.UsedRange.SpecialCells(-4123)  # xlCellTypeFormulas
            except Exception:
                continue
            for c in cells:
                if a.table + "[" in c.Formula and not (sh.Name == ws.Name and lo.Range.Row <= c.Row):
                    refs.append((sh.Name, c.Address, c.Formula, c.Value))
        # pivot tables built on the table
        pivots = [(sh.Name, pt.Name) for sh in wb.Worksheets for pt in sh.PivotTables()
                  if str(pt.SourceData).strip("'") in (a.table, f"{a.table}[#All]")]
        print(f"Table {a.table} at {top_left}: {rows_before} rows, columns {headers}")
        print(f"  calculated columns kept: {[n for n, _ in extra]}")
        print(f"  formulas using it: {[(s, ad) for s, ad, _, _ in refs]}")
        print(f"  pivot tables using it: {pivots}")

        # replace the table with the live query (same name, same place)
        lo.Delete()
        for q in list(wb.Queries):
            if q.Name == QUERY_NAME:
                q.Delete()
        wb.Queries.Add(QUERY_NAME, m_query(tuple(headers[:N_DATA])))
        conn = f'OLEDB;Provider=Microsoft.Mashup.OleDb.1;Data Source=$Workbook$;Location={QUERY_NAME};Extended Properties=""'
        new = ws.ListObjects.Add(0, conn, True, 1, ws.Range(top_left))
        qt = new.QueryTable
        qt.CommandType = 2
        qt.CommandText = [f"SELECT * FROM [{QUERY_NAME}]"]
        qt.RowNumbers = False
        qt.PreserveFormatting = True
        qt.AdjustColumnWidth = False
        qt.BackgroundQuery = False  # Refresh All finishes the data before pivots refresh
        qt.Refresh(False)
        new.Name = a.table
        if style:
            new.TableStyle = style
        for name, formula in extra:
            col = new.ListColumns.Add()
            col.Name = name
            col.DataBodyRange.Formula = formula
        for i, fmt in enumerate(formats, start=1):
            new.ListColumns(i).DataBodyRange.NumberFormat = "mmm yy" if i == 1 else fmt
        for sh, addr, formula, _ in refs:
            # Headers with leading/trailing spaces (e.g. " -   ") break structured references when Excel
            # re-parses them, so refer to such columns by position instead.
            for n, h in enumerate(headers, start=1):
                if h != h.strip():
                    formula = formula.replace(f"{a.table}[{h}]", f"INDEX({a.table},0,{n})")
            wb.Worksheets(sh).Range(addr).Formula = formula
        for sh, name in pivots:
            pc = wb.PivotCaches().Create(1, a.table)  # xlDatabase
            wb.Worksheets(sh).PivotTables(name).ChangePivotCache(pc)
        xl.Calculate()

        print(f"Now {new.ListRows.Count} rows (was {rows_before}).")
        for sh, addr, formula, before in refs:
            after = wb.Worksheets(sh).Range(addr).Value
            print(f"  {sh}!{addr}  {formula[:40]:40}  before {before!s:>18}  after {after!s:>18}")
        wb.Save()
        saved = True
        wb.Close(False)
    finally:
        if not saved:
            print("Not saved - the workbook is unchanged.")
        xl.Quit()


if __name__ == "__main__":
    main()
