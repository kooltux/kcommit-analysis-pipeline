from lib.scoring import fmt_profiles, fmt_evidence
"""Spreadsheet export for kcommit-analysis-pipeline.

v9.14 changes:
  - Native Python types throughout: datetime for dates, int/float for numbers.
  - XLSX: _xlsx_write_sheet applies number/date cell formats automatically
    by inspecting cell value type (datetime → date format, float → 0.00,
    int → 0).  Auto-width measures actual rendered text width including
    header row, capped 8–60 chars.
  - ODS: _ods_cell handles datetime with office:value-type="date" and
    office:date-value="ISO8601". Floats keep office:value-type="float".

E.1: COMMIT_COLS, COMMIT_COLS_FILTERED, SUMMARY_COLS, MATRIX_COLS,
     STATS_COLS moved to lib.manifest (single source of truth).
     This module re-exports them for backward import compatibility.
"""
import datetime
import os
import zipfile
import xml.sax.saxutils as _sx

# Column definitions imported from manifest (single source of truth)
from lib.manifest import (COMMIT_COLS, COMMIT_COLS_FILTERED,
                          SUMMARY_COLS, MATRIX_COLS, STATS_COLS)


# ── Date helper ───────────────────────────────────────────────────────────────
def _parse_date(ts):
    """Convert a Unix timestamp (int/str) to a datetime object, or None."""
    if not ts:
        return None
    try:
        return datetime.datetime.fromtimestamp(int(ts), tz=datetime.timezone.utc).replace(tzinfo=None)
    except (TypeError, ValueError):
        return None


def _fmt_date_str(ts):
    """Return YYYY-MM-DD HH:MM string for display (CSV / ODS text fallback)."""
    dt = _parse_date(ts)
    return dt.strftime("%Y-%m-%d %H:%M") if dt else (str(ts)[:16] if ts else "")


# ── Shared row builders ───────────────────────────────────────────────────────
def _commit_row(c, include_reason=False, native_types=False):
    """Build a row for a commit record.

    When *native_types* is True (XLSX path), the Date cell is a datetime
    object so openpyxl can apply a real date format.  Otherwise it is a
    formatted string (CSV / ODS text path).
    """
    date_val = _parse_date(c.get("author_time")) if native_types else _fmt_date_str(c.get("author_time"))
    row = [
        c.get("_rank") or "",
        (c.get("commit") or "")[:12],
        c.get("subject", ""),
        c.get("author_name", ""),
        date_val,
        float(c.get("score", 0) or 0),
        fmt_profiles(c),
        fmt_evidence(c),
    ]
    if include_reason:
        row.append(c.get("_filter_reason", ""))
    return row


def _summary_rows(ps, native_types=False):
    return [
        [n,
         int(d.get("commit_count", d.get("count", 0))),
         float(d.get("total_score", 0)),
         round(float(d.get("avg_score", 0)), 2)]
        for n, d in sorted(ps.items(),
                           key=lambda kv: kv[1].get("commit_count", 0), reverse=True)
    ]


def _matrix_rows(scored, native_types=False):
    rows = []
    for c in scored:
        sc = c.get("scoring", {}) or {}
        for p in (c.get("matched_profiles") or []):
            rows.append([
                c.get("_rank") or "",
                (c.get("commit") or "")[:12],
                c.get("subject", ""),
                p,
                float(c.get("score", 0) or 0),
                float((sc.get("profiles") or {}).get(p, 0)),
            ])
    return rows


def _stats_rows(report_stats):
    rows = []
    for k, v in sorted((report_stats or {}).items()):
        if isinstance(v, float):
            rows.append([k, v])
        elif isinstance(v, int):
            rows.append([k, v])
        else:
            rows.append([k, str(v)])
    return rows


# ── XLSX via openpyxl ─────────────────────────────────────────────────────────
_XLSX_DATE_FMT  = "YYYY-MM-DD HH:MM"
_XLSX_FLOAT_FMT = "0.00"
_XLSX_INT_FMT   = "0"


def _xlsx_write_sheet(ws, headers, rows):
    """Write headers + rows to *ws* with auto-width and typed cell formats."""
    from openpyxl.styles import Font, PatternFill, Alignment, numbers as xl_numbers
    from openpyxl.utils import get_column_letter

    HEADER_FILL   = PatternFill("solid", fgColor="1F4E79")
    HEADER_FONT_W = Font(bold=True, name="Calibri", size=11, color="FFFFFF")
    TOP           = Alignment(vertical="top", wrap_text=False)

    ws.append(headers)
    for cell in ws[1]:
        cell.font      = HEADER_FONT_W
        cell.fill      = HEADER_FILL
        cell.alignment = Alignment(vertical="top", wrap_text=False)
    ws.row_dimensions[1].height = 18

    for row in rows:
        ws.append(row)

    # Apply cell-level formats by value type
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = TOP
            if isinstance(cell.value, datetime.datetime):
                cell.number_format = _XLSX_DATE_FMT
            elif isinstance(cell.value, float):
                cell.number_format = _XLSX_FLOAT_FMT
            elif isinstance(cell.value, int) and not isinstance(cell.value, bool):
                cell.number_format = _XLSX_INT_FMT

    # Auto-fit column widths: measure rendered text length for every cell
    for i, col_cells in enumerate(ws.columns):
        col_letter = get_column_letter(i + 1)
        max_len = 0
        for cell in col_cells:
            if cell.value is None:
                continue
            if isinstance(cell.value, datetime.datetime):
                display = cell.value.strftime("%Y-%m-%d %H:%M")
            else:
                display = str(cell.value)
            max_len = max(max_len, len(display))
        ws.column_dimensions[col_letter].width = min(max(max_len + 2, 8), 60)

    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions


def _xlsx_save(wb, path):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    wb.save(path)


def _new_wb():
    import openpyxl
    return openpyxl.Workbook()


def write_xlsx(path: str, scored: list, profile_summary: dict,
               sheet_name: str = "Commits",
               include_reason: bool = False) -> None:
    """Write a single-sheet XLSX for *scored* commits."""
    wb = _new_wb()
    ws = wb.active
    ws.title = sheet_name
    cols = COMMIT_COLS_FILTERED if include_reason else COMMIT_COLS
    _xlsx_write_sheet(ws, cols,
                      [_commit_row(c, include_reason, native_types=True) for c in scored])
    _xlsx_save(wb, path)


def write_profile_summary_xlsx(path: str, profile_summary: dict) -> None:
    """Write a single-sheet XLSX for profile summary."""
    wb = _new_wb()
    ws = wb.active
    ws.title = "Profile Summary"
    _xlsx_write_sheet(ws, SUMMARY_COLS, _summary_rows(profile_summary, native_types=True))
    _xlsx_save(wb, path)


def write_profile_matrix_xlsx(path: str, scored: list) -> None:
    """Write a single-sheet XLSX for profile matrix."""
    wb = _new_wb()
    ws = wb.active
    ws.title = "Profile Matrix"
    _xlsx_write_sheet(ws, MATRIX_COLS, _matrix_rows(scored, native_types=True))
    _xlsx_save(wb, path)


def write_summary_xlsx(path: str, scored: list, filtered: list,
                       profile_summary: dict, report_stats: dict = None,
                       report_title: str = "kcommit Analysis Report") -> None:
    """Write a multi-sheet summary XLSX.

    Sheet order: Report Stats, Relevant Commits, Filtered Commits,
                 Profile Summary, Profile Matrix.
    """
    wb = _new_wb()

    ws0 = wb.active
    ws0.title = "Report Stats"
    _xlsx_write_sheet(ws0, STATS_COLS, _stats_rows(report_stats))

    ws1 = wb.create_sheet("Relevant Commits")
    _xlsx_write_sheet(ws1, COMMIT_COLS,
                      [_commit_row(c, native_types=True) for c in scored])

    if filtered:
        ws2 = wb.create_sheet("Filtered Commits")
        _xlsx_write_sheet(ws2, COMMIT_COLS_FILTERED,
                          [_commit_row(c, include_reason=True, native_types=True)
                           for c in filtered])

    if profile_summary:
        ws3 = wb.create_sheet("Profile Summary")
        _xlsx_write_sheet(ws3, SUMMARY_COLS, _summary_rows(profile_summary, native_types=True))

    ws4 = wb.create_sheet("Profile Matrix")
    _xlsx_write_sheet(ws4, MATRIX_COLS, _matrix_rows(scored, native_types=True))

    _xlsx_save(wb, path)


# ── ODS via stdlib zipfile ────────────────────────────────────────────────────
_ODS_NS = (
    ' xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"'
    ' xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0"'
    ' xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"'
    ' xmlns:fo="urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0"'
    ' xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0"'
    ' xmlns:number="urn:oasis:names:tc:opendocument:xmlns:datastyle:1.0"'
)
_ODS_HEAD = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    f'<office:document-content{_ODS_NS} office:version="1.2">'
    '<office:automatic-styles>'
    '<style:style style:name="H" style:family="table-cell">'
    '<style:text-properties fo:font-weight="bold"/></style:style>'
    '<style:style style:name="CO" style:family="table-column">'
    '<style:table-column-properties'
    ' style:use-optimal-column-width="true"/></style:style>'
    '<number:date-style style:name="ND">'
    '<number:year number:style="long"/>'
    '<number:text>-</number:text>'
    '<number:month number:style="long"/>'
    '<number:text>-</number:text>'
    '<number:day number:style="long"/>'
    '<number:text> </number:text>'
    '<number:hours number:style="long"/>'
    '<number:text>:</number:text>'
    '<number:minutes number:style="long"/>'
    '</number:date-style>'
    '<style:style style:name="DC" style:family="table-cell"'
    ' style:data-style-name="ND"/>'
    '<number:number-style style:name="NF">'
    '<number:number number:decimal-places="2" number:min-integer-digits="1"/>'
    '</number:number-style>'
    '<style:style style:name="FC" style:family="table-cell"'
    ' style:data-style-name="NF"/>'
    '</office:automatic-styles>'
    '<office:body><office:spreadsheet>'
)
_ODS_TAIL = '</office:spreadsheet></office:body></office:document-content>'


def _ods_cell(value, bold=False):
    """Render a typed ODS cell element."""
    style = ' table:style-name="H"' if bold else ''
    if isinstance(value, datetime.datetime):
        iso = value.strftime("%Y-%m-%dT%H:%M:%S")
        disp = _sx.escape(value.strftime("%Y-%m-%d %H:%M"))
        return (f'<table:table-cell table:style-name="DC"'
                f' office:value-type="date" office:date-value="{iso}">'
                f'<text:p>{disp}</text:p></table:table-cell>')
    if isinstance(value, float):
        esc = _sx.escape(f"{value:.2f}")
        return (f'<table:table-cell{style} table:style-name="FC"'
                f' office:value-type="float" office:value="{value}">'
                f'<text:p>{esc}</text:p></table:table-cell>')
    if isinstance(value, int) and not isinstance(value, bool):
        esc = _sx.escape(str(value))
        return (f'<table:table-cell{style}'
                f' office:value-type="float" office:value="{value}">'
                f'<text:p>{esc}</text:p></table:table-cell>')
    esc = _sx.escape(str(value) if value is not None else "")
    return (f'<table:table-cell{style} office:value-type="string">'
            f'<text:p>{esc}</text:p></table:table-cell>')


def _ods_sheet(name, headers, rows):
    ncols = len(headers)
    col_tags = '<table:table-column table:style-name="CO"/>' * ncols
    lines = [f'<table:table table:name="{_sx.escape(name)}">'
             + col_tags
             + '<table:table-row>'
             + ''.join(_ods_cell(h, bold=True) for h in headers)
             + '</table:table-row>']
    for row in rows:
        lines.append('<table:table-row>'
                     + ''.join(_ods_cell(v) for v in row)
                     + '</table:table-row>')
    lines.append('</table:table>')
    return ''.join(lines)


def _ods_save(content, path):
    manifest = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<manifest:manifest'
        ' xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0">'
        '<manifest:file-entry'
        ' manifest:media-type="application/vnd.oasis.opendocument.spreadsheet"'
        ' manifest:full-path="/"/>'
        '<manifest:file-entry manifest:media-type="text/xml"'
        ' manifest:full-path="content.xml"/>'
        '</manifest:manifest>'
    )
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zi = zipfile.ZipInfo("mimetype")
        zi.compress_type = zipfile.ZIP_STORED
        zf.writestr(zi, "application/vnd.oasis.opendocument.spreadsheet")
        zf.writestr("META-INF/manifest.xml", manifest)
        zf.writestr("content.xml", content)


def write_ods(path: str, scored: list, profile_summary: dict,
              sheet_name: str = "Commits",
              include_reason: bool = False) -> None:
    """Write a single-sheet ODS for *scored* commits."""
    cols = COMMIT_COLS_FILTERED if include_reason else COMMIT_COLS
    content = (
        _ODS_HEAD
        + _ods_sheet(sheet_name, cols,
                     [_commit_row(c, include_reason, native_types=True) for c in scored])
        + _ODS_TAIL
    )
    _ods_save(content, path)


def write_profile_summary_ods(path: str, profile_summary: dict) -> None:
    """Write a single-sheet ODS for profile summary."""
    content = (_ODS_HEAD
               + _ods_sheet("Profile Summary", SUMMARY_COLS,
                             _summary_rows(profile_summary, native_types=True))
               + _ODS_TAIL)
    _ods_save(content, path)


def write_profile_matrix_ods(path: str, scored: list) -> None:
    """Write a single-sheet ODS for profile matrix."""
    content = (_ODS_HEAD
               + _ods_sheet("Profile Matrix", MATRIX_COLS,
                             _matrix_rows(scored, native_types=True))
               + _ODS_TAIL)
    _ods_save(content, path)


def write_summary_ods(path: str, scored: list, filtered: list,
                      profile_summary: dict, report_stats: dict = None,
                      report_title: str = "kcommit Analysis Report") -> None:
    """Write a multi-sheet summary ODS.

    Sheet order: Report Stats, Relevant Commits, Filtered Commits,
                 Profile Summary, Profile Matrix.
    """
    sheets  = _ods_sheet("Report Stats",     STATS_COLS,  _stats_rows(report_stats))
    sheets += _ods_sheet("Relevant Commits", COMMIT_COLS,
                         [_commit_row(c, native_types=True) for c in scored])
    if filtered:
        sheets += _ods_sheet("Filtered Commits", COMMIT_COLS_FILTERED,
                             [_commit_row(c, include_reason=True, native_types=True)
                              for c in filtered])
    if profile_summary:
        sheets += _ods_sheet("Profile Summary", SUMMARY_COLS,
                             _summary_rows(profile_summary, native_types=True))
    sheets += _ods_sheet("Profile Matrix", MATRIX_COLS,
                         _matrix_rows(scored, native_types=True))
    _ods_save(_ODS_HEAD + sheets + _ODS_TAIL, path)
