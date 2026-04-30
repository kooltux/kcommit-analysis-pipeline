# Reports

Stage 06 generates all output files under `<work_dir>/output/`.

## Output files

| File | Always | Description |
|------|--------|-------------|
| `relevant_commits.csv` | ✓ | Ranked commits above `templates.top_n` and `reports.min_score` |
| `relevant_commits.json` | ✓ | Same data as JSON (full commit dict per entry) |
| `profile_summary.json` | ✓ | Per-profile: commit count, total score, average score |
| `profile_matrix.csv` | ✓ | Per-commit × per-profile score breakdown |
| `report_stats.json` | ✓ | Pipeline run statistics (timings, counts, filter drop rate) |
| `summary.html` | ✓ | Interactive report (see below) |
| `relevant_commits.xlsx` | opt-in | Enable with `templates.xls_output: true` |
| `relevant_commits.ods` | opt-in | Enable with `templates.ods_output: true` |

## CSV / JSON columns

| Column | Description |
|--------|-------------|
| `rank` | Position in the ranked output (1 = highest score) |
| `score` | Combined score (sum of per-profile rule contributions) |
| `commit` | Full SHA |
| `subject` | Commit subject line |
| `author` | Author name |
| `date` | Author date (ISO-8601) |
| `files_changed` | Number of files touched |
| `matched_profiles` | Comma-separated list of profiles that contributed score > 0 |
| `product_evidence` | Evidence tags from product-map matching (informational) |
| `<profile>_score` | Per-profile score contribution (one column per active profile) |

### v8.11 column removals

The following columns from v8.4/v8.5 have been **removed**:
- `security_score` — was a direct keyword-based bonus, now informational metadata only
- `performance_score` — same
- `stable_score` — same
- `product_score` — same
- `symbol_match_score` — same

These signals are still computed and available in the JSON output under
`commit['scoring']['meta']` and displayed as flag badges in the HTML report,
but they do not contribute to `score`.

## HTML report (`summary.html`)

The report is self-contained (single HTML file, no external dependencies at
display time). It includes:

### Header
- Report title (from `templates.report_title`) with analysis date/time
- Dark/light mode toggle (system preference detected automatically)

### KPI cards
- Total commits in range
- Commits after filter (stage 04 drop count)
- Commits above threshold
- Unique profiles matched
- Commits with CVE tags

### Commit table
- Sortable columns (click header)
- Column-level search filters (per-column input row)
- Global search bar (subject + SHA)
- Score badges with 4-band coloring:
  - 🔴 **Critical** ≥ 300
  - 🟠 **High** ≥ 150
  - 🟡 **Medium** ≥ 50
  - ⬜ **Low** < 50
- Flag badges per commit: `CVE` / `Fix` / `Stable` / `Perf` (informational metadata)
- Profile tags (each matched profile shown as a teal chip)

### Profile summary table
Per-profile commit count, total score, average score, top commit SHA.

### Footer
Analysis date, pipeline version, config path.

## Customising the HTML report

Append custom CSS via `templates.css_override`:

```json
"templates": {
  "css_override": "${CONFIGDIR}/templates/custom.css"
}
```

The custom CSS is injected after the built-in styles, so any selector can be
overridden. The built-in design uses CSS custom properties (`--pri`, `--bg`,
etc.) defined in `:root` and `[data-theme=dark]` — override those variables
for global palette changes:

```css
:root {
  --pri: #7c3aed;   /* change accent to violet */
}
```
