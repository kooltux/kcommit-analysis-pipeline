"""Spreadsheet export for kcommit-analysis-pipeline.

Zero-dependency XLSX and ODS writers (stdlib zipfile + XML only).
Three sheets: Commits | Profile Summary | Profile Matrix.

XLSX fix: removed spurious mimetype entry (ODF-only concept);
          [Content_Types].xml is now the correct first entry.
ODS fix:  office:value-type set correctly on all numeric cells;
          manifest uses correct document MIME type.
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
    sc = c.get("scoring", {}) or {}
    return [c.get("_rank", ""), (c.get("commit") or "")[:12],
            c.get("subject", ""), c.get("author_name", ""), c.get("author_time", ""),
            c.get("score", 0) or 0,
            sc.get("security", 0) or 0, sc.get("performance", 0) or 0,
            sc.get("product", 0) or 0, sc.get("stable", 0) or 0,
            "; ".join(c.get("matched_profiles") or []),
            "; ".join(c.get("product_evidence") or [])]


def _summary_rows(ps):
    return [[n, d.get("count", 0), d.get("total_score", 0), d.get("avg_score", 0)]
            for n, d in sorted(ps.items(),
                               key=lambda kv: kv[1].get("count", 0), reverse=True)]


def _matrix_rows(scored):
    rows = []
    for c in scored:
        sc = c.get("scoring", {}) or {}
        for p in (c.get("matched_profiles") or []):
            rows.append([c.get("_rank", ""), (c.get("commit") or "")[:12],
                         c.get("subject", ""), p,
                         c.get("score", 0) or 0,
                         (sc.get("profiles") or {}).get(p, 0)])
    return rows

# ═══════════════════════════════════════════════════════════════════════════════
# XLSX
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

_STYLES_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<styleSheet xmlns="' + 'http://schemas.openxmlformats.org/spreadsheetml/2006/main' + '">'
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


def _col_letter(n):
    s = ''; n += 1
    while n:
        n, r = divmod(n - 1, 26); s = chr(65 + r) + s
    return s


def _xl_cell(col, row, value, bold=False):
    ref = f'{_col_letter(col)}{row}'; s = ' s="1"' if bold else ''
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f'<c r="{ref}"{s}><v>{value}</v></c>'
    escaped = _sx.escape(str(value if value is not None else ''))
    return f'<c r="{ref}"{s} t="inlineStr"><is><t>{escaped}</t></is></c>'


def _xl_sheet(headers, rows):
    parts = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
             '<sheetData>']
    parts.append('<row r="1">' + ''.join(_xl_cell(c,1,h,bold=True) for c,h in enumerate(headers)) + '</row>')
    for ri, row in enumerate(rows, 2):
        parts.append(f'<row r="{ri}">' + ''.join(_xl_cell(c,ri,v) for c,v in enumerate(row)) + '</row>')
    parts.append('</sheetData></worksheet>')
    return ''.join(parts)


def _xl_content_types(n):
    ov = (
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        + ''.join(f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' for i in range(1, n+1)))
    return ('<?xml version="1.0" encoding="UTF-8"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            f'{ov}</Types>')


def _xl_pkg_rels():
    return ('<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/workbook" Target="xl/workbook.xml"/>'
            '</Relationships>')


def _xl_workbook(names):
    sheets = ''.join(f'<sheet name="{_sx.escape(n)}" sheetId="{i}" r:id="rId{i}"/>' for i,n in enumerate(names,1))
    return ('<?xml version="1.0" encoding="UTF-8"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
            ' xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            f'<sheets>{sheets}</sheets></workbook>')


def _xl_wb_rels(n):
    rels = ''.join(
        f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>'
        for i in range(1, n+1))
    rels += f'<Relationship Id="rId{n+1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
    return ('<?xml version="1.0" encoding="UTF-8"?>'
            f'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">{rels}</Relationships>')


def write_xlsx(path, scored, profile_summary, report_title='kcommit Analysis Report'):
    """Write XLSX using stdlib only. No mimetype entry (XLSX is not ODF)."""
    sheets = [
        ('Commits',         COMMIT_COLS,  [_commit_row(c) for c in scored]),
        ('Profile Summary', SUMMARY_COLS, _summary_rows(profile_summary)),
        ('Profile Matrix',  MATRIX_COLS,  _matrix_rows(scored)),
    ]
    names = [s[0] for s in sheets]; n = len(sheets)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('[Content_Types].xml',       _xl_content_types(n))
        zf.writestr('_rels/.rels',               _xl_pkg_rels())
        zf.writestr('xl/workbook.xml',           _xl_workbook(names))
        zf.writestr('xl/_rels/workbook.xml.rels',_xl_wb_rels(n))
        zf.writestr('xl/styles.xml',             _STYLES_XML)
        for i, (_, headers, rows) in enumerate(sheets, 1):
            zf.writestr(f'xl/worksheets/sheet{i}.xml', _xl_sheet(headers, rows))


# ═══════════════════════════════════════════════════════════════════════════════
# ODS
# ═══════════════════════════════════════════════════════════════════════════════
_ODS_MIME   = 'application/vnd.oasis.opendocument.spreadsheet'
_ODS_NS_MAP = (
    'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
    'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" '
    'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
    'xmlns:fo="urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0" '
    'xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0" '
    'xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0"'
)


def _ods_cell(value):
    if isinstance(value, bool):
        return f'<table:table-cell office:value-type="string"><text:p>{_sx.escape(str(value))}</text:p></table:table-cell>'
    if isinstance(value, (int, float)):
        return f'<table:table-cell office:value-type="float" office:value="{value}"><text:p>{value}</text:p></table:table-cell>'
    return f'<table:table-cell office:value-type="string"><text:p>{_sx.escape(str(value if value is not None else ""))}</text:p></table:table-cell>'


def _ods_hcell(value):
    return f'<table:table-cell table:style-name="bold" office:value-type="string"><text:p>{_sx.escape(str(value))}</text:p></table:table-cell>'


def _ods_sheet(name, headers, rows):
    hrow = '<table:table-row>' + ''.join(_ods_hcell(h) for h in headers) + '</table:table-row>'
    drows = ''.join('<table:table-row>' + ''.join(_ods_cell(v) for v in row) + '</table:table-row>' for row in rows)
    return f'<table:table table:name="{_sx.escape(name)}">{hrow}{drows}</table:table>'


def _ods_content(sheets):
    styles = ('<office:automatic-styles>'
              '<style:style style:name="bold" style:family="table-cell">'
              '<style:text-properties fo:font-weight="bold"/>'
              '</style:style>'
              '</office:automatic-styles>')
    body = ''.join(_ods_sheet(n, h, r) for n, h, r in sheets)
    return ('<?xml version="1.0" encoding="UTF-8"?>'
            '<office:document-content ' + _ODS_NS_MAP + ' office:version="1.3">'
            + styles +
            '<office:body><office:spreadsheet>'
            + body +
            '</office:spreadsheet></office:body>'
            '</office:document-content>')


def _ods_manifest():
    return ('<?xml version="1.0" encoding="UTF-8"?>'
            '<manifest:manifest'
            ' xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0"'
            ' manifest:version="1.3">'
            f'<manifest:file-entry manifest:full-path="/" manifest:media-type="{_ODS_MIME}"/>'
            '<manifest:file-entry manifest:full-path="content.xml" manifest:media-type="text/xml"/>'
            '</manifest:manifest>')


def write_ods(path, scored, profile_summary, report_title='kcommit Analysis Report'):
    """Write ODS spreadsheet using stdlib only.
    mimetype entry is first, uncompressed (ODF spec requirement).
    """
    sheets = [
        ('Commits',         COMMIT_COLS,  [_commit_row(c) for c in scored]),
        ('Profile Summary', SUMMARY_COLS, _summary_rows(profile_summary)),
        ('Profile Matrix',  MATRIX_COLS,  _matrix_rows(scored)),
    ]
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
        mi = zipfile.ZipInfo('mimetype')
        mi.compress_type = zipfile.ZIP_STORED
        zf.writestr(mi, _ODS_MIME)
        zf.writestr('META-INF/manifest.xml', _ods_manifest())
        zf.writestr('content.xml',           _ods_content(sheets))
