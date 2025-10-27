# Quick Start: Regenerate Clean Outputs

## TL;DR

Your `data_clean_feature_engineering.py` has been updated. Run it to regenerate clean_outputs with correct column names.

---

## What Was Fixed

**Problem**: Old clean_outputs had `EGFR`, `TP53`, `KRAS` columns, but database and SQL queries expect `EGFR_status`, `TP53_status`, `KRAS_status`.

**Solution**: Updated script to rename columns and standardize empty values to "Unknown".

---

## Run This Now

```bash
# Navigate to NSLC directory
cd NSLC/

# Run the updated script
python data_clean_feature_engineering.py

# Verify output
head -1 clean_outputs/fl3c_metadata_clean.tsv
# Should show: ...EGFR_status	TP53_status	KRAS_status
```

**Expected output**:
```
== ZHANG (human) ==
Human merge: % missing group = 0.0 %
Saved Zhang outputs.

== VanDerSteen (cell lines) ==
Saved FL3C outputs.

All done. Clean outputs saved to: /path/to/clean_outputs
```

(Optional matplotlib boxplots may appear - you can close them)

---

## Verify It Worked

```bash
# Check column names
head -1 clean_outputs/fl3c_metadata_clean.tsv | grep "EGFR_status"
# Should output the header line with EGFR_status

# Check for Unknown values
grep "Unknown" clean_outputs/fl3c_metadata_clean.tsv | wc -l
# Should be > 0

# Check file sizes
ls -lh clean_outputs/
# Should show:
# - fl3c_tpm_clean.tsv: ~301M
# - zhang_tpm_clean.tsv: ~88M
# - fl3c_metadata_clean.tsv: ~4.3K
```

---

## If It Fails

### Error: "No module named 'pandas'"
```bash
pip install pandas numpy openpyxl
```

### Error: "File not found"
```bash
# Make sure you're in NSLC/ directory
cd NSLC/
ls -lh zhang.salmon.merged.gene_tpm.tsv
ls -lh "Suppl Table S1 Cell Lines.xlsx"
```

### Error: "Permission denied"
```bash
# Check file permissions
chmod +x data_clean_feature_engineering.py
```

---

## What Happens Next

After regeneration:
1. ✅ SQL queries will work (correct column names)
2. ✅ Empty mutations show "Unknown" (standardized)
3. ✅ Chatbot queries like "EGFR levels in mutant cells" will work properly

---

## Backup Information

Your old clean_outputs were backed up to:
```
NSLC/clean_outputs_backup_20251022/
```

You can delete this after verifying the new files work (in 1-2 weeks).

---

## Full Documentation

For complete details, see:
- `DATA_CLEANUP_UPDATES.md` - Detailed change explanations
- `DATABASE_AND_FILES_AUDIT_REPORT.md` - Full audit report

---

**Questions?** Check the documentation files or reach out for support.

**Estimated time**: 2-5 minutes (depending on system speed)
