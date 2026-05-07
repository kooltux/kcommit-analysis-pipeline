from lib.scoring import fmt_profiles, fmt_evidence
"""Spreadsheet export for kcommit-analysis-pipeline.

v9.11: XLSX uses openpyxl for correctness; ODS remains stdlib (zipfile).
       Shared column layout and row builders used by all three formats.
"""
import os
import zipfile
import xml.sax.saxutils as _sx

# ── Column definitions ────────────────────────────────────────────────────────
COMMIT_COLS  = ['Rank', 'SHA', 'Subject', 'Author', 'Date',
                'Score', 'Profiles', 'Product Evidence']
SUMMARY_COLS = ['Profile', 'Count', 'Total Score', 'Avg Score']
MATRIX_COLS  = ['Rank', 'SHA', 'Subject', 'Profile', 'Total Score', 'Profile Score']


# ── Shared row builders ───────────────────────────────────────────────────────
def _commit_row(c):
    return [
        c.get('_rank', ''),
        (c.get('commit') or '')[:12],
        c.get('subject', ''),
        c.get('author_name', ''),
        c.get('author_time', ''),
        c.get('score', 0) or 0,
        fmt_profiles(c),
        fmt_evidence(c),
    ]


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
def write_xlsx(path: str, scored: list, profile_summary: dict,
               report_title: str = 'kcommit Analysis Report') -> None:
    """Write XLSX using openpyxl — correct shared strings, styles, col widths."""
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.utils import get_column_letter

    HEADER_FONT   = Font(bold=True, name='Calibri', size=11)
    HEADER_FILL   = PatternFill('solid', fgColor='1F4E79')
    HEADER_FONT_W = Font(bold=True, name='Calibri', size=11, color='FFFFFF')
    WRAP          = Alignment(wrap_text=True, vertical='top')
    TOP           = Alignment(vertical='top')

    def _write_sheet(ws, headers, rows, col_widths=None):
        ws.append(headers)
        for cell in ws[1]:
            cell.font      = HEADER_FONT_W
            cell.fill      = HEADER_FILL
            cell.alignment = WRAP
        ws.row_dimensions[1].height = 18
        for row in rows:
            ws.append(row)
        for i, cell in enumerate(ws[1]):
            col  = get_column_letter(i + 1)
            w    = (col_widths or {}).get(i, 18)
            ws.column_dimensions[col].width = w
        ws.freeze_panes = 'A2'
        # Auto-filter on header row
        ws.auto_filter.ref = ws.dimensions

    wb = openpyxl.Workbook()

    # Sheet 1: Commits
    ws1 = wb.active
    ws1.title = 'Commits'
    _write_sheet(ws1, COMMIT_COLS, [_commit_row(c) for c in scored],
                 {0: 6, 1: 13, 2: 60, 3: 22, 4: 18, 5: 8, 6: 30, 7: 40})
    for row in ws1.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = TOP

    # Sheet 2: Profile Summary
    ws2 = wb.create_sheet('Profile Summary')
    _write_sheet(ws2, SUMMARY_COLS, _summary_rows(profile_summary),
                 {0: 28, 1: 10, 2: 12, 3: 10})

    # Sheet 3: Profile Matrix
    ws3 = wb.create_sheet('Profile Matrix')
    _write_sheet(ws3, MATRIX_COLS, _matrix_rows(scored),
                 {0: 6, 1: 13, 2: 50, 3: 22, 4: 12, 5: 12})

    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    wb.save(path)


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


def write_ods(path: str, scored: list, profile_summary: dict,
              report_title: str = 'kcommit Analysis Report') -> None:
    content = (
        _ODS_HEAD
        + _ods_sheet('Commits',        COMMIT_COLS,  [_commit_row(c) for c in scored])
        + _ods_sheet('Profile Summary', SUMMARY_COLS, _summary_rows(profile_summary))
        + _ods_sheet('Profile Matrix',  MATRIX_COLS,  _matrix_rows(scored))
        + _ODS_TAIL
    )
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


