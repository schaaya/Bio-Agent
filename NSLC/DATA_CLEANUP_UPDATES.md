# Data Cleanup Script Updates - 2025-10-22

## Summary

Updated `data_clean_feature_engineering.py` to match database schema expectations. The original clean_outputs files had column name mismatches that caused SQL queries to fail.

---

## Changes Made

### 1. **Mutation Column Renaming**

**Before** (in clean_outputs):
- `EGFR`
- `TP53`
- `KRAS`

**After** (now matches database schema):
- `EGFR_status`
- `TP53_status`
- `KRAS_status`

**Why**: All SQL queries in the codebase reference `EGFR_status`, `TP53_status`, `KRAS_status`. The SQLite database (`bio_gene_expression.db`) also uses these column names with the `_status` suffix.

### 2. **Proliferation Column Standardization**

**Before**:
- `proliferation_cat` (abbreviated)

**After**:
- `proliferation_category` (full word)

**Why**: Consistency with database schema and clarity.

### 3. **Empty Value Handling**

**Before**:
- Empty strings (`""`) for missing mutation data

**After**:
- `"Unknown"` for all empty/null mutation values

**Why**: The SQLite database populates empty mutation values as `"Unknown"`. This ensures consistency across data sources.

**Code added**:
```python
# Fill empty mutation status values with "Unknown" to match database
for col in ["EGFR_status", "TP53_status", "KRAS_status"]:
    if col in meta.columns:
        meta[col] = meta[col].fillna("Unknown").replace("", "Unknown").astype(str).str.strip()
        meta.loc[meta[col] == "", col] = "Unknown"
```

---

## Files Modified

1. **NSLC/data_clean_feature_engineering.py**
   - Lines 1-13: Added docstring explaining updates
   - Lines 151-172: Updated metadata processing
     - Column renames in Excel import
     - Empty value filling
     - Updated keep list

---

## Output Files Impact

### Before Updates (backed up to `clean_outputs_backup_20251022/`):

**fl3c_metadata_clean.tsv** header:
```
sample_id	cell_line	histology	proliferation_rate_72h	proliferation_cat	EGFR	TP53	KRAS
```

**Sample row**:
```
HCC2935	HCC2935	Lung Adenocarcinoma	2.77	slow
```
(Empty EGFR, TP53, KRAS values)

### After Updates (to be generated):

**fl3c_metadata_clean.tsv** header:
```
sample_id	cell_line	histology	proliferation_rate_72h	proliferation_category	EGFR_status	TP53_status	KRAS_status
```

**Sample row**:
```
HCC2935	HCC2935	Lung Adenocarcinoma	2.77	slow	Unknown	Unknown	Unknown
```
(Empty values now "Unknown")

---

## Discrepancy Root Cause

The issue arose because:

1. **Original Excel file** (`Suppl Table S1 Cell Lines.xlsx`) has columns named `EGFR`, `TP53`, `KRAS`
2. **SQLite database** (`bio_gene_expression.db`) was manually created with `EGFR_status`, `TP53_status`, `KRAS_status`
3. **SQL queries and domain knowledge** all reference the `_status` suffix columns
4. **Old processing script** used the Excel column names directly without renaming

This caused:
- SQL queries like `WHERE EGFR_status = 'p.E746_A750delELREA'` to fail when loading from TSV files
- Empty mutation values displayed as blank instead of "Unknown"

---

## How to Regenerate Clean Outputs

### Prerequisites

Ensure these packages are installed:
```bash
pip install pandas numpy openpyxl
```

(These should already be in `requirements.txt`)

### Steps

1. **Navigate to NSLC directory**:
   ```bash
   cd NSLC/
   ```

2. **Verify raw data files exist**:
   ```bash
   ls -lh zhang.salmon.merged.gene_tpm.tsv
   ls -lh fl3c.salmon.merged.gene_tpm.tsv
   ls -lh sample_map.tsv
   ls -lh "Suppl Table S1 Cell Lines.xlsx"
   ```

3. **Run the updated script**:
   ```bash
   python data_clean_feature_engineering.py
   ```

4. **Verify output**:
   ```bash
   ls -lh clean_outputs/
   head -1 clean_outputs/fl3c_metadata_clean.tsv
   ```

   **Expected header**:
   ```
   sample_id	cell_line	histology	proliferation_rate_72h	proliferation_category	EGFR_status	TP53_status	KRAS_status
   ```

5. **Check for "Unknown" values**:
   ```bash
   grep "Unknown" clean_outputs/fl3c_metadata_clean.tsv | head -3
   ```

   Should show cell lines with Unknown mutation status.

---

## Verification Checklist

After regeneration, verify:

- [ ] `clean_outputs/fl3c_metadata_clean.tsv` has `EGFR_status`, `TP53_status`, `KRAS_status` columns
- [ ] `clean_outputs/fl3c_metadata_clean.tsv` has `proliferation_category` (not `proliferation_cat`)
- [ ] Empty mutation values show "Unknown" instead of blank
- [ ] File sizes are similar to backup (301MB for fl3c_tpm_clean.tsv, 88MB for zhang_tpm_clean.tsv)
- [ ] Gene summary files generated without errors

---

## Expected Output

When the script runs successfully, you should see:

```
== ZHANG (human) ==
Human merge: % missing group = 0.0 %
Saved Zhang outputs.

== VanDerSteen (cell lines) ==
Saved FL3C outputs.

All done. Clean outputs saved to: /path/to/clean_outputs
```

With optional boxplot windows (can be closed).

---

## Files Generated

After running, these files will be in `clean_outputs/`:

1. **zhang_tpm_clean.tsv** (~88 MB)
   - Long-format gene expression data for Zhang (human) dataset
   - Columns: gene_id, gene_name, sample_id, tpm, group

2. **zhang_metadata_clean.tsv** (~1.2 KB)
   - Sample metadata for Zhang dataset
   - Columns: sample_id, group (Tumor/Normal)

3. **gene_summary_zhang.tsv** (~3.8 MB)
   - Gene-level statistics for Tumor vs Normal
   - Includes fold_change and log2_fc

4. **fl3c_tpm_clean.tsv** (~301 MB)
   - Long-format gene expression data for cell lines
   - Columns: gene_id, gene_name, sample_id, tpm, cell_line_norm, cell_line, histology, proliferation_rate_72h, proliferation_category, EGFR_status, TP53_status, KRAS_status, group

5. **fl3c_metadata_clean.tsv** (~4.3 KB)
   - Cell line metadata ✅ **Updated with _status columns**
   - Columns: sample_id, cell_line, histology, proliferation_rate_72h, proliferation_category, EGFR_status, TP53_status, KRAS_status

6. **gene_summary_fl3c.tsv** (~2.8 MB)
   - Gene-level statistics by histology

---

## Database Re-loading (If Needed)

If the PostgreSQL or SQLite databases need to be reloaded with the new clean data:

### Option 1: Manual SQL Import

```sql
-- PostgreSQL example
COPY cell_line_metadata(sample_id, cell_line, histology, proliferation_rate_72h,
                        proliferation_category, EGFR_status, TP53_status, KRAS_status)
FROM '/path/to/clean_outputs/fl3c_metadata_clean.tsv'
DELIMITER E'\t'
CSV HEADER;
```

### Option 2: Python Script

```python
import pandas as pd
import sqlite3

# Load cleaned data
meta = pd.read_csv("clean_outputs/fl3c_metadata_clean.tsv", sep="\t")

# Connect to database
conn = sqlite3.connect("bio_gene_expression.db")

# Replace existing table
meta.to_sql("cell_line_metadata", conn, if_exists="replace", index=False)

conn.close()
```

**Note**: The database loading script likely already exists in the project. Check `NSLC/bio_chatbot_*.py` or `scripts/` directory.

---

## Impact on Queries

### Query That Previously Failed:

```sql
SELECT g.gene_name, clm.EGFR_status, AVG(ge.tpm_value) AS mean_expression
FROM gene_expression ge
JOIN genes g ON ge.gene_id = g.gene_id
JOIN samples s ON ge.sample_id = s.sample_id
JOIN cell_line_metadata clm ON s.sample_id = clm.sample_id
WHERE g.gene_name = 'EGFR'
  AND clm.EGFR_status NOT IN ('WT', 'Unknown', '')  -- ❌ Would fail if TSV had "EGFR" column
```

**Before**: Column `EGFR_status` not found in TSV data → SQL error

**After**: Column `EGFR_status` exists → Query works ✅

---

## Backup Information

Original clean_outputs backed up to:
```
NSLC/clean_outputs_backup_20251022/
```

**Contents**:
- fl3c_metadata_clean.tsv (OLD - has EGFR, TP53, KRAS columns)
- fl3c_tpm_clean.tsv
- gene_summary_fl3c.tsv
- gene_summary_zhang.tsv
- zhang_metadata_clean.tsv
- zhang_tpm_clean.tsv

**Can be deleted after verification** that new clean_outputs work correctly.

---

## Testing the Fix

### Test 1: Check column names
```bash
head -1 clean_outputs/fl3c_metadata_clean.tsv
# Should show: sample_id	cell_line	...	EGFR_status	TP53_status	KRAS_status
```

### Test 2: Check Unknown values
```bash
awk -F'\t' 'NR>1 && $6=="Unknown" {print $1,$6,$7,$8}' clean_outputs/fl3c_metadata_clean.tsv | head -5
# Should show cell lines with Unknown mutation status
```

### Test 3: Run a SQL query (if database loaded)
```sql
SELECT DISTINCT EGFR_status
FROM cell_line_metadata
ORDER BY EGFR_status;
-- Should return: p.E746_A750delELREA, Unknown, WT, etc.
```

### Test 4: Run user query via chatbot
```
Query: "EGFR levels in mutant cells"
Expected: Should now show "p.E746_A750delELREA" (not just "Mutant")
```

---

## Related Fixes

This change complements the earlier fix in `core/summarization.py` (lines 302-324) which ensures that even if mutation values are present, they're displayed with their exact names (e.g., "p.E746_A750delELREA") rather than generic labels like "Mutant".

Combined effect:
1. **Data layer** (this fix): Correct column names and "Unknown" standardization
2. **Presentation layer** (summarization.py fix): Exact mutation name display

---

## Questions?

If you encounter issues:

1. **Import errors**: Verify pandas, numpy, openpyxl are installed
2. **File not found**: Check that raw data files exist in NSLC/ directory
3. **Output mismatch**: Compare with backup to see what changed
4. **Database sync**: May need to reload database with new TSV files

---

**Updated**: 2025-10-22
**Script Version**: 2.0 (with _status suffix support)
**Backup Location**: `NSLC/clean_outputs_backup_20251022/`
