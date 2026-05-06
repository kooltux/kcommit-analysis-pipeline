# Profiles and Rules

## Profiles

A **profile** defines a relevance axis for commits. Each profile has a
**weight** (0–100) set in `profiles.active` that scales how much its rule
matches contribute to the final commit score.

Profile files are JSON, one per profile name, placed in the directories
listed under `profiles.profiles_dirs` (default: `<CONFIGDIR>/profiles/`).

### Profile file format

```json
{
  "name":        "my_profile",
  "description": "Optional human-readable description",
  "rules": {
    "rule_set_x": { "weight": 80 },
    "rule_set_y": { "weight": 30 },
    "shared_rule": 50
  }
}
```

`rules` maps rule-set names to their weight for this profile. Weight can be
given as a plain integer or as an object with a `weight` key. Rule-set
directories are resolved from `rules.rules_dirs`.

### Scoring contribution

```
profile_score = min(sum(matching rule weights), 100) × profile_weight / 100
```

Rule points are capped at 100 before weight scaling.
The final commit score is the sum of all active profile scores.

## Rules

A **rule** is a named directory containing pattern files. Rules live under
`rules.rules_dirs` (default: `<CONFIGDIR>/rules/`). The directory name is
the rule key referenced in profile files.

### Rule directory structure

```
rule_set_x/
├── keywords_whitelist.txt
├── keywords_blacklist.txt
├── path_whitelist.txt
├── path_blacklist.txt
├── commit_whitelist.txt
└── commit_blacklist.txt
```

All files are optional. Any combination is valid; a rule with no matching
files scores 0 for every commit.

### Pattern files

| File | Effect |
|------|--------|
| `keywords_whitelist.txt` | Match against commit subject + body; hit adds `weight` |
| `keywords_blacklist.txt` | Match against subject; hit excludes commit from this profile |
| `path_whitelist.txt`     | Match against touched file paths; hit adds `weight` |
| `path_blacklist.txt`     | Match against touched paths; if ALL files match → pre-filter DROP |
| `commit_whitelist.txt`   | Exact or glob SHA; hit adds `weight` |
| `commit_blacklist.txt`   | Exact or glob SHA; hit excludes commit from this profile |

### Pattern syntax (one entry per line)

| Prefix | Meaning |
|--------|---------|
| *(none)* | Case-insensitive substring |
| `re:` | Python `re.search` regular expression |
| `*`, `?`, `[…]` | fnmatch glob |

Comments (`#`) and blank lines are ignored.

### Shared rules

A rule directory can be referenced by multiple profiles simultaneously.
`compiled_rules.json` (stage 00 output) stores each rule body only once and
references it by name from each profile that uses it.

## Pre-filter evaluation order (stage 04)

Lists from all active profiles are merged globally before evaluation:

1. SHA in `commit_whitelist` → **KEEP** (absolute — beats everything)
2. SHA in `commit_blacklist` → **DROP** (beaten only by whitelist)
3. ALL touched files in `path_blacklist` → **DROP**
4. ANY touched file in `path_whitelist` → **KEEP**
5. Kconfig/build-artifact coverage check → **DROP** if uncovered (opt-in)
6. ANY keyword in `keywords_whitelist` → **KEEP**
7. ANY keyword in `keywords_blacklist` → **DROP**
8. Default → **KEEP** (let scoring decide)
