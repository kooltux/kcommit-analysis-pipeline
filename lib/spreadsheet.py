"""Spreadsheet export for kcommit-analysis-pipeline.

v8.5.1: write_xlsx() rewritten with stdlib zipfile + XML only.
        openpyxl dependency dropped entirely.

Both write_xlsx() and write_ods() are now zero-dependency.
Three sheets in each output: Commits | Profile Summary | Profile Matrix.

Column layout
─────────────
Commits       : Rank | SHA | Subject | Author | Date | Score | Security |
                Performance | Product | Stable | Profiles | Product Evidence
Profile Summary: Profile | Count | Total Score | Avg Score
Profile Matrix : Rank | SHA | Subject | Profile | Total Score | Profile Score
"""
import os
import xml.sax.saxutils as _sx
import zipfile

COMMIT_COLS  = ['Rank', 'SHA', 'Subject', 'Author', 'Date',
                'Score', 'Security', 'Performance', 'Product', 'Stable',
                'Profiles', 'Product Evidence']
SUMMARY_COLS = ['Profile', 'Count', 'Total Score', 'Avg Score']
MATRIX_COLS  = ['Rank', 'SHA', 'Subject', 'Profile', 'Total Score', 'Profile Score']


# ── shared row builders ───────────────────────────────────────────────────────
def _commit_row(c):
    sc = c.get('scoring', {}) or {}
    return [c.get('_rank', ''), (c.get('commit') or '')[:12],
            c.get('subject', ''), c.get('author_name', ''), c.get('author_time', ''),
            c.get('score', 0) or 0,
            sc.get('security', 0) or 0, sc.get('performance', 0) or 0,
            sc.get('product', 0) or 0, sc.get('stable', 0) or 0,
            '; '.join(c.get('matched_profiles') or []),
            '; '.join(c.get('product_evidence') or [])]


def _summary_rows(ps):
    return [[n, d.get('count', 0), d.get('total_score', 0), d.get('avg_score', 0)]
            for n, d in sorted(ps.items(),
                               key=lambda kv: kv[1].get('count', 0), reverse=True)]


def _matrix_rows(scored):
    rows = []
    for c in scored:
        sc = c.get('scoring', {}) or {}
        for p in (c.get('matched_profiles') or []):
            rows.append([c.get('_rank', ''), (c.get('commit') or '')[:12],
                         c.get('subject', ''), p,
                         c.get('score', 0) or 0,
                         (sc.get('profiles') or {}).get(p, 0)])
    return rows


# ═══════════════════════════════════════════════════════════════════════════════
# XLSX — stdlib zipfile + XML, no external dependency
# ═══════════════════════════════════════════════════════════════════════════════
_XL_NS   = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
_REL_NS  = 'http://schemas.openxmlformats.org/package/2006/relationships'
_PKG_NS  = 'http://schemas.openxmlformats.org/package/2006/content-types'
_WB_TYPE = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml'
_WS_TYPE = 'application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml'
_ST_TYPE = 'application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml'
_WB_REL  = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/workbook'
_WS_REL  = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet'
_ST_REL  = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles'

_MIME_XLSX = ('application/vnd.openxmlformats-officedocument'
              '.spreadsheetml.sheet')

# Minimal styles: xf 0 = normal, xf 1 = bold (header)
_STYLES_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    f'<styleSheet xmlns="{_XL_NS}">'
    '<fonts count="2">'
    '<font><sz val="11"/><name val="Calibri"/></font>'
    '<font><b/><sz val="11"/><name val="Calibri"/></font>'
    '</fonts>'
    '<fills count="2">'
    '<fill><patternFill patternType="none"/></fill>'
    '<fill><patternFill patternType="gray125"/></fill>'
    '</fills>'
    '<borders count="1">'
    '<border><left/><right/><top/><bottom/><diagonal/></border>'
    '</borders>'
    '<cellStyleXfs count="1">'
    '<xf numFmtId="0" fontId="0" fillId="0" borderId="0"/>'
    '</cellStyleXfs>'
    '<cellXfs count="2">'
    '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
    '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0"/>'
    '</cellXfs>'
    '</styleSheet>')


def _col_letter(n: int) -> str:
    """0-based column index → Excel letter(s): 0→A, 25→Z, 26→AA …"""
    s = ''
    n += 1
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _xl_cell(col: int, row: int, value, bold: bool = False) -> str:
    """Return an <c> element for the given 0-based col, 1-based row."""
    ref = f'{_col_letter(col)}{row}'
    s   = ' s="1"' if bold else ''
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f'<c r="{ref}"{s}><v>{value}</v></c>'
    escaped = _sx.escape(str(value if value is not None else ''))
    return f'<c r="{ref}"{s} t="inlineStr"><is><t>{escaped}</t></is></c>'


def _xl_sheet(headers: list, rows: list) -> str:
    """Build a worksheet XML string."""
    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             f'<worksheet xmlns="{_XL_NS}"><sheetData>']
    # header row (row 1, bold)
    hcells = ''.join(_xl_cell(c, 1, h, bold=True) for c, h in enumerate(headers))
    lines.append(f'<row r="1">{hcells}</row>')
    # data rows
    for ri, row in enumerate(rows, 2):
        dcells = ''.join(_xl_cell(c, ri, v) for c, v in enumerate(row))
        lines.append(f'<row r="{ri}">{dcells}</row>')
    lines.append('</sheetData></worksheet>')
    return ''.join(lines)


def _xl_content_types(n_sheets: int) -> str:
    overrides = (
        f'<Override PartName="/xl/workbook.xml" ContentType="{_WB_TYPE}"/>'
        f'<Override PartName="/xl/styles.xml"   ContentType="{_ST_TYPE}"/>'
        + ''.join(
            f'<Override PartName="/xl/worksheets/sheet{i}.xml"'
            f' ContentType="{_WS_TYPE}"/>'
            for i in range(1, n_sheets + 1)))
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<Types xmlns="{_PKG_NS}">'
        '<Default Extension="rels"'
        ' ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        f'{overrides}</Types>')


def _xl_pkg_rels() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<Relationships xmlns="{_REL_NS}">'
        f'<Relationship Id="rId1" Type="{_WB_REL}"'
        ' Target="xl/workbook.xml"/>'
        '</Relationships>')


def _xl_workbook(sheet_names: list) -> str:
    sheets = ''.join(
        f'<sheet name="{_sx.escape(n)}" sheetId="{i}" r:id="rId{i}"/>'
        for i, n in enumerate(sheet_names, 1))
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
        ' xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f'<sheets>{sheets}</sheets></workbook>')


def _xl_wb_rels(n_sheets: int) -> str:
    rels = ''.join(
        f'<Relationship Id="rId{i}" Type="{_WS_REL}"'
        f' Target="worksheets/sheet{i}.xml"/>'
        for i in range(1, n_sheets + 1))
    rels += (f'<Relationship Id="rId{n_sheets+1}" Type="{_ST_REL}"'
             ' Target="styles.xml"/>')
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<Relationships xmlns="{_REL_NS}">{rels}</Relationships>')


def write_xlsx(path: str, scored: list, profile_summary: dict,
               report_title: str = 'kcommit Analysis Report') -> None:
    """Write an XLSX workbook to *path* using stdlib only — no openpyxl needed.

    Produces three sheets: Commits, Profile Summary, Profile Matrix.
    Compatible with Excel 2007+, LibreOffice Calc, Google Sheets.
    """
    sheets = [
        ('Commits',         COMMIT_COLS,  [_commit_row(c) for c in scored]),
        ('Profile Summary', SUMMARY_COLS, _summary_rows(profile_summary)),
        ('Profile Matrix',  MATRIX_COLS,  _matrix_rows(scored)),
    ]
    names = [s[0] for s in sheets]
    n     = len(sheets)

    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
        # MIME hint (must be first, uncompressed)
        zf.writestr(zipfile.ZipInfo('mimetype'), _MIME_XLSX)
        # package relationships + content types
        zf.writestr('[Content_Types].xml',  _xl_content_types(n))
        zf.writestr('_rels/.rels',           _xl_pkg_rels())
        # workbook
        zf.writestr('xl/workbook.xml',       _xl_workbook(names))
        zf.writestr('xl/_rels/workbook.xml.rels', _xl_wb_rels(n))
        zf.writestr('xl/styles.xml',         _STYLES_XML)
        # worksheets
        for i, (_, hdr, rows) in enumerate(sheets, 1):
            zf.writestr(f'xl/worksheets/sheet{i}.xml', _xl_sheet(hdr, rows))


# ═══════════════════════════════════════════════════════════════════════════════
# ODS — stdlib zipfile + XML, no external dependency (unchanged from v8.5)
# ═══════════════════════════════════════════════════════════════════════════════
_ODS_HEAD = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<office:document-content'
    ' xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"'
    ' xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0"'
    ' xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"'
    ' xmlns:fo="urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0"'
    ' xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0"'
    ' office:version="1.2">'
    '<office:automatic-styles>'
    '<style:style style:name="H" style:family="table-cell">'
    '<style:text-properties fo:font-weight="bold"/></style:style>'
    '</office:automatic-styles>'
    '<office:body><office:spreadsheet>')
_ODS_TAIL = '</office:spreadsheet></office:body></office:document-content>'
_ODS_MFST = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<manifest:manifest'
    ' xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0">'
    '<manifest:file-entry manifest:full-path="/"'
    ' manifest:media-type="application/vnd.oasis.opendocument.spreadsheet"/>'
    '<manifest:file-entry manifest:full-path="content.xml"'
    ' manifest:media-type="text/xml"/>'
    '</manifest:manifest>')
_ODS_MIME = 'application/vnd.oasis.opendocument.spreadsheet'


def _ods_cell(v, hdr=False):
    s = ' table:style-name="H"' if hdr else ''
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return (f'<table:table-cell{s} office:value-type="float"'
                f' office:value="{v}"><text:p>{v}</text:p></table:table-cell>')
    return (f'<table:table-cell{s} office:value-type="string">'
            f'<text:p>{_sx.escape(str(v))}</text:p></table:table-cell>')


def _ods_sheet(name, headers, rows):
    hrow  = ('<table:table-row>'
             + ''.join(_ods_cell(h, hdr=True) for h in headers)
             + '</table:table-row>')
    drows = ''.join(
        '<table:table-row>'
        + ''.join(_ods_cell(v) for v in row)
        + '</table:table-row>'
        for row in rows)
    return (f'<table:table table:name="{_sx.escape(name)}">'
            f'{hrow}{drows}</table:table>')


def write_ods(path: str, scored: list, profile_summary: dict,
              report_title: str = 'kcommit Analysis Report') -> None:
    """Write an ODS spreadsheet using stdlib zipfile only."""
    content = (
        _ODS_HEAD
        + _ods_sheet('Commits',         COMMIT_COLS,  [_commit_row(c) for c in scored])
        + _ods_sheet('Profile Summary', SUMMARY_COLS, _summary_rows(profile_summary))
        + _ods_sheet('Profile Matrix',  MATRIX_COLS,  _matrix_rows(scored))
        + _ODS_TAIL)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(zipfile.ZipInfo('mimetype'), _ODS_MIME)
        zf.writestr('META-INF/manifest.xml',     _ODS_MFST)
        zf.writestr('content.xml',               content.encode('utf-8'))
