# Profiles and Rules

## Profiles

A **profile** defines a high-level relevance axis (e.g. `security_fixes`,
`performance`). Each profile has a **weight** (0–100) set in the config that
scales how much its rule matches contribute to the final commit score.

Profile directories live under `<CONFIGDIR>/profiles/<profile_name>/` and
contain:
- `rules/` — rule files (see below)
- `path_whitelist`, `path_blacklist` — file-path patterns
- `commit_whitelist`, `commit_blacklist` — SHA lists
- `keywords_whitelist`, `keywords_blacklist` — text patterns
- `profile.json` — optional metadata (description, weight default)

### Scoring contribution

```
profile_score = min(sum(matching rule weights), 100) × profile_weight / 100
```

The per-profile score is capped at 100 rule points before weight scaling.
The final commit score is the sum of all profile scores.

## Rules

A **rule** is a named pattern set with a weight. Rules live in
`<profile>/rules/<rule_name>.json` (or `.yaml`).

Typical rule structure:
```json
{
  "weight": 30,
  "path_patterns":    ["drivers/net/**", "net/core/*.c"],
  "subject_patterns": ["re:CVE-\\d{4}-\\d+", "fix:", "security:"],
  "body_patterns":    ["Fixes:", "stable@"]
}
```

A rule **matches** a commit when:
- At least one `path_pattern` matches any touched file, **AND**
- At least one `subject_pattern` or `body_pattern` matches the commit text.

Both conditions must hold (if specified). An absent field means "always match".

### Pattern syntax

| Prefix | Meaning |
|---|---|
| *(none)* | Case-insensitive substring |
| `re:` | Python regular expression (re.search) |
| `glob:` | fnmatch glob (`*`, `?`, `**` for paths) |

### Shared rules

Rules can be shared across profiles by placing them in a `shared_rules/`
directory and referencing them by name in the profile. Shared rules avoid
duplication when the same pattern set is relevant to multiple profiles.

## Whitelist / blacklist files

Each list file contains one entry per line. Comments (`#`) and blank lines
are ignored. Pattern syntax (substring / `re:` / `glob:`) applies.

### Evaluation order (profile-level)

1. Commit SHA in `commit_whitelist` → KEEP (absolute)
2. Commit SHA in `commit_blacklist` → DROP
3. ALL touched files in `path_blacklist` → DROP
4. ANY touched file in `path_whitelist` → KEEP
5. Kconfig/build-artifact coverage check → DROP if uncovered
6. ANY keyword in `keywords_whitelist` → KEEP
7. ANY keyword in `keywords_blacklist` → DROP
8. Default → KEEP (let scoring decide)

Lists from all active profiles are **merged** before evaluation (global
pass/fail). A commit blocked by one profile's blacklist cannot be rescued
by another profile's whitelist for the same list type.
