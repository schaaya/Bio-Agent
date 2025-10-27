# Biomedical SQL Domain Knowledge for Gene Expression Database

This document contains best practices, patterns, and biological context for querying the bio_gene_expression database. Each section is designed to be independently retrievable for semantic search.

---

## ⚠️ CRITICAL: Performance and Table Selection Rules

### Performance Rules (MUST FOLLOW):
1. **NEVER query gene_expression without specific gene filters** - this table has millions of rows
2. **NEVER return >1000 rows without aggregation** - always use GROUP BY or LIMIT
3. **ALWAYS use gene_statistics for simple "show/compare expression" queries** - it's pre-aggregated
4. **ALWAYS add LIMIT clause** when querying raw samples from gene_expression

### Penalties for Rule Violations:
- Query returning >10K rows → Query will be rejected (confidence < 75%)
- Using gene_expression for simple group comparisons (Tumor vs Normal) → Query will be rejected
- No filters on gene_expression → Query will be rejected

---

## Table Selection: When to Use gene_statistics vs gene_expression

### Context
The bio_gene_expression database has two tables for expression data:
- `gene_expression`: Raw TPM values for every gene in every sample (millions of rows)
- `gene_statistics`: Precomputed aggregated statistics (mean, median, SD) by group (thousands of rows)

### 🚨 CRITICAL EXCEPTIONS: When You MUST Use gene_expression

#### Exception 1: Visualization Queries (Box Plots, Scatter Plots, Distributions)

**When the query asks for VISUALIZATIONS showing DISTRIBUTIONS, you MUST use gene_expression:**
- "Plot EGFR as box plots"
- "Show box plots of TP53 across tissues"
- "Visualize EGFR distribution"
- "Plot expression as box plots: one column for normal, one for tumor, one for cell lines"

**Why:** Box plots and distribution visualizations need RAW individual sample values to show quartiles, outliers, and spread. Aggregated statistics (mean/median from gene_statistics) cannot create meaningful box plots.

**Required pattern for visualization queries:**
```sql
-- For human tissues (Normal or Tumor)
SELECT g.gene_name, htm.tissue_type, ge.tpm_value, ge.sample_id
FROM gene_expression ge
JOIN genes g ON ge.gene_id = g.gene_id
JOIN samples s ON ge.sample_id = s.sample_id
JOIN human_tissue_metadata htm ON s.sample_id = htm.sample_id
WHERE g.gene_name = 'EGFR'
  AND htm.tissue_type = 'Normal'  -- or 'Tumor'
  AND ge.dataset_source = 'zhang_2016'

-- For cell lines
SELECT clm.cell_line_name, ge.tpm_value
FROM gene_expression ge
JOIN genes g ON ge.gene_id = g.gene_id
JOIN cell_line_metadata clm ON ge.sample_id = clm.sample_id
WHERE g.gene_name = 'EGFR'
  AND ge.dataset_source = 'vandersteen_fl3c'
```

#### Exception 2: Mutation-Stratified Queries

**When the query involves mutation status filtering, you MUST use gene_expression:**
- "EGFR expression in KRAS-mutant cells"
- "Show TP53 in EGFR-mutant cell lines"
- "Compare EGFR between different KRAS mutations"
- "Expression in p.G12D mutants"

**Why:** The `gene_statistics` table only has `sample_group` column (Tumor/Normal/Cell line). It does NOT have `sample_id`, so you CANNOT join with `cell_line_metadata` to filter by mutation status (EGFR_status, KRAS_status, TP53_status).

**Required pattern for mutation-stratified queries:**
```sql
SELECT
  g.gene_name,
  clm.KRAS_status,  -- or EGFR_status, TP53_status
  AVG(ge.tpm_value) AS mean_expression,
  COUNT(*) AS n_samples
FROM gene_expression ge
JOIN genes g ON ge.gene_id = g.gene_id
JOIN samples s ON ge.sample_id = s.sample_id
JOIN cell_line_metadata clm ON s.sample_id = clm.sample_id  -- ✅ Requires sample_id
WHERE g.gene_name = 'EGFR'
  AND clm.KRAS_status NOT IN ('WT', 'Unknown', '')  -- Mutation filtering
GROUP BY g.gene_name, clm.KRAS_status
```

### Best Practice for Non-Mutation Queries
**Use gene_statistics when the query needs:**
- Mean expression levels
- Median expression levels
- Average expression
- Summary statistics
- **Simple group-level comparisons (Tumor vs Normal, Cell line vs Tumor)**
- **NO mutation status filtering (EGFR_status, KRAS_status, TP53_status)**

**Use gene_expression when the query needs:**
- **Mutation-stratified analysis (REQUIRED - see exception above)**
- Individual sample values
- Raw TPM measurements
- Sample-level filtering
- Custom aggregations not available in gene_statistics

### Critical Pattern Recognition

Questions with these phrases MUST use gene_expression:
- **"plot as box plots" / "box plot" / "box plots"** → Use gene_expression (visualization)
- **"visualize distribution" / "show distribution"** → Use gene_expression (visualization)
- **"scatter plot" / "plot expression"** → Use gene_expression (visualization)
- "EGFR in KRAS-mutant cells" → Use gene_expression (mutation filtering)
- "TP53 in p.G12D mutants" → Use gene_expression (mutation filtering)
- "Compare between EGFR mutations" → Use gene_expression (mutation filtering)
- "[gene] levels in mutant cells" → Use gene_expression (mutation filtering)

Questions with these phrases use gene_statistics (UNLESS they mention box plots/visualizations or mutations):
- "Show [gene] expression in tumor vs normal" → Use gene_statistics (if no box plot)
- "Compare [gene] between tumor and normal" → Use gene_statistics (if no box plot)
- "TP53 expression tumor vs normal" → Use gene_statistics (if no box plot)
- "[gene] levels in cancer vs healthy" → Use gene_statistics (if no box plot)

DO NOT return raw sample data for simple group comparisons (Tumor vs Normal)!

### Example
Question: "What is the average TP53 expression in tumor vs normal?"
✅ USE: `gene_statistics` (mean_tpm is precomputed)
❌ DON'T USE: `gene_expression` with AVG() (slow, redundant)

SQL:
```sql
SELECT g.gene_name, gs.sample_group, gs.mean_tpm, gs.median_tpm, gs.n_samples
FROM gene_statistics gs
JOIN genes g ON gs.gene_id = g.gene_id
WHERE g.gene_name = 'TP53' AND gs.sample_group IN ('Tumor', 'Normal')
```

Question: "Show TP53 expression in tumor vs normal"
✅ CORRECT - Use gene_statistics:
```sql
SELECT
  g.gene_name,
  gs.sample_group,
  gs.mean_tpm,
  gs.median_tpm,
  gs.std_dev_tpm,
  gs.min_tpm,
  gs.max_tpm,
  gs.n_samples
FROM gene_statistics gs
JOIN genes g ON gs.gene_id = g.gene_id
WHERE g.gene_name = 'TP53'
  AND gs.sample_group IN ('Tumor', 'Normal')
  AND gs.dataset_source = 'zhang_2016'
```

❌ INCORRECT - Do NOT return raw samples:
```sql
SELECT g.gene_name, htm.tissue_type, ge.tpm_value, ge.sample_id
FROM gene_expression ge
JOIN genes g ON ge.gene_id = g.gene_id
-- This returns 62 rows of raw data, not summary statistics!
```

---

## Table Selection: When to Use gene_comparison for Fold Change

### Context
The `gene_comparison` table contains precomputed fold changes between groups (e.g., Tumor vs Normal).

### Best Practice
**Use gene_comparison when the query asks about:**
- Fold change
- Log2 fold change
- Upregulated genes
- Downregulated genes
- Differentially expressed genes
- Genes with fold change > threshold

**Don't compute fold change manually** when it's already in gene_comparison.

### ⚠️ IMPORTANT: Fallback Strategy if gene_comparison is Empty
If gene_comparison table returns 0 rows or doesn't exist:
1. **Compute fold change from gene_statistics** using:
   - `fold_change = tumor_mean / normal_mean`
   - `log2_fold_change = LOG(fold_change) / LOG(2)` (SQLite syntax)
2. **Join gene_statistics twice**:
   - Once for Tumor group
   - Once for Normal group
3. **Filter for biological significance**:
   - `tumor_mean > normal_mean` (for upregulated)
   - `tumor_mean > 1.0` (must be expressed)
   - `normal_mean > 0.1` (filter noise)

### Example (Primary Approach)
Question: "Which genes are upregulated in tumor with log2FC > 1?"

SQL:
```sql
SELECT g.gene_name, gc.log2_fold_change, gc.fold_change, gc.p_value
FROM gene_comparison gc
JOIN genes g ON gc.gene_id = g.gene_id
WHERE gc.comparison_type = 'Tumor_vs_Normal'
  AND gc.log2_fold_change > 1
ORDER BY gc.log2_fold_change DESC
LIMIT 20
```

### Example (Fallback if gene_comparison is empty)
```sql
SELECT
  g.gene_name,
  tumor.mean_tpm AS tumor_mean,
  normal.mean_tpm AS normal_mean,
  tumor.mean_tpm / normal.mean_tpm AS fold_change,
  LOG(tumor.mean_tpm / normal.mean_tpm) / LOG(2) AS log2_fold_change
FROM genes g
JOIN gene_statistics tumor ON g.gene_id = tumor.gene_id
  AND tumor.sample_group = 'Tumor'
JOIN gene_statistics normal ON g.gene_id = normal.gene_id
  AND normal.sample_group = 'Normal'
WHERE tumor.mean_tpm > normal.mean_tpm
  AND LOG(tumor.mean_tpm / normal.mean_tpm) / LOG(2) > 1
  AND tumor.mean_tpm > 1.0
ORDER BY log2_fold_change DESC
LIMIT 20
```

---

## Comprehensive Differential Expression Analysis Pattern

### Context
When users ask for "differential expression analysis" they typically want complete statistics, not just fold change.

### What to Include
A comprehensive differential expression query should provide:
1. Mean/Median TPM for both groups (from gene_statistics)
2. Standard deviation and range (from gene_statistics)
3. Sample counts (n_samples from gene_statistics)
4. Fold change and log2FC (from gene_comparison)

### Pattern
```sql
SELECT
  g.gene_name,
  gs.sample_group,
  gs.mean_tpm,
  gs.median_tpm,
  gs.std_dev_tpm,
  gs.min_tpm,
  gs.max_tpm,
  gs.n_samples,
  gc.log2_fold_change,
  gc.fold_change
FROM gene_statistics gs
JOIN genes g ON gs.gene_id = g.gene_id
LEFT JOIN gene_comparison gc ON g.gene_id = gc.gene_id
  AND gc.comparison_type = 'Tumor_vs_Normal'
WHERE g.gene_name = 'TP53'
  AND gs.sample_group IN ('Tumor', 'Normal')
  AND gs.dataset_source = 'zhang_2016'
ORDER BY CASE WHEN gs.sample_group = 'Tumor' THEN 1 ELSE 2 END
```

### Why This Pattern Works
- Single query provides all data for publication-quality analysis
- LEFT JOIN on gene_comparison ensures query works even if fold change not computed
- ORDER BY ensures Tumor appears first in results
- Filters to zhang_2016 for human tissue data

---

## Tumor vs Normal Analysis: Understanding Data Relationships

### Context
Tumor vs normal comparisons require linking gene_expression to tissue classification via multiple tables.

### Table Relationships
```
gene_expression (TPM values)
  ↓ JOIN genes (get gene_name)
  ↓ JOIN samples (bridge table)
  ↓ JOIN human_tissue_metadata (get tissue_type: Tumor/Normal)
```

### Key Fields
- `human_tissue_metadata.tissue_type`: Contains 'Tumor' or 'Normal' classification
- `samples.sample_type`: Must be 'human_tissue' (not 'cell_line')
- `samples.dataset_source`: Filter to 'zhang_2016' for human patient data

### Example
Question: "Show TP53 expression in tumor samples"

SQL:
```sql
SELECT g.gene_name, htm.tissue_type, ge.tpm_value, ge.sample_id
FROM gene_expression ge
JOIN genes g ON ge.gene_id = g.gene_id
JOIN samples s ON ge.sample_id = s.sample_id
JOIN human_tissue_metadata htm ON s.sample_id = htm.sample_id
WHERE g.gene_name = 'TP53'
  AND htm.tissue_type = 'Tumor'
```

---

## Mutation-Stratified Analysis: EGFR, TP53, KRAS

### Context
Cell lines have mutation profiles that affect gene expression. Mutation-stratified analysis compares expression between wildtype (WT) and mutant genotypes.

### Table Relationships
```
gene_expression (TPM values)
  ↓ JOIN genes (get gene_name)
  ↓ JOIN samples (bridge table, filter sample_type='cell_line')
  ↓ JOIN cell_line_metadata (get EGFR_status, TP53_status, KRAS_status)
```

### Key Fields
- `cell_line_metadata.TP53_status`: 'WT' or mutation notation (e.g., 'p.R273H')
- `cell_line_metadata.EGFR_status`: 'WT' or mutation (e.g., 'p.L858R')
- `cell_line_metadata.KRAS_status`: 'WT' or mutation (e.g., 'p.G12C')
- `samples.sample_type`: Must be 'cell_line' (not 'human_tissue')

### Example
Question: "Expression of EGFR in TP53-mutant vs wildtype cell lines"

SQL:
```sql
SELECT
  g.gene_name,
  clm.TP53_status,
  AVG(ge.tpm_value) AS mean_expression,
  MIN(ge.tpm_value) AS min_expression,
  MAX(ge.tpm_value) AS max_expression,
  COUNT(*) AS n_samples
FROM gene_expression ge
JOIN genes g ON ge.gene_id = g.gene_id
JOIN samples s ON ge.sample_id = s.sample_id
JOIN cell_line_metadata clm ON s.sample_id = clm.sample_id
WHERE g.gene_name = 'EGFR'
  AND s.sample_type = 'cell_line'
  AND clm.TP53_status IS NOT NULL
GROUP BY g.gene_name, clm.TP53_status
```

**Note**: SQLite does not support STDDEV(). Use MIN/MAX for range instead, or calculate manually if needed.

---

## Gene Name Best Practice: Always Include gene_name in Results

### Context
The database uses gene_id as the primary key for joins, but users think in gene symbols (TP53, EGFR, KRAS).

### Best Practice
**Always include genes.gene_name in SELECT clause** when returning results to users.

### Why
- Users don't recognize Ensembl IDs (ENSG00000141510)
- Gene symbols (TP53) are the standard in scientific literature
- Results without gene names are not interpretable

### Example
❌ BAD:
```sql
SELECT ge.gene_id, AVG(ge.tpm_value)
FROM gene_expression ge
GROUP BY ge.gene_id
```
User sees: "ENSG00000141510: 45.2" (uninterpretable)

✅ GOOD:
```sql
SELECT g.gene_name, AVG(ge.tpm_value) AS mean_tpm
FROM gene_expression ge
JOIN genes g ON ge.gene_id = g.gene_id
GROUP BY g.gene_name
```
User sees: "TP53: 45.2" (clear and interpretable)

---

## Biological Context: TPM Interpretation

### TPM (Transcripts Per Million)
TPM is a normalized measure of gene expression that accounts for gene length and sequencing depth.

### Interpretation Guidelines
- **TPM < 1**: Not detected or very low (gene may not be expressed)
- **TPM 1-10**: Detected but low expression
- **TPM 10-100**: Moderate expression (typical for many genes)
- **TPM 100-1000**: High expression
- **TPM > 1000**: Very high expression (housekeeping genes, abundant proteins)

### Common Thresholds
- **Detection threshold**: TPM >= 1 (gene is "detected")
- **Expression threshold**: TPM >= 10 (gene is "expressed")
- **High expression**: TPM >= 100

### Example Usage
Question: "How many samples have high TP53 expression (TPM > 100)?"

SQL:
```sql
SELECT COUNT(*) AS n_samples_high_expression
FROM gene_expression ge
JOIN genes g ON ge.gene_id = g.gene_id
WHERE g.gene_name = 'TP53' AND ge.tpm_value > 100
```

---

## Biological Context: Log2 Fold Change Interpretation

### Log2 Fold Change
Log2FC is the preferred metric for differential expression because it is symmetric around zero.

### Interpretation Guidelines
- **log2FC = 0**: No change
- **log2FC = +1**: 2-fold upregulation (2x higher in group 1)
- **log2FC = -1**: 2-fold downregulation (2x lower in group 1)
- **log2FC = +2**: 4-fold upregulation
- **log2FC = -2**: 4-fold downregulation
- **|log2FC| >= 1**: Typically considered biologically significant (>= 2-fold change)
- **|log2FC| >= 2**: Highly significant (>= 4-fold change)

### Common Thresholds
- **Minimal change**: |log2FC| < 0.5 (< 1.4-fold)
- **Moderate change**: 0.5 <= |log2FC| < 1 (1.4 to 2-fold)
- **Significant change**: |log2FC| >= 1 (>= 2-fold) ← most common threshold
- **Highly significant**: |log2FC| >= 2 (>= 4-fold)

### Example Usage
Question: "Genes with at least 2-fold upregulation in tumor"

SQL:
```sql
SELECT g.gene_name, gc.log2_fold_change, gc.fold_change
FROM gene_comparison gc
JOIN genes g ON gc.gene_id = g.gene_id
WHERE gc.comparison_type = 'Tumor_vs_Normal'
  AND gc.log2_fold_change >= 1  -- 2-fold or higher
ORDER BY gc.log2_fold_change DESC
```

---

## Dataset Filtering: Zhang 2016 vs VanDerSteen FL3C

### Two Datasets in Database
1. **zhang_2016**: Human patient tissue samples (tumor/normal pairs)
2. **vandersteen_fl3c**: Lung cancer cell lines

### 🚨 CRITICAL: ALWAYS Filter by Dataset Source
**NEVER query without dataset_source filter!** This is MANDATORY:

- For **human tissue analysis** (Normal, Tumor): `dataset_source = 'zhang_2016'`
- For **cell line analysis**: `dataset_source = 'vandersteen_fl3c'`
- For **combined Tumor + Normal + Cell lines**: Use BOTH filters with OR/UNION

### Pattern Recognition for Dataset Selection
**If the query mentions ANY of these, use zhang_2016:**
- "normal tissue", "tumor tissue", "human tissue"
- "patient samples", "tumor vs normal"
- "cancer vs healthy"

**If the query mentions ANY of these, use vandersteen_fl3c:**
- "cell line", "cell lines", "in vitro"
- "cultured cells", "lung cancer cell lines"

**If the query wants BOTH tissues AND cell lines together:**
```sql
-- Query tissues (Normal, Tumor)
WHERE gs.sample_group IN ('Normal', 'Tumor') AND gs.dataset_source = 'zhang_2016'
UNION
-- Query cell lines
WHERE gs.sample_group = 'Cell line' AND gs.dataset_source = 'vandersteen_fl3c'
```

### Where Dataset Appears
- `gene_expression.dataset_source`
- `gene_statistics.dataset_source`
- `gene_comparison.dataset_source`
- `samples.dataset_source`

### Example
Question: "TP53 expression in human tissues only"

SQL:
```sql
SELECT g.gene_name, gs.sample_group, gs.mean_tpm
FROM gene_statistics gs
JOIN genes g ON gs.gene_id = g.gene_id
WHERE g.gene_name = 'TP53'
  AND gs.dataset_source = 'zhang_2016'  -- Human tissues only
```

---

## Patient Demographics: Age, Gender, Smoking Status

### Context
Human tissue samples have associated patient demographics in `human_tissue_metadata`.

### Available Demographics
- `patient_age`: Age in years
- `patient_gender`: 'Male', 'Female', or 'Unknown'
- `smoking_status`: 'Never', 'Former', 'Current', or 'Unknown'

### Use Cases
- Age-stratified analysis (e.g., young vs old patients)
- Sex-specific expression patterns
- Smoking-related gene expression changes

### Example
Question: "TP53 expression in never-smokers vs current smokers"

SQL:
```sql
SELECT
  g.gene_name,
  htm.smoking_status,
  AVG(ge.tpm_value) AS mean_expression,
  COUNT(*) AS n_samples
FROM gene_expression ge
JOIN genes g ON ge.gene_id = g.gene_id
JOIN samples s ON ge.sample_id = s.sample_id
JOIN human_tissue_metadata htm ON s.sample_id = htm.sample_id
WHERE g.gene_name = 'TP53'
  AND htm.smoking_status IN ('Never', 'Current')
GROUP BY g.gene_name, htm.smoking_status
```

---

## Sample Counts: Always Report n_samples

### Context
Statistical analyses need sample sizes for interpretation.

### Best Practice
**Always include sample counts** when reporting aggregate statistics.

### Why
- Sample size affects statistical power
- Small n (<5) may not be reliable
- Transparency in scientific reporting

### Where to Get n_samples
- `gene_statistics.n_samples`: Precomputed counts
- `COUNT(*)` in aggregations: Computed on-the-fly

### Example
```sql
SELECT
  g.gene_name,
  gs.sample_group,
  gs.mean_tpm,
  gs.n_samples  -- Always include!
FROM gene_statistics gs
JOIN genes g ON gs.gene_id = g.gene_id
WHERE g.gene_name = 'TP53'
```

Result interpretation: "TP53 mean TPM = 45.2 in Tumor (n=50)" is much more informative than "TP53 mean TPM = 45.2 in Tumor"

---

## Few-Shot Example 1: Comprehensive Tumor vs Normal Analysis

### Question
"Differential expression analysis of TP53 between tumor and normal tissues"

### Expected Output
Complete statistics with mean, median, SD, range, sample counts, and fold change.

### SQL Query
```sql
SELECT
  g.gene_name,
  gs.sample_group,
  gs.mean_tpm,
  gs.median_tpm,
  gs.std_dev_tpm,
  gs.min_tpm,
  gs.max_tpm,
  gs.n_samples,
  gc.log2_fold_change,
  gc.fold_change
FROM gene_statistics gs
JOIN genes g ON gs.gene_id = g.gene_id
LEFT JOIN gene_comparison gc ON g.gene_id = gc.gene_id
  AND gc.comparison_type = 'Tumor_vs_Normal'
WHERE g.gene_name = 'TP53'
  AND gs.sample_group IN ('Tumor', 'Normal')
  AND gs.dataset_source = 'zhang_2016'
ORDER BY CASE WHEN gs.sample_group = 'Tumor' THEN 1 ELSE 2 END
```

### Reasoning
- Uses `gene_statistics` for precomputed aggregates (fast)
- LEFT JOIN `gene_comparison` for fold change
- Filters to human data (`zhang_2016`)
- Orders Tumor first for readability
- Single query provides all data for publication-quality analysis

---

## Few-Shot Example 2: Top Upregulated Genes

### Question
"Which genes are most upregulated in tumor compared to normal?"

### Expected Output
List of genes ranked by fold change.

### SQL Query
```sql
-- Compute fold change from gene_statistics on-the-fly
-- Note: SQLite doesn't support LOG() function, so we only calculate fold_change
SELECT
  g.gene_name,
  tumor.mean_tpm AS tumor_mean,
  normal.mean_tpm AS normal_mean,
  CASE
    WHEN normal.mean_tpm > 0 THEN tumor.mean_tpm / normal.mean_tpm
    ELSE NULL
  END AS fold_change,
  tumor.n_samples AS tumor_n,
  normal.n_samples AS normal_n
FROM genes g
JOIN gene_statistics tumor ON g.gene_id = tumor.gene_id
  AND tumor.sample_group = 'Tumor'
  AND tumor.dataset_source = 'zhang_2016'
JOIN gene_statistics normal ON g.gene_id = normal.gene_id
  AND normal.sample_group = 'Normal'
  AND normal.dataset_source = 'zhang_2016'
WHERE tumor.mean_tpm > normal.mean_tpm  -- Upregulated in tumor
  AND normal.mean_tpm > 0.1  -- Filter noise (very low expression)
  AND tumor.mean_tpm > 1.0  -- Must be detectably expressed in tumor
ORDER BY fold_change DESC
LIMIT 20
```

### Reasoning
- Computes fold change from `gene_statistics` on-the-fly
- Joins Tumor and Normal groups from gene_statistics
- Calculates fold_change = tumor_mean / normal_mean
- Filters for upregulation (tumor > normal)
- Filters out noise (very low expression genes: normal > 0.1, tumor > 1.0)
- Orders by fold_change (higher = more upregulated)
- Limits to top 20 for manageable results
- **Note**: SQLite doesn't support LOG() function, so log2_fold_change is omitted

---

## Few-Shot Example 3: Mutation-Stratified Expression

### Question
"Compare EGFR expression in KRAS-mutant vs KRAS-wildtype cell lines"

### Expected Output
Mean expression and sample counts for each KRAS status group.

### SQL Query
```sql
SELECT
  g.gene_name,
  clm.KRAS_status,
  AVG(ge.tpm_value) AS mean_expression,
  MIN(ge.tpm_value) AS min_expression,
  MAX(ge.tpm_value) AS max_expression,
  COUNT(*) AS n_samples
FROM gene_expression ge
JOIN genes g ON ge.gene_id = g.gene_id
JOIN samples s ON ge.sample_id = s.sample_id
JOIN cell_line_metadata clm ON s.sample_id = clm.sample_id
WHERE g.gene_name = 'EGFR'
  AND s.sample_type = 'cell_line'
  AND clm.KRAS_status IN ('WT', 'p.G12C', 'p.G12D', 'p.G12V')
GROUP BY g.gene_name, clm.KRAS_status
ORDER BY mean_expression DESC
```

### Reasoning
- Uses `gene_expression` (raw data for custom aggregation by mutation)
- Joins `cell_line_metadata` for KRAS_status
- Filters to cell lines only
- Includes multiple KRAS mutations (not just WT vs mutant)
- Computes mean, range (min/max), and n for each group
- **Note**: SQLite does not support STDDEV() - use manual calculation if standard deviation is critical

---

## Common Pitfall: Forgetting to Filter sample_type

### Problem
Mixing human tissues and cell lines unintentionally.

### Solution
Always filter `samples.sample_type` when querying a specific sample type.

### Example
❌ BAD: This query mixes tissues and cell lines
```sql
SELECT g.gene_name, AVG(ge.tpm_value)
FROM gene_expression ge
JOIN genes g ON ge.gene_id = g.gene_id
JOIN samples s ON ge.sample_id = s.sample_id
WHERE g.gene_name = 'TP53'
```

✅ GOOD: Explicitly filter to human tissues
```sql
SELECT g.gene_name, AVG(ge.tpm_value)
FROM gene_expression ge
JOIN genes g ON ge.gene_id = g.gene_id
JOIN samples s ON ge.sample_id = s.sample_id
WHERE g.gene_name = 'TP53'
  AND s.sample_type = 'human_tissue'  -- Explicit filter
```

---

## Common Pitfall: Not Filtering NULL Metadata

### Problem
Metadata tables may have NULL values for missing data.

### Solution
Filter out NULLs when grouping by metadata fields.

### Example
❌ BAD: Includes samples with NULL TP53_status
```sql
SELECT clm.TP53_status, AVG(ge.tpm_value)
FROM gene_expression ge
JOIN samples s ON ge.sample_id = s.sample_id
LEFT JOIN cell_line_metadata clm ON s.sample_id = clm.sample_id
GROUP BY clm.TP53_status
```
Result: Includes a group "NULL" which is uninterpretable

✅ GOOD: Filter NULL values
```sql
SELECT clm.TP53_status, AVG(ge.tpm_value)
FROM gene_expression ge
JOIN samples s ON ge.sample_id = s.sample_id
JOIN cell_line_metadata clm ON s.sample_id = clm.sample_id
WHERE clm.TP53_status IS NOT NULL  -- Exclude NULL
GROUP BY clm.TP53_status
```

---

## Performance Tip: Use Precomputed Tables When Possible

### Context
Aggregating millions of rows from gene_expression is slow.

### Precomputed Tables
1. **gene_statistics**: Precomputed means, medians, SD by group
2. **gene_comparison**: Precomputed fold changes

### When to Use Each
- **Mean/median queries**: Use `gene_statistics` (100x faster)
- **Fold change queries**: Use `gene_comparison` (don't recompute)
- **Custom aggregations**: Use `gene_expression` (when precomputed data doesn't fit)

### Example
Question: "Average TP53 expression in tumor"

❌ SLOW (~5 seconds):
```sql
SELECT AVG(ge.tpm_value)
FROM gene_expression ge
JOIN genes g ON ge.gene_id = g.gene_id
JOIN samples s ON ge.sample_id = s.sample_id
JOIN human_tissue_metadata htm ON s.sample_id = htm.sample_id
WHERE g.gene_name = 'TP53' AND htm.tissue_type = 'Tumor'
```

✅ FAST (<0.1 seconds):
```sql
SELECT gs.mean_tpm
FROM gene_statistics gs
JOIN genes g ON gs.gene_id = g.gene_id
WHERE g.gene_name = 'TP53' AND gs.sample_group = 'Tumor'
```

---

## Biological Knowledge: TP53 (Tumor Suppressor)

### Gene Function
TP53 encodes p53, the "guardian of the genome." It is a tumor suppressor that regulates cell cycle, apoptosis, and DNA repair.

### Clinical Relevance
- Most commonly mutated gene in human cancers (~50%)
- TP53 mutations associated with poor prognosis
- Wildtype TP53 triggers apoptosis in response to DNA damage
- Mutant TP53 loses tumor suppressor function (loss-of-function)

### Expected Expression Pattern
- TP53 mRNA expression is often upregulated in tumors as a compensatory stress response
- However, TP53 protein function may be lost due to mutations

---

## Biological Knowledge: EGFR (Receptor Tyrosine Kinase)

### Gene Function
EGFR encodes Epidermal Growth Factor Receptor, a receptor tyrosine kinase that activates RAS/MAPK and PI3K/AKT signaling pathways.

### Clinical Relevance
- EGFR mutations occur in ~15% of lung adenocarcinomas (higher in Asian populations and never-smokers)
- Common activating mutations: L858R (exon 21), E746-A750del (exon 19)
- EGFR-mutant tumors are sensitive to EGFR inhibitors (gefitinib, erlotinib, osimertinib)
- EGFR T790M mutation confers resistance to first-generation EGFR inhibitors

### Expected Expression Pattern
- EGFR is often overexpressed in lung cancer
- EGFR mutant cell lines may show increased sensitivity to EGFR pathway activation

---

## Biological Knowledge: KRAS (Oncogene)

### Gene Function
KRAS encodes a GTPase that activates the RAS/MAPK signaling pathway, promoting cell proliferation.

### Clinical Relevance
- KRAS mutations occur in ~30% of lung adenocarcinomas
- Most common mutations: G12C, G12D, G12V (codon 12), G13D (codon 13)
- KRAS mutations are oncogenic drivers (gain-of-function)
- KRAS G12C-specific inhibitors (sotorasib, adagrasib) recently FDA-approved

### Expected Expression Pattern
- KRAS expression level is less important than mutation status
- KRAS mutant cell lines show constitutive activation of RAS/MAPK pathway

---

## SQL Best Practice: Use LEFT JOIN for Optional Metadata

### Context
Not all samples have metadata in all tables.

### Pattern
- Use INNER JOIN for required relationships (genes ↔ gene_expression)
- Use LEFT JOIN for optional metadata (samples ↔ human_tissue_metadata)

### Example
```sql
SELECT g.gene_name, ge.tpm_value, htm.tissue_type
FROM gene_expression ge
JOIN genes g ON ge.gene_id = g.gene_id          -- INNER: Required
JOIN samples s ON ge.sample_id = s.sample_id    -- INNER: Required
LEFT JOIN human_tissue_metadata htm             -- LEFT: Optional (cell lines don't have this)
  ON s.sample_id = htm.sample_id
WHERE g.gene_name = 'TP53'
```

This query works for both human tissues (with tissue_type) and cell lines (tissue_type = NULL).

---

## SQL Best Practice: ORDER BY for Readable Results

### Context
Query results should be organized logically for user interpretation.

### Common Patterns
1. **Tumor before Normal**: `ORDER BY CASE WHEN sample_group = 'Tumor' THEN 1 ELSE 2 END`
2. **By fold change magnitude**: `ORDER BY ABS(log2_fold_change) DESC`
3. **By expression level**: `ORDER BY mean_tpm DESC`
4. **Alphabetically**: `ORDER BY gene_name`

### Example
```sql
SELECT g.gene_name, gs.sample_group, gs.mean_tpm
FROM gene_statistics gs
JOIN genes g ON gs.gene_id = g.gene_id
WHERE g.gene_name IN ('TP53', 'EGFR', 'KRAS')
  AND gs.sample_group IN ('Tumor', 'Normal')
ORDER BY g.gene_name,
         CASE WHEN gs.sample_group = 'Tumor' THEN 1 ELSE 2 END
```

Result will be organized: TP53-Tumor, TP53-Normal, EGFR-Tumor, EGFR-Normal, KRAS-Tumor, KRAS-Normal

---

## CRITICAL: Filtering for Mutant Cell Lines (Excluding Unknown) - KRAS-mutant, TP53-mutant, EGFR-mutant queries

**APPLIES TO: Compare EGFR in KRAS-mutant, Show expression in TP53-mutant, Analyze EGFR-mutant cell lines**

### Problem
When querying for mutant cell lines (KRAS-mutant, TP53-mutant, EGFR-mutant), using `!= 'WT'` incorrectly includes "Unknown" status, which are NOT confirmed mutants.

### Why This Matters
- "Unknown" means mutation status was not determined or data is missing
- Mixing "Unknown" with confirmed mutants is scientifically invalid
- Violates biological interpretation and statistical validity

### WRONG Pattern ❌
```sql
-- This incorrectly includes "Unknown" status!
WHERE KRAS_status != 'WT'
```

**Result**: Returns both confirmed mutants AND "Unknown" status (invalid!)

### CORRECT Pattern ✅
```sql
-- Excludes both WT AND Unknown
WHERE KRAS_status NOT IN ('WT', 'Unknown', '')
  AND KRAS_status IS NOT NULL
```

**Result**: Returns ONLY confirmed mutants (valid!)

### Example Use Cases
These queries REQUIRE the correct filtering pattern:
- "Show EGFR expression in KRAS-mutant cell lines"
- "Compare expression in TP53-mutant cells"
- "Analyze EGFR-mutant vs wildtype"
- "Which genes are differentially expressed in mutant cells"

### Full Example
Question: "Show EGFR expression in KRAS-mutant cell lines"

❌ WRONG:
```sql
SELECT g.gene_name, ge.tpm_value, clm.KRAS_status
FROM gene_expression ge
JOIN genes g ON ge.gene_id = g.gene_id
JOIN samples s ON ge.sample_id = s.sample_id
JOIN cell_line_metadata clm ON s.sample_id = clm.sample_id
WHERE g.gene_name = 'EGFR'
  AND s.sample_type = 'cell_line'
  AND clm.KRAS_status != 'WT'  -- BAD! Includes "Unknown"
```

✅ CORRECT:
```sql
SELECT
  g.gene_name,
  clm.KRAS_status,
  AVG(ge.tpm_value) AS mean_egfr,
  COUNT(*) AS n_cell_lines
FROM gene_expression ge
JOIN genes g ON ge.gene_id = g.gene_id
JOIN samples s ON ge.sample_id = s.sample_id
JOIN cell_line_metadata clm ON s.sample_id = clm.sample_id
WHERE g.gene_name = 'EGFR'
  AND s.sample_type = 'cell_line'
  AND clm.KRAS_status NOT IN ('WT', 'Unknown', '')
  AND clm.KRAS_status IS NOT NULL  -- Excludes Unknown!
GROUP BY g.gene_name, clm.KRAS_status
```

### Same Pattern for All Mutation Queries
Apply this filtering to ANY mutation status field:
- `TP53_status NOT IN ('WT', 'Unknown', '') AND TP53_status IS NOT NULL`
- `EGFR_status NOT IN ('WT', 'Unknown', '') AND EGFR_status IS NOT NULL`
- `KRAS_status NOT IN ('WT', 'Unknown', '') AND KRAS_status IS NOT NULL`

---

## CRITICAL: Always Include Comparison Groups for Mutation Queries

### Problem
When users ask to "compare" mutations, queries often return ONLY the mutant group without a wild-type (WT) comparison baseline. This prevents valid comparative analysis.

### Why This Matters
- Cannot determine if mutants are different from WT without a comparison group
- No statistical context for results
- Violates the scientific meaning of "compare"

### WRONG Pattern ❌
```sql
-- Returns only mutants (no WT comparison)
SELECT clm.KRAS_status, AVG(ge.tpm_value)
FROM gene_expression ge
JOIN cell_line_metadata clm ON ...
WHERE clm.KRAS_status NOT IN ('WT', 'Unknown', '')
GROUP BY clm.KRAS_status
```

**Result**: Only mutant groups shown (cannot compare to baseline!)

### CORRECT Pattern ✅
```sql
-- Returns BOTH mutant and WT groups
SELECT
  CASE
    WHEN clm.KRAS_status = 'WT' THEN 'KRAS-WT'
    WHEN clm.KRAS_status NOT IN ('WT', 'Unknown', '')
      AND clm.KRAS_status IS NOT NULL THEN 'KRAS-mutant'
  END as kras_group,
  COUNT(*) AS n_cell_lines,
  AVG(ge.tpm_value) AS mean_egfr
FROM gene_expression ge
JOIN cell_line_metadata clm ON ...
WHERE (
  clm.KRAS_status = 'WT'
  OR (clm.KRAS_status NOT IN ('WT', 'Unknown', '')
      AND clm.KRAS_status IS NOT NULL)
)
GROUP BY kras_group
```

**Result**: Both KRAS-mutant AND KRAS-WT groups (valid comparison!)

### Example Use Cases
These queries REQUIRE both comparison groups:
- "Compare EGFR in KRAS-mutant cell lines" → Show mutant AND WT
- "Analyze TP53 expression in mutant vs wildtype" → Show both groups
- "EGFR levels in mutant cells" → Include WT for context

### Full Example
Question: "Compare EGFR expression in KRAS-mutant vs wildtype cell lines"

❌ WRONG (no WT group):
```sql
SELECT clm.KRAS_status, AVG(ge.tpm_value) AS mean_egfr
FROM gene_expression ge
JOIN genes g ON ge.gene_id = g.gene_id
JOIN samples s ON ge.sample_id = s.sample_id
JOIN cell_line_metadata clm ON s.sample_id = clm.sample_id
WHERE g.gene_name = 'EGFR'
  AND clm.KRAS_status != 'WT'  -- No WT comparison!
GROUP BY clm.KRAS_status
```

✅ CORRECT (both groups):
```sql
SELECT
  CASE
    WHEN clm.KRAS_status = 'WT' THEN 'KRAS-WT'
    WHEN clm.KRAS_status NOT IN ('WT', 'Unknown', '')
      AND clm.KRAS_status IS NOT NULL THEN 'KRAS-mutant'
  END as kras_group,
  COUNT(*) AS n_cell_lines,
  AVG(ge.tpm_value) AS mean_egfr,
  MIN(ge.tpm_value) AS min_egfr,
  MAX(ge.tpm_value) AS max_egfr
FROM gene_expression ge
JOIN genes g ON ge.gene_id = g.gene_id
JOIN samples s ON ge.sample_id = s.sample_id
JOIN cell_line_metadata clm ON s.sample_id = clm.sample_id
WHERE g.gene_name = 'EGFR'
  AND s.sample_type = 'cell_line'
  AND (
    clm.KRAS_status = 'WT'
    OR (clm.KRAS_status NOT IN ('WT', 'Unknown', '')
        AND clm.KRAS_status IS NOT NULL)
  )
GROUP BY kras_group
ORDER BY kras_group
```

**Note**: SQLite does not support STDDEV(). Use range (min/max) for variability, or calculate standard deviation manually if needed.

### Alternative: Individual Mutation Type Breakdown
If user wants to see EACH mutation type separately (not just mutant vs WT):

```sql
SELECT
  clm.KRAS_status,
  COUNT(*) AS n_cell_lines,
  AVG(ge.tpm_value) AS mean_egfr
FROM gene_expression ge
JOIN genes g ON ge.gene_id = g.gene_id
JOIN samples s ON ge.sample_id = s.sample_id
JOIN cell_line_metadata clm ON s.sample_id = clm.sample_id
WHERE g.gene_name = 'EGFR'
  AND s.sample_type = 'cell_line'
  AND clm.KRAS_status NOT IN ('Unknown', '')
  AND clm.KRAS_status IS NOT NULL
GROUP BY clm.KRAS_status
ORDER BY clm.KRAS_status
```

This shows: WT, p.G12C, p.G12D, p.G12V, etc. (each as separate row)

### Sample Size Validation
Always include sample counts (n) to assess statistical validity:
- n >= 3 per group: Minimum for basic statistics
- n >= 10 per group: Adequate for t-tests
- n < 3: Add caveat about insufficient sample size

