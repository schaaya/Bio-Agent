"""
Data Cleaning and Feature Engineering Script for NSLC Gene Expression Data

UPDATES (2025-10-22):
- Changed mutation column names from EGFR/TP53/KRAS to EGFR_status/TP53_status/KRAS_status
  to match database schema (bio_gene_expression.db)
- Changed proliferation_cat to proliferation_category for consistency
- Added "Unknown" filling for empty mutation values to match database convention
- These changes ensure clean_outputs TSV files align with SQL query expectations

Original columns in Excel: EGFR, TP53, KRAS
Output columns in TSV: EGFR_status, TP53_status, KRAS_status
"""

import re
from pathlib import Path
import pandas as pd
import numpy as np

# ---------- EDIT THESE PATHS ----------
P_ZHANG_TPM  = Path("zhang.salmon.merged.gene_tpm.tsv")
P_ZHANG_META = Path("sample_map.tsv")  # columns: Subject_ID, source_name, ...
P_FL3C_TPM   = Path("fl3c.salmon.merged.gene_tpm.tsv")
P_FL3C_S1    = Path("Suppl Table S1 Cell Lines.xlsx")  # the Excel you showed

OUT_DIR = Path("clean_outputs")
OUT_DIR.mkdir(parents=True, exist_ok=True)

# ---------- helpers ----------
def _standardize_cols(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = (df.columns.astype(str).str.strip()
                  .str.replace("\u200b", "", regex=False)
                  .str.replace("\xa0", " ", regex=False)
                  .str.replace(" ", "_", regex=False)
                  .str.lower())
    return df

def drop_all_zero_genes(df_long: pd.DataFrame, value_col="tpm") -> pd.DataFrame:
    mask = df_long.groupby("gene_id")[value_col].transform(lambda s: np.nansum(pd.to_numeric(s, errors="coerce").fillna(0).values)) > 0
    return df_long[mask].copy()

def summarize_by_group(df_long: pd.DataFrame, value_col="tpm", group_col="group") -> pd.DataFrame:
    return (df_long.groupby(["gene_id", group_col])[value_col]
                  .agg(n="count", mean="mean", median="median", var="var")
                  .reset_index())

def add_log2_fc(summary_df: pd.DataFrame, group_col="group",
                num_group="Tumor", den_group="Normal") -> pd.DataFrame:
    a = summary_df[summary_df[group_col] == num_group][["gene_id", "mean"]].rename(columns={"mean": "mean_num"})
    b = summary_df[summary_df[group_col] == den_group][["gene_id", "mean"]].rename(columns={"mean": "mean_den"})
    m = a.merge(b, on="gene_id", how="inner")
    m["fold_change"] = (m["mean_num"] + 1e-6) / (m["mean_den"] + 1e-6)
    m["log2_fc"] = np.log2(m["fold_change"])
    return m[["gene_id", "fold_change", "log2_fc"]]

# ---------- ZHANG (HUMAN) ----------
print("== ZHANG (human) ==")
zhang_tpm = pd.read_csv(P_ZHANG_TPM, sep="\t", low_memory=False)
zhang_tpm = _standardize_cols(zhang_tpm)

# Detect gene columns
gid_col = next((c for c in ["gene_id", "ensembl", "ensembl_gene_id", "gene"] if c in zhang_tpm.columns), zhang_tpm.columns[0])
gsym_col = next((c for c in ["gene_name", "symbol", "gene_symbol"] if c in zhang_tpm.columns), None)

zhang_meta_raw = pd.read_csv(P_ZHANG_META, sep="\t", low_memory=False)
# NOTE: we do NOT standardize column names here yet because your TSV has CamelCase headers we reference below.
# We'll copy out the two columns we need, then standardize.

# Expecting columns: 'Subject_ID' (e.g., NSLC-0093) and 'source_name' (contains 'tumor' or 'normal')
assert "Subject_ID" in zhang_meta_raw.columns, f"Subject_ID not found in {P_ZHANG_META}"
assert "source_name" in zhang_meta_raw.columns, f"source_name not found in {P_ZHANG_META}"

def norm_subject(x: str) -> str:
    x = str(x).strip().upper().replace("-", ".").replace("_", ".")
    m = re.search(r"NSLC\.?(\d+)", x)
    if m:
        return f"NSLC.{m.group(1).zfill(4)}"
    return x

def status_to_group_suffix(text: str):
    t = str(text).lower()
    if "tumor" in t:   return "Tumor", ".T"
    if "normal" in t:  return "Normal", ".N"
    return "Unknown", ""

m = zhang_meta_raw[["Subject_ID", "source_name"]].copy()
m["subject_norm"] = m["Subject_ID"].map(norm_subject)
m[["group", "suffix"]] = m["source_name"].apply(lambda s: pd.Series(status_to_group_suffix(s)))
m["sample_id_norm"] = m["subject_norm"] + m["suffix"]
meta_key = m[["sample_id_norm", "group"]].drop_duplicates()

# melt TPM and normalize column headers to match 'NSLC.####.T/N'
exclude = [gid_col] + ([gsym_col] if gsym_col else [])
sample_cols = [c for c in zhang_tpm.columns if c not in exclude]

z_long = zhang_tpm.melt(id_vars=[gid_col] + ([gsym_col] if gsym_col else []),
                        value_vars=sample_cols, var_name="sample_id", value_name="tpm")
z_long["tpm"] = pd.to_numeric(z_long["tpm"], errors="coerce")
z_long = z_long.rename(columns={gid_col: "gene_id"})
z_long["sample_id_norm"] = (
    z_long["sample_id"].astype(str).str.strip().str.upper()
         .str.replace("-", ".", regex=False).str.replace("_", ".", regex=False)
         .str.replace(r"\.+", ".", regex=True)
)

z_joined = z_long.merge(meta_key, on="sample_id_norm", how="left")
print("Human merge: % missing group =", round(z_joined["group"].isna().mean()*100, 2), "%")

z_clean = drop_all_zero_genes(z_joined.rename(columns={"sample_id_norm": "sample_id"}), value_col="tpm")
z_clean.to_csv(OUT_DIR / "zhang_tpm_clean.tsv", sep="\t", index=False)

# gene summaries + log2FC (Tumor vs Normal)
z_sum = summarize_by_group(z_clean, value_col="tpm", group_col="group")
z_fc  = add_log2_fc(z_sum, group_col="group", num_group="Tumor", den_group="Normal")
z_wide = z_sum.pivot_table(index="gene_id", columns="group", values=["n", "mean", "median", "var"])
z_wide.columns = [f"{stat}_{grp.lower()}" for stat, grp in z_wide.columns]
z_gene_summary = z_wide.reset_index().merge(z_fc, on="gene_id", how="left")
z_gene_summary.to_csv(OUT_DIR / "gene_summary_zhang.tsv", sep="\t", index=False)

# also export metadata (lowercased & standardized)
zhang_meta = _standardize_cols(zhang_meta_raw)
zhang_meta_fixed = pd.DataFrame({
    "sample_id": meta_key["sample_id_norm"],
    "group": meta_key["group"]
})
zhang_meta_fixed.to_csv(OUT_DIR / "zhang_metadata_clean.tsv", sep="\t", index=False)

print("Saved Zhang outputs.")

# ---------- VANDERSTEEN (CELL LINES) ----------
print("== VanDerSteen (cell lines) ==")
fl3c = pd.read_csv(P_FL3C_TPM, sep="\t", low_memory=False)
fl3c = _standardize_cols(fl3c)
gid_col_c = next((c for c in ["gene_id", "ensembl", "ensembl_gene_id", "gene"] if c in fl3c.columns), fl3c.columns[0])
gsym_col_c = next((c for c in ["gene_name", "symbol", "gene_symbol"] if c in fl3c.columns), None)

# melt and strip replicate suffixes (_rep1, _rep2, ...)
exclude_c = [gid_col_c] + ([gsym_col_c] if gsym_col_c else [])
val_cols_c = [c for c in fl3c.columns if c not in exclude_c]

def base_from_col(c: str) -> str:
    c = str(c).strip()
    c = re.sub(r"(?i)_rep\d+$", "", c)  # drop trailing _repX
    c = c.split(".")[0]
    return c

fl_long = fl3c.melt(id_vars=[gid_col_c] + ([gsym_col_c] if gsym_col_c else []),
                    value_vars=val_cols_c, var_name="sample_id", value_name="tpm")
fl_long["tpm"] = pd.to_numeric(fl_long["tpm"], errors="coerce")
fl_long = fl_long.rename(columns={gid_col_c: "gene_id"})
fl_long["cell_line_raw"] = fl_long["sample_id"].map(base_from_col)

def norm_cellline(x: str) -> str:
    x = str(x).upper().strip()
    x = re.sub(r"[\s_]+", "-", x)      # spaces/underscores -> hyphen
    x = re.sub(r"[^A-Z0-9\-]", "", x)  # keep alnum + hyphen
    x = re.sub(r"-+", "-", x)
    return x

fl_long["cell_line_norm"] = fl_long["cell_line_raw"].map(norm_cellline)

# Load S1 and pick the columns you showed
S1 = pd.read_excel(P_FL3C_S1)  # requires openpyxl
meta = S1.rename(columns={
    "Cell Line": "cell_line",
    "Subtype": "histology",
    "Proliferation rate 72h": "proliferation_rate_72h",
    "Proliferation (category)": "proliferation_category",  # Use full word
    # Rename mutation columns to match database schema
    "EGFR": "EGFR_status",
    "TP53": "TP53_status",
    "KRAS": "KRAS_status"
})
meta["cell_line_norm"] = meta["cell_line"].map(norm_cellline)

# Fill empty mutation status values with "Unknown" to match database
for col in ["EGFR_status", "TP53_status", "KRAS_status"]:
    if col in meta.columns:
        meta[col] = meta[col].fillna("Unknown").replace("", "Unknown").astype(str).str.strip()
        # Replace empty strings after stripping
        meta.loc[meta[col] == "", col] = "Unknown"

keep = ["cell_line_norm", "cell_line", "histology", "proliferation_rate_72h",
        "proliferation_category", "EGFR_status", "TP53_status", "KRAS_status"]
meta = meta[[c for c in keep if c in meta.columns]].drop_duplicates()

# merge TPM with metadata
fl_joined = fl_long.merge(meta, on="cell_line_norm", how="left")
fl_joined["group"] = "Cell line"

# Save per-replicate clean table
fl_clean = drop_all_zero_genes(fl_joined.rename(columns={"cell_line_norm": "sample_id"}), value_col="tpm")
fl_clean.to_csv(OUT_DIR / "fl3c_tpm_clean.tsv", sep="\t", index=False)

# Save cell-line metadata
fl_meta_out = meta.rename(columns={"cell_line_norm": "sample_id"})
fl_meta_out.to_csv(OUT_DIR / "fl3c_metadata_clean.tsv", sep="\t", index=False)

# Gene summaries (by histology if present)
# --- Gene summaries (by histology if present), avoiding duplicate 'group' name
if "histology" in fl_clean.columns:
    fl_clean["group_for_summary"] = fl_clean["histology"].astype(str)
    fl_clean.loc[fl_clean["group_for_summary"].isin(["", "nan", "None"]), "group_for_summary"] = "Cell line"
else:
    fl_clean["group_for_summary"] = fl_clean["group"]

# Summarize
c_sum = summarize_by_group(fl_clean, value_col="tpm", group_col="group_for_summary")

# Pivot to a wide table
c_wide = c_sum.pivot_table(index="gene_id",
                           columns="group_for_summary",
                           values=["n", "mean", "median", "var"])
# Tidy column names
c_wide.columns = [f"{stat}_{str(grp).lower().replace(' ', '_')}" for stat, grp in c_wide.columns]
c_gene_summary = c_wide.reset_index()
c_gene_summary.to_csv(OUT_DIR / "gene_summary_fl3c.tsv", sep="\t", index=False)

print("Saved FL3C outputs.")

print("All done. Clean outputs saved to:", OUT_DIR.resolve())


# ---------- OPTIONAL: plotting helper ----------
def boxplot_gene(df_long: pd.DataFrame, gene_query: str, *,
                 group_col="group", gene_id_col="gene_id",
                 gene_symbol_col="gene_name", title=None):
    """Safe boxplot across groups for one gene."""
    sub = df_long.copy()
    mask = sub[gene_id_col].astype(str).str.upper().eq(gene_query.upper())
    if gene_symbol_col in sub.columns and not mask.any():
        mask = sub[gene_symbol_col].astype(str).str.upper().eq(gene_query.upper())
    sub = sub[mask].copy()
    if sub.empty:
        print(f"No rows for gene: {gene_query}"); return

    preferred = ["Normal", "Tumor", "Cell line"]
    groups = [g for g in preferred if g in sub[group_col].unique()]
    if not groups: groups = list(sub[group_col].dropna().unique())

    data, labels = [], []
    for g in groups:
        vals = pd.to_numeric(sub.loc[sub[group_col] == g, "tpm"], errors="coerce").dropna()
        if len(vals): data.append(vals); labels.append(g)
    if not data:
        print(f"No numeric TPM values to plot for {gene_query}."); return

    import matplotlib.pyplot as plt
    plt.figure(figsize=(6, 4))
    plt.boxplot(data, tick_labels=labels, showfliers=False)
    plt.ylabel("TPM"); plt.xlabel("Group")
    plt.title(title or f"Expression for {gene_query}")
    plt.tight_layout(); plt.show()

boxplot_gene(z_clean, "TP53", group_col="group",
             title="Zhang (human) – TP53",
             gene_id_col="gene_id", gene_symbol_col="gene_name")
boxplot_gene(fl_clean, "TP53", group_col="group",
                title="FL3C (cell lines) – TP53",
                gene_id_col="gene_id", gene_symbol_col="gene_name") 