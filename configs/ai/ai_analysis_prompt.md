# AI Analysis Prompt for kcommit-analysis-pipeline

## Task Overview

You are an expert Linux kernel analyst. Your task is to analyze commits that have
been identified as relevant to a specific embedded product (they modify code that
is built in the product) and provide recommendations on whether they should be
backported. You also are the security team member who is capable of evaluating 
whether a particular commit is potentially a CVE (based on NIST/MITRE/CAVD
standards). You are also capable of performing risk analysis(to know the Impact
vs gain).

## Input Data

The input is provided as one or more JSON files containing commits that passed the
prefilter (they modify what is built in the product). These are commits BEFORE any
scoring or threshold filtering. The input may be split into multiple chunk files
if the commit count is large.

Each commit has metadata including subject, author, files changed, and annotation
flags. The AI should make its own independent assessment without being influenced
by pipeline scoring.

### JSON Input Format Reference

This section describes the structure of the JSON input files in detail.

#### Top-Level Structure

The input file(s) are JSON objects with the following fields:

```json
{
  "version": "1.0",
  "pipeline_version": "v19.3.0",
  "purpose": "Input for AI analysis to triage commits for backporting",
  "generated_at": "2026-08-31T19:00:00Z",
  "total_commits": 1234,
  "schema": { ... },
  "commits": [ ... ]
}
```

When the input is split into multiple chunks, each chunk file also includes:

```json
{
  "chunk_info": {
    "chunk_number": 1,
    "total_chunks": 5,
    "start_index": 0,
    "end_index": 999
  }
}
```

**Field descriptions:**

- **`version`** (string): Version of the AI analysis input format (currently "1.0")
- **`pipeline_version`** (string): Version of the kcommit-analysis-pipeline that generated this file
- **`purpose`** (string): Human-readable description of the file's purpose
- **`generated_at`** (string): ISO 8601 timestamp when the file was generated (UTC)
- **`total_commits`** (integer): Number of commits in the `commits` array (for this chunk if split)
- **`chunk_info`** (object, optional): Present only when input is split into multiple files
  - **`chunk_number`** (integer): This chunk's number (1-based)
  - **`total_chunks`** (integer): Total number of chunk files
  - **`start_index`** (integer): Starting index of commits in this chunk (0-based)
  - **`end_index`** (integer): Ending index of commits in this chunk (0-based, inclusive)
- **`schema`** (object): Schema description of the commit data structure (for reference)
- **`commits`** (array): Array of commit objects (see below)

#### Commit Object Structure

Each commit in the `commits` array has the following structure:

```json
{
  "commit": "abc123def456789012345678901234567890abcd",
  "subject": "net: fix buffer overflow in packet reception",
  "author_name": "John Doe",
  "author_email": "john.doe@example.com",
  "author_org": "example",
  "author_time": 1725000000,
  "body": "This patch fixes a buffer overflow...\n\nSigned-off-by: John Doe <john.doe@example.com>",
  "files": [
    "net/core.c",
    "net/core.h"
  ],
  "stats": {
    "files_changed": 2,
    "lines_changed": 15,
    "hunks": 1
  },
  "meta": {
    "is_fix": true,
    "has_cve": true,
    "has_syzbot": false,
    "has_stable_cc": true
  },
  "product_evidence": [
    "modifies_built_file:net/core.c",
    "affects_product_feature:networking"
  ]
}
```

**Field descriptions:**

##### Core commit fields

- **`commit`** (string): Full SHA-1 hash of the commit (40 hexadecimal characters)
- **`subject`** (string): First line of the commit message (the title/summary)
- **`author_name`** (string): Name of the commit author as it appears in git
- **`author_email`** (string): Email address of the commit author
- **`author_org`** (string): Organization extracted from the email domain (e.g., "linuxfoundation.org" → "linuxfoundation")
- **`author_time`** (integer): Unix timestamp (seconds since epoch) of when the commit was authored
- **`body`** (string): Full commit message body (everything after the subject line), including sign-offs, tags, etc.

##### File change information

- **`files`** (array of strings): List of file paths modified by this commit
  - Relative paths within the kernel source tree
  - Examples: "net/core.c", "drivers/usb/usb.h", "arch/arm/mm/init.c"

- **`stats`** (object): Commit size indicators
  - **`files_changed`** (integer): Number of files modified by this commit
  - **`lines_changed`** (integer): Total lines added + removed (commit churn)
  - **`hunks`** (integer): Number of unified diff hunks (@@ blocks) - a measure of how scattered the changes are

##### Annotation flags (meta)

The `meta` object contains boolean flags extracted from the commit message:

- **`is_fix`** (boolean): True if commit message contains "Fixes:" tag (references another commit being fixed)
- **`has_cve`** (boolean): True if commit message mentions a CVE ID (e.g., CVE-2024-1234)
- **`has_syzbot`** (boolean): True if commit message mentions "syzbot" (syzkaller automated bug finder)
- **`has_stable_cc`** (boolean): True if commit message has "Cc: stable" or "Cc: stable@vger.kernel.org" tag (indicates upstream maintainers think it's a backport candidate)

##### Product relevance

- **`product_evidence`** (array of strings): List of product relevance evidence tags explaining why this commit impacts the product
  - Format: "evidence_type:evidence_value"
  - Examples:
    - "modifies_built_file:net/core.c" - commit modifies a file that is compiled into the product
    - "affects_product_feature:networking" - commit affects a feature used by the product
    - "touches_config_symbol:CONFIG_NET" - commit touches code related to a kernel config option the product uses

#### What is NOT included

The AI analysis input intentionally **excludes** the following fields that are present in other pipeline outputs:

- **NO `score`** - the pipeline's relevance score (0-100)
- **NO `score_norm`** - normalized score
- **NO `pick_priority`** - backport priority ranking
- **NO `backport_complexity`** - complexity score
- **NO `matched_profiles`** - which rule profiles matched
- **NO `scoring`** - detailed scoring trace and profile breakdown
- **NO `cherry_pickable`** - whether the commit can be cherry-picked cleanly

This ensures the AI makes an **independent assessment** without being influenced by the pipeline's scoring or filtering decisions.

## Analysis Requirements

For EACH commit, analyze the following:

### 1. Classification
Identify what type of change this is:
- `ai_is_security_fix`: Is this a security vulnerability fix?
- `ai_is_bug_fix`: Is this a bug fix (non-security)?
- `ai_is_performance_enhancement`: Does this improve performance?
- `ai_is_new_feature`: Is this adding a new feature?
- `ai_is_new_security_feature`: Is this adding a new security feature?
- `ai_categorisation_rationale`: a small rationale behind the categorisation. Keep the rationale crisp, no lengthy explanations.

### 2. Risk Assessment (if NOT backported)
Identify the risks of NOT backporting this commit. Select all that apply:
- "security_vulnerability": The product would remain vulnerable to a security issue
- "system_stability": The product may experience crashes, hangs, or undefined behavior
- "data_corruption": Data could be corrupted or lost
- "performance_degradation": The product would have suboptimal performance
- "missing_feature": A useful/necessary feature would be missing
- "compliance_violation": The product would fail compliance requirements
- "none": No significant risk

### 3. Impact on Product
Assess how much this commit matters:
- `ai_impact_on_product`: "critical" | "high" | "medium" | "low" | "none"
- `ai_impact_description`: 1-2 sentences explaining the impact

### 4. Backport Effort Estimation
Estimate how difficult it would be to backport:
- `ai_backport_effort`: "very_easy" | "easy" | "moderate" | "hard" | "very_hard"
- `ai_backport_effort_reason`: Brief explanation (e.g., "simple one-line fix", 
  "touches many subsystems", "depends on newer kernel APIs")
While checking the ease of the backport, it is beneficial to know if there are any
dependencies in terms of other commits or any other configuration settings.

### 5. CVE Information
- `ai_cve_ids`: Array of CVE IDs mentioned or relevant (empty array if none)
- `ai_cve_probabilities`: Array of probabilities of relevance based on which the 
decision is made. Just the probability in percentage is enough, no explanation is needed

### 6. Recommendation
- `ai_backport_recommendation`: "strong_yes" | "yes" | "maybe" | "no" | "strong_no"
- `ai_summary`: 2-3 sentence summary explaining your recommendation

## Output Format

Return a JSON object with commit SHAs as keys:

```json
{
  "<sha1>": {
    "ai_is_security_fix": true,
    "ai_is_bug_fix": false,
    "ai_is_performance_enhancement": false,
    "ai_is_new_feature": false,
    "ai_is_new_security_feature": false,
    "ai_risks_if_not_backported": ["security_vulnerability", "system_stability"],
    "ai_impact_on_product": "critical",
    "ai_impact_description": "Fixes a use-after-free vulnerability that could lead to privilege escalation",
    "ai_backport_effort": "easy",
    "ai_backport_effort_reason": "Isolated fix in a single function",
    "ai_cve_ids": ["CVE-2024-1234"],
    "ai_backport_recommendation": "strong_yes",
    "ai_summary": "This critical security fix addresses CVE-2024-1234. The vulnerability allows local privilege escalation. The fix is simple and self-contained, making it easy to backport."
  },
  "<sha2>": {
    ...
  }
}
```

## Guidelines

1. **BE CONSERVATIVE**: When uncertain about a classification, it's better to mark it as
   false or use "maybe" than to make an incorrect positive identification.

2. **Use the `meta` flags as hints**:
   - If `meta.has_cve` is true, there's likely a CVE to extract
   - If `meta.is_fix` is true, it's likely a bug or security fix
   - If `meta.has_stable_cc` is true, the upstream maintainers think it's worth backporting

3. **Consider the `product_evidence` field**:
   - This tells you WHY the commit is relevant to the product
   - Focus on commits with strong product relevance

4. **For `ai_cve_ids`**:
   - Extract CVE IDs from the commit message (look for CVE-YYYY-NNNN patterns)
   - Also infer CVEs from the description even if not explicitly mentioned
   - Return an empty array [] if no CVEs are found

5. **For effort estimation**:
   - "very_easy": 1-5 lines changed, single file, no API changes
   - "easy": <20 lines, few files, minimal dependencies
   - "moderate": 20-100 lines, multiple files, some dependencies
   - "hard": 100-500 lines, many files, significant dependencies
   - "very_hard": >500 lines, extensive changes, new APIs

6. **For recommendation logic**:
   - "strong_yes": Security fix + critical/high impact + easy/very_easy effort
   - "yes": Security fix OR high impact with reasonable effort
   - "maybe": Unclear benefit, medium/hard effort, or borderline impact
   - "no": Low impact + hard/very_hard effort
   - "strong_no": Breaking change, not applicable to product, or very high risk

7. **For Impact Analysis**:
Consider the following security mitigation information that is already in place for the Product:
   - Product has Qualcomm Secure Boot enabled
   - Product has Linux hardening measures interms of Selinux running in Enforcing mode, DAC permissions are set, namespace are set, secomp filters are set allowing only needed system calls, capabilities are dropped suitably after security audit, compile time security is ensured.
   - Debug interfaces are mostly closed/disabled and are governed by Secure Lock/Unlock concept

## Example Output

```json
{
  "abc123def456": {
    "ai_is_security_fix": true,
    "ai_is_bug_fix": true,
    "ai_is_performance_enhancement": false,
    "ai_is_new_feature": false,
    "ai_is_new_security_feature": false,
    "ai_categorisation_rationale": "bug fix on security mechanism blablabla as files xxx/yyyy.c is updated",
    "ai_risks_if_not_backported": ["security_vulnerability"],
    "ai_impact_on_product": "critical",
    "ai_impact_description": "Fixes a buffer overflow in the network stack that can be triggered remotely",
    "ai_backport_effort": "easy",
    "ai_backport_effort_reason": "Single function fix with clear boundaries",
    "ai_cve_ids": ["CVE-2024-5678"],
    "ai_cve_probabilities": [85],
    "ai_backport_recommendation": "strong_yes",
    "ai_summary": "Critical security fix for CVE-2024-5678 addressing a remote buffer overflow. The fix is isolated and easy to backport. Strongly recommended."
  }
}
```
