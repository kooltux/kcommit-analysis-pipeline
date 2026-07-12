# kcommit-analysis-pipeline — HTML UI v2 Handoff

## Context

This is a continuation of UI work on the `kcommit-analysis-pipeline` project.

---

## What exists

### `configs/html.v1/` — V1 UI (do not modify)
The working v1 UI. Used by the build system today via `paths.templates_dir`
in the pipeline config. The Python report builder (`lib/html_report.py`)
assembles the report by:
1. Reading `configs/html.v1/report.html` as the shell template
2. Reading `configs/html.v1/summary.css` inlined into `__CSS__`
3. Globbing `configs/html.v1/js/summary_*.js` in sorted order, wrapping in an IIFE → `__JS__`
4. Injecting `window.__KC_UI__` JSON data → `__COMMITS_DATA__`

### `configs/html.v1/` — copy of v1 (archive, ignore)

### `configs/html/` — V2 UI (build here)
Empty except for this file. The build system will be pointed here via
`paths.templates_dir = configs/html` once v2 is ready.

---

## JS module structure (v1, replicate in v2)

Files are concatenated in filename order inside an IIFE. Each module is
a plain JS file — no imports, no bundler. All globals are shared within
the IIFE scope.

| File | Role |
|---|---|
| `summary_01_globals.js` | Dataset prep, `ROWS`, `COLS`, `filteredRows`, tab state |
| `summary_02_utils.js` | `esc()`, `fmtDate()`, `scorePill()`, `chips()`, `stageBadge()` |
| `summary_03_charts.js` | SVG score distribution chart |
| `summary_04_theme.js` | Light/dark theme toggle |
| `summary_05_panes.js` | Resize handles, collapse/expand left+right panes |
| `summary_06_topbar.js` | Top bar meta pills, subtitle |
| `summary_07_sidebar.js` | Left pane content (funnel, stats, profiles) |
| `summary_08_tabs.js` | Report tab switcher (Relevant / Filtered) |
| `summary_09_loader.js` | Table loader overlay (progress bar) |
| `summary_10_table.js` | Filter controls, sort, `rowHtml()`, `applyFilters()` |
| `summary_11_vtable.js` | **Virtual scroll** — the module being redesigned |
| `summary_12_bootstrap.js` | Boot sequence: buildHead → showLoader → renderRowsAsync |
| `summary_13_detail.js` | Right pane commit detail (Overview/Scoring/Files/Raw) |

In v2 a new `summary_14_vscroll.js` may or may not be needed depending
on whether the native scrollbar is sufficient.

---

## V1 virtual scroll — how it works (and why it broke)

`summary_11_vtable.js` in v1 uses:
- `tableEl.style.paddingTop/paddingBottom` as spacers to simulate full
  dataset height for the native scrollbar
- `tbody.innerHTML = parts.join('')` to replace the visible window
- `tableWrap` = `#kc-table-wrap`, a `div` with `overflow: auto`
- `<thead>` is `position: sticky; top: 0` inside `tableWrap`

**The known bug:** `tableEl.style.paddingTop` shifts the sticky `<thead>`
downward as the user scrolls — the "header slides" bug. This is why v18.6.2
tried to replace padding with spacer `<tr>` rows, which then caused
`scrollHeight` reflow instability and the ghost-thumb / scroll-ceiling bugs
that were never fully fixed.

**Root cause:** mixing sticky thead with virtual-scroll spacers in the same
scroll container is inherently fragile.

---

## V2 design goals

### Layout changes
- Top bar: slimmer; **report tabs live in the top bar** (not a separate strip)
- Left pane: **overlay drawer** (slides over centre, not pushing it)
  — collapsed = 0 width, no rail
- Right pane: stays as side column on desktop, overlay on mobile
- Centre pane: full width by default (left drawer hidden)

### Table changes (the critical part)
- **Thead is outside the scroll container** — rendered in a separate
  fixed-height div above the scroll host, columns aligned via
  `table-layout: fixed` + shared `<colgroup>` widths
- **Scroll host** = plain `<div id="kc-scroll-host">` with `overflow-y: scroll`
- **Spacers** = `<div id="kc-spacer-top">` and `<div id="kc-spacer-bot">`
  as direct children of the scroll host, height set by JS
- **Table** = `<table id="kc-table">` between the spacers, no thead,
  `table-layout: fixed`, `width: 100%`
- **Native scrollbar** — no custom scrollbar
- `scrollTop` maps 1:1 to data rows (no thead offset ever)
- `scrollHeight` = spacer-top + table + spacer-bot (stable, no reflow)

### Virtual scroll math (v2)
```
const top      = scrollHost.scrollTop;          // pure data offset
const viewH    = scrollHost.clientHeight;
const visStart = Math.floor(top / rowHeightPx);
const visEnd   = Math.ceil((top + viewH) / rowHeightPx);
const winStart = Math.max(0, visStart - OVERSCAN);
const winEnd   = Math.min(total, visEnd + OVERSCAN);
spacerTop.style.height = `${winStart * rowHeightPx}px`;
spacerBot.style.height = `${(total - winEnd) * rowHeightPx}px`;
tbody.innerHTML = rows.slice(winStart, winEnd).map(rowHtml).join('');
```

No rAF deferral needed for scrollbar sync — native scrollbar reads
`scrollHeight` which is stable because spacers are `<div>`s not `<tr>`s.

### Visual style
- Rounded cards in left pane
- Pill-style active tab indicator (not underline)
- Row hover: left-border accent instead of background tint
- Right detail panel: collapsible card sections instead of inner tabs
- Same CSS custom-property token system as v1 (full dark/light support)

---

## HTML template placeholders (same as v1)

```html
<style>__CSS__</style>
__COMMITS_DATA__   ← <script> tag with window.__KC_UI__ etc.
<script>__JS__</script>
```

Title: `__TITLE__`, subtitle: `__SUBTITLE__`

---

## Key DOM IDs that must be preserved (read by JS)

| ID | Role |
|---|---|
| `kc-title` | Report title (h1) |
| `kc-subtitle` | Subtitle span |
| `kc-topbar-pills` | Meta pills container |
| `kc-theme-btn` / `kc-theme-icon` | Theme toggle |
| `kc-pane-left` | Left pane |
| `kc-pane-mid` | Centre pane |
| `kc-pane-right` | Right pane |
| `kc-left-body` | Left pane scroll body |
| `kc-left-toggle` | Left collapse button |
| `kc-toolbar` | Toolbar bar |
| `kc-global-search` | Search input |
| `kc-clear-filters` | Clear button |
| `kc-export-csv` | Export button |
| `kc-live-count` | Row count span |
| `kc-table-wrap` | **V2: rename to `kc-scroll-host`** |
| `kc-table` | `<table>` |
| `kc-thead` | `<thead>` (now in separate div) |
| `kc-tbody` | `<tbody>` |
| `kc-no-match` | Empty state message |
| `kc-detail-body` | Right pane content |
| `kc-tab-overview` etc. | Detail tab panels |
| `kc-right-toggle` | Right collapse button |
| `kc-right-handle` | Resize handle |

**New in v2:**
| ID | Role |
|---|---|
| `kc-thead-wrap` | Fixed div containing the header table |
| `kc-scroll-host` | The scrollable div (replaces `kc-table-wrap`) |
| `kc-spacer-top` | Top spacer div |
| `kc-spacer-bot` | Bottom spacer div |

---

## Tests to keep passing

The test suite lives in `tests/test_html_report.py`. Key tests that touch
the virtual scroll JS:
- `test_summary_js_resetvirt_uses_sentinel` — checks `virtOffset = -1` in resetVirt()
- Various structure checks on the assembled JS

Run tests with: `pytest tests/test_html_report.py -v`

---

## Task

Build `configs/html/` as a complete templates directory:
1. Copy `summary_01` through `summary_10`, `summary_12`, `summary_13` unchanged from `configs/html/js/`
2. Rewrite `summary_11_vtable.js` with the v2 scroll architecture
3. Write `summary_14_vscroll.js` only if needed (likely not)
4. Write `report.html` with the v2 layout
5. Write `summary.css` with the v2 visual style

All five files must be written before running tests.
