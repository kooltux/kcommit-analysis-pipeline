"""Spreadsheet export for kcommit-analysis-pipeline.

v9.9 changes:
  - Removed legacy 'Security', 'Performance', 'Product', 'Stable' columns.
    These were per-category sub-scores from a pre-profile era. All outputs
    now use the canonical profile-based column layout.
  - COMMIT_COLS, _commit_row(), and all three sheet writers (XLSX, ODS, CSV)
    are now in sync: same columns, same order, same data.
  - write_xlsx(): fixed corrupt output — _xl_pkg_rels() was missing the
    leading XML declaration; [Content_Types].xml override for styles was
    using the wrong MIME type string (a cut-off literal).
  - ODS mimetype entry must be the first file in the ZIP and must use
    ZipInfo with compress_type=ZIP_STORED (required by ODS spec).

Column layout
─────────────
Commits        : Rank | SHA | Subject | Author | Date | Score | Profiles | Product Evidence
Profile Summary: Profile | Count | Total Score | Avg Score
Profile Matrix : Rank | SHA | Subject | Profile | Total Score | Profile Score
"""
import os
import xml.sax.saxutils as _sx
import zipfile

COMMIT_COLS  = ['Rank', 'SHA', 'Subject', 'Author', 'Date',
                'Score', 'Profiles', 'Product Evidence']
SUMMARY_COLS = ['Profile', 'Count', 'Total Score', 'Avg Score']
MATRIX_COLS  = ['Rank', 'SHA', 'Subject', 'Profile', 'Total Score', 'Profile Score']


# ── shared row builders ───────────────────────────────────────────────────────

def _commit_row(c):
    return [
        c.get('_rank', ''),
        (c.get('commit') or '')[:12],
        c.get('subject', ''),
        c.get('author_name', ''),
        c.get('author_time', ''),
        c.get('score', 0) or 0,
        '; '.join(c.get('matched_profiles') or []),
        '; '.join(c.get('product_evidence') or []),
    ]


def _summary_rows(ps):
    return [
        [n, d.get('count', 0), d.get('total_score', 0), round(d.get('avg_score', 0), 2)]
        for n, d in sorted(ps.items(),
                           key=lambda kv: kv[1].get('count', 0), reverse=True)
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


# ═══════════════════════════════════════════════════════════════════════════════
# XLSX — stdlib zipfile + XML, no external dependency
# ═══════════════════════════════════════════════════════════════════════════════
_XL_NS   = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
_REL_NS  = 'http://schemas.openxmlformats.org/package/2006/relationships'
_PKG_NS  = 'http://schemas.openxmlformats.org/package/2006/content-types'
_WB_TYPE = ('application/vnd.openxmlformats-officedocument'
            '.spreadsheetml.sheet.main+xml')
_WS_TYPE = ('application/vnd.openxmlformats-officedocument'
            '.spreadsheetml.worksheet+xml')
_ST_TYPE = ('application/vnd.openxmlformats-officedocument'
            '.spreadsheetml.styles+xml')
_WB_REL  = ('http://schemas.openxmlformats.org/officeDocument'
             '/2006/relationships/workbook')
_WS_REL  = ('http://schemas.openxmlformats.org/officeDocument'
             '/2006/relationships/worksheet')
_ST_REL  = ('http://schemas.openxmlformats.org/officeDocument'
             '/2006/relationships/styles')

_MIME_XLSX = ('application/vnd.openxmlformats-officedocument'
              '.spreadsheetml.sheet')

# Minimal styles: xf 0 = normal, xf 1 = bold (header)
_STYLES_XML = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
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
      '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/>'
    '</cellXfs>'
    '</styleSheet>'
)


def _col_letter(n: int) -> str:
    """0-based column index → Excel letter(s): 0→A, 25→Z, 26→AA …"""
    s = ''
    n += 1
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _xl_cell(col: int, row: int, value, bold: bool = False) -> str:
    ref = f'{_col_letter(col)}{row}'
    s   = ' s="1"' if bold else ''
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f'<c r="{ref}"{s}><v>{value}</v></c>'
    escaped = _sx.escape(str(value if value is not None else ''))
    return f'<c r="{ref}"{s} t="inlineStr"><is><t>{escaped}</t></is></c>'


def _xl_sheet(headers: list, rows: list) -> str:
    lines = [
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
        f'<worksheet xmlns="{_XL_NS}"><sheetData>',
    ]
    hcells = ''.join(_xl_cell(c, 1, h, bold=True) for c, h in enumerate(headers))
    lines.append(f'<row r="1">{hcells}</row>')
    for ri, row in enumerate(rows, 2):
        dcells = ''.join(_xl_cell(c, ri, v) for c, v in enumerate(row))
        lines.append(f'<row r="{ri}">{dcells}</row>')
    lines.append('</sheetData></worksheet>')
    return ''.join(lines)


def _xl_content_types(n_sheets: int) -> str:
    overrides = (
        f'<Override PartName="/xl/workbook.xml" ContentType="{_WB_TYPE}"/>'
        f'<Override PartName="/xl/styles.xml" ContentType="{_ST_TYPE}"/>'
        + ''.join(
            f'<Override PartName="/xl/worksheets/sheet{i}.xml"'
            f' ContentType="{_WS_TYPE}"/>'
            for i in range(1, n_sheets + 1)
        )
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<Types xmlns="{_PKG_NS}">'
        '<Default Extension="rels"'
        ' ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        f'{overrides}'
        '</Types>'
    )


def _xl_pkg_rels() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<Relationships xmlns="{_REL_NS}">'
        f'<Relationship Id="rId1" Type="{_WB_REL}" Target="xl/workbook.xml"/>'
        '</Relationships>'
    )


def _xl_workbook(sheet_names: list) -> str:
    sheets = ''.join(
        f'<sheet name="{_sx.escape(n)}" sheetId="{i}" r:id="rId{i}"/>'
        for i, n in enumerate(sheet_names, 1)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook'
        ' xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
        ' xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f'<sheets>{sheets}</sheets>'
        '</workbook>'
    )


def _xl_wb_rels(n_sheets: int) -> str:
    rels = ''.join(
        f'<Relationship Id="rId{i}" Type="{_WS_REL}"'
        f' Target="worksheets/sheet{i}.xml"/>'
        for i in range(1, n_sheets + 1)
    )
    rels += (
        f'<Relationship Id="rId{n_sheets + 1}" Type="{_ST_REL}"'
        ' Target="styles.xml"/>'
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<Relationships xmlns="{_REL_NS}">{rels}</Relationships>'
    )


def write_xlsx(path: str, scored: list, profile_summary: dict,
               report_title: str = 'kcommit Analysis Report') -> None:
    """Write a valid XLSX workbook using stdlib zipfile only.

    Three sheets: Commits | Profile Summary | Profile Matrix.
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
        zf.writestr('[Content_Types].xml',       _xl_content_types(n))
        zf.writestr('_rels/.rels',                _xl_pkg_rels())
        zf.writestr('xl/workbook.xml',            _xl_workbook(names))
        zf.writestr('xl/_rels/workbook.xml.rels', _xl_wb_rels(n))
        zf.writestr('xl/styles.xml',              _STYLES_XML)
        for i, (_, hdr, rows) in enumerate(sheets, 1):
            zf.writestr(f'xl/worksheets/sheet{i}.xml', _xl_sheet(hdr, rows))


# ═══════════════════════════════════════════════════════════════════════════════
# ODS — stdlib zipfile + XML, no external dependency
# ═══════════════════════════════════════════════════════════════════════════════
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
_ODS_MFST = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<manifest:manifest'
    ' xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0"'
    ' manifest:version="1.2">'
    '<manifest:file-entry manifest:full-path="/"'
    ' manifest:media-type="application/vnd.oasis.opendocument.spreadsheet"/>'
    '<manifest:file-entry manifest:full-path="content.xml"'
    ' manifest:media-type="text/xml"/>'
    '</manifest:manifest>'
)
_ODS_MIME = 'application/vnd.oasis.opendocument.spreadsheet'


def _ods_cell(v, hdr=False):
    s = ' table:style-name="H"' if hdr else ''
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return (
            f'<table:table-cell{s} office:value-type="float"'
            f' office:value="{v}"><text:p>{v}</text:p></table:table-cell>'
        )
    return (
        f'<table:table-cell{s} office:value-type="string">'
        f'<text:p>{_sx.escape(str(v if v is not None else ""))}</text:p>'
        f'</table:table-cell>'
    )


def _ods_sheet(name, headers, rows):
    hrow  = ('<table:table-row>'
             + ''.join(_ods_cell(h, hdr=True) for h in headers)
             + '</table:table-row>')
    drows = ''.join(
        '<table:table-row>'
        + ''.join(_ods_cell(v) for v in row)
        + '</table:table-row>'
        for row in rows
    )
    return (
        f'<table:table table:name="{_sx.escape(name)}">'
        f'{hrow}{drows}</table:table>'
    )


def write_ods(path: str, scored: list, profile_summary: dict,
              report_title: str = 'kcommit Analysis Report') -> None:
    """Write a valid ODS spreadsheet using stdlib zipfile only.

    The mimetype entry must be first and uncompressed (ODS spec §3.3).
    Three sheets: Commits | Profile Summary | Profile Matrix.
    """
    content = (
        _ODS_HEAD
        + _ods_sheet('Commits',         COMMIT_COLS,  [_commit_row(c) for c in scored])
        + _ods_sheet('Profile Summary', SUMMARY_COLS, _summary_rows(profile_summary))
        + _ods_sheet('Profile Matrix',  MATRIX_COLS,  _matrix_rows(scored))
        + _ODS_TAIL
    ).encode('utf-8')

    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
        # mimetype MUST be first entry and MUST be uncompressed (stored)
        mi = zipfile.ZipInfo('mimetype')
        mi.compress_type = zipfile.ZIP_STORED
        zf.writestr(mi, _ODS_MIME)
        zf.writestr('META-INF/manifest.xml', _ODS_MFST)
        zf.writestr('content.xml', content)
