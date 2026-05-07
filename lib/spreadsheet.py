from lib.scoring import fmt_profiles, fmt_evidence
"""Spreadsheet export for kcommit-analysis-pipeline.

v9.12 changes:
  - Individual write_xlsx / write_ods each write a single-sheet file.
  - New write_summary_xlsx / write_summary_ods produce a multi-sheet summary
    (summary.xlsx / summary.ods) merging all datasets into one workbook:
    Relevant Commits, Filtered Commits, Profile Summary, Profile Matrix.
"""
import os
import zipfile
import xml.sax.saxutils as _sx

# ── Column definitions ────────────────────────────────────────────────────────
COMMIT_COLS          = ['Rank', 'SHA', 'Subject', 'Author', 'Date',
                        'Score', 'Profiles', 'Product Evidence']
COMMIT_COLS_FILTERED = COMMIT_COLS + ['Filter Reason']
SUMMARY_COLS         = ['Profile', 'Count', 'Total Score', 'Avg Score']
MATRIX_COLS          = ['Rank', 'SHA', 'Subject', 'Profile', 'Total Score', 'Profile Score']


# ── Shared row builders ───────────────────────────────────────────────────────
def _commit_row(c, include_reason=False):
    row = [
        c.get('_rank', ''),
        (c.get('commit') or '')[:12],
        c.get('subject', ''),
        c.get('author_name', ''),
        c.get('author_time', ''),
        c.get('score', 0) or 0,
        fmt_profiles(c),
        fmt_evidence(c),
    ]
    if include_reason:
        row.append(c.get('_filter_reason', ''))
    return row


def _summary_rows(ps):
    return [
        [n, d.get('commit_count', d.get('count', 0)),
         d.get('total_score', 0), round(d.get('avg_score', 0), 2)]
        for n, d in sorted(ps.items(),
                           key=lambda kv: kv[1].get('commit_count', 0), reverse=True)
    ]


def _matrix_rows(scored):
    rows = []
    for c in scored:
        sc = c.get('scoring', {}) or {}
        for p in (c.get('matched_profiles') or []):
            rows.append([
                c.get('_rank', ''),
                (c.get('commit') or '')[:12],
                c.get('subject', ''),
                p,
                c.get('score', 0) or 0,
                (sc.get('profiles') or {}).get(p, 0),
            ])
    return rows


# ── XLSX via openpyxl ─────────────────────────────────────────────────────────
def _xlsx_write_sheet(ws, headers, rows, col_widths=None):
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.utils import get_column_letter
    HEADER_FILL   = PatternFill('solid', fgColor='1F4E79')
    HEADER_FONT_W = Font(bold=True, name='Calibri', size=11, color='FFFFFF')
    WRAP          = Alignment(wrap_text=True, vertical='top')
    TOP           = Alignment(vertical='top')
    ws.append(headers)
    for cell in ws[1]:
        cell.font      = HEADER_FONT_W
        cell.fill      = HEADER_FILL
        cell.alignment = WRAP
    ws.row_dimensions[1].height = 18
    for row in rows:
        ws.append(row)
    for i, cell in enumerate(ws[1]):
        col = get_column_letter(i + 1)
        ws.column_dimensions[col].width = (col_widths or {}).get(i, 18)
    ws.freeze_panes = 'A2'
    ws.auto_filter.ref = ws.dimensions
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = TOP


def _xlsx_save(wb, path):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    wb.save(path)


def write_xlsx(path: str, scored: list, profile_summary: dict,
               sheet_name: str = 'Commits',
               include_reason: bool = False) -> None:
    """Write a single-sheet XLSX for *scored* commits."""
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet_name
    cols = COMMIT_COLS_FILTERED if include_reason else COMMIT_COLS
    widths = {0: 6, 1: 13, 2: 60, 3: 22, 4: 18, 5: 8, 6: 30, 7: 40}
    if include_reason:
        widths[8] = 30
    _xlsx_write_sheet(ws, cols, [_commit_row(c, include_reason) for c in scored], widths)
    _xlsx_save(wb, path)


def write_summary_xlsx(path: str, scored: list, filtered: list,
                       profile_summary: dict,
                       report_title: str = 'kcommit Analysis Report') -> None:
    """Write a multi-sheet summary XLSX merging all datasets."""
    import openpyxl
    wb = openpyxl.Workbook()

    ws1 = wb.active
    ws1.title = 'Relevant Commits'
    _xlsx_write_sheet(ws1, COMMIT_COLS, [_commit_row(c) for c in scored],
                      {0: 6, 1: 13, 2: 60, 3: 22, 4: 18, 5: 8, 6: 30, 7: 40})

    if filtered:
        ws2 = wb.create_sheet('Filtered Commits')
        _xlsx_write_sheet(ws2, COMMIT_COLS_FILTERED,
                          [_commit_row(c, include_reason=True) for c in filtered],
                          {0: 6, 1: 13, 2: 60, 3: 22, 4: 18, 5: 8, 6: 30, 7: 40, 8: 30})

    if profile_summary:
        ws3 = wb.create_sheet('Profile Summary')
        _xlsx_write_sheet(ws3, SUMMARY_COLS, _summary_rows(profile_summary),
                          {0: 28, 1: 10, 2: 12, 3: 10})

    ws4 = wb.create_sheet('Profile Matrix')
    _xlsx_write_sheet(ws4, MATRIX_COLS, _matrix_rows(scored),
                      {0: 6, 1: 13, 2: 50, 3: 22, 4: 12, 5: 12})

    _xlsx_save(wb, path)


# ── ODS via stdlib zipfile ────────────────────────────────────────────────────
_ODS_NS = (
    ' xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"'
    ' xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0"'
    ' xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"'
    ' xmlns:fo="urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0"'
    ' xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0"'
)
_ODS_HEAD = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    f'<office:document-content{_ODS_NS} office:version="1.2">'
    '<office:automatic-styles>'
    '<style:style style:name="H" style:family="table-cell">'
    '<style:text-properties fo:font-weight="bold"/></style:style>'
    '</office:automatic-styles>'
    '<office:body><office:spreadsheet>'
)
_ODS_TAIL = '</office:spreadsheet></office:body></office:document-content>'


def _ods_cell(value, bold=False):
    s     = ' table:style-name="H"' if bold else ''
    vtype = 'float' if isinstance(value, (int, float)) and not isinstance(value, bool) else 'string'
    esc   = _sx.escape(str(value if value is not None else ''))
    if vtype == 'float':
        return (f'<table:table-cell{s} office:value-type="float"'
                f' office:value="{value}"><text:p>{esc}</text:p></table:table-cell>')
    return (f'<table:table-cell{s} office:value-type="string">'
            f'<text:p>{esc}</text:p></table:table-cell>')


def _ods_sheet(name, headers, rows):
    lines = [f'<table:table table:name="{_sx.escape(name)}">']
    lines.append('<table:table-row>'
                 + ''.join(_ods_cell(h, bold=True) for h in headers)
                 + '</table:table-row>')
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
    with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
        zi = zipfile.ZipInfo('mimetype')
        zi.compress_type = zipfile.ZIP_STORED
        zf.writestr(zi, 'application/vnd.oasis.opendocument.spreadsheet')
        zf.writestr('META-INF/manifest.xml', manifest)
        zf.writestr('content.xml', content)


def write_ods(path: str, scored: list, profile_summary: dict,
              sheet_name: str = 'Commits',
              include_reason: bool = False) -> None:
    """Write a single-sheet ODS for *scored* commits."""
    cols = COMMIT_COLS_FILTERED if include_reason else COMMIT_COLS
    content = (
        _ODS_HEAD
        + _ods_sheet(sheet_name, cols,
                     [_commit_row(c, include_reason) for c in scored])
        + _ODS_TAIL
    )
    _ods_save(content, path)


def write_summary_ods(path: str, scored: list, filtered: list,
                      profile_summary: dict,
                      report_title: str = 'kcommit Analysis Report') -> None:
    """Write a multi-sheet summary ODS merging all datasets."""
    sheets = _ods_sheet('Relevant Commits', COMMIT_COLS,
                        [_commit_row(c) for c in scored])
    if filtered:
        sheets += _ods_sheet('Filtered Commits', COMMIT_COLS_FILTERED,
                             [_commit_row(c, include_reason=True) for c in filtered])
    if profile_summary:
        sheets += _ods_sheet('Profile Summary', SUMMARY_COLS,
                             _summary_rows(profile_summary))
    sheets += _ods_sheet('Profile Matrix', MATRIX_COLS, _matrix_rows(scored))
    _ods_save(_ODS_HEAD + sheets + _ODS_TAIL, path)
