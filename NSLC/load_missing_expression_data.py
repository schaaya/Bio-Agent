"""
Load Missing Cell Line Expression Data into Database

Problem: Only 12 out of 60 cell lines have expression data loaded.
Solution: Load the remaining 48 cell lines from clean_outputs/fl3c_tpm_clean.tsv

The TSV file is in LONG format:
- Each row: gene_id, gene_name, sample_id (replicate), tpm, cell_line (normalized), ...
- We need to aggregate replicates and load by cell_line name

Usage:
    python load_missing_expression_data.py
"""

import sqlite3
import sys
from pathlib import Path
from collections import defaultdict

DB_PATH = Path("bio_gene_expression.db")
TPM_FILE = Path("clean_outputs/fl3c_tpm_clean.tsv")

def check_prerequisites():
    """Check if required files exist"""
    if not DB_PATH.exists():
        print(f"❌ Database not found: {DB_PATH}")
        return False

    if not TPM_FILE.exists():
        print(f"❌ TPM file not found: {TPM_FILE}")
        print("   Run: python data_clean_feature_engineering.py first")
        return False

    print(f"✅ Found database: {DB_PATH} ({DB_PATH.stat().st_size / 1024 / 1024:.1f} MB)")
    print(f"✅ Found TPM file: {TPM_FILE} ({TPM_FILE.stat().st_size / 1024 / 1024:.1f} MB)")
    return True

def get_current_status(conn):
    """Check current database status"""
    cursor = conn.cursor()

    # Total cell lines
    cursor.execute("SELECT COUNT(*) FROM samples WHERE sample_type = 'cell_line'")
    total_samples = cursor.fetchone()[0]

    # Cell lines with expression data
    cursor.execute("""
        SELECT COUNT(DISTINCT s.sample_id)
        FROM samples s
        JOIN gene_expression ge ON s.sample_id = ge.sample_id
        WHERE s.sample_type = 'cell_line'
    """)
    with_data = cursor.fetchone()[0]

    # Cell lines without expression data
    cursor.execute("""
        SELECT s.sample_id
        FROM samples s
        LEFT JOIN gene_expression ge ON s.sample_id = ge.sample_id
        WHERE s.sample_type = 'cell_line'
          AND ge.expression_id IS NULL
        ORDER BY s.sample_id
    """)
    without_data = [row[0] for row in cursor.fetchall()]

    return total_samples, with_data, without_data

def get_gene_id_map(conn):
    """Create a mapping of gene_name -> gene_id"""
    cursor = conn.cursor()
    cursor.execute("SELECT gene_name, gene_id FROM genes")
    return {name: gid for name, gid in cursor.fetchall()}

def load_expression_data_long_format(conn, tpm_file, missing_samples, gene_id_map):
    """
    Load expression data from LONG format TSV file.

    Long format:
    gene_id, gene_name, sample_id (rep), tpm, cell_line_raw, cell_line (normalized), ...

    We aggregate replicates by taking the mean TPM across replicates for each gene+cell_line.
    """
    import csv
    import re

    print(f"\n📂 Reading TPM file (long format)...")

    # Normalize missing sample names to lowercase for matching
    missing_samples_lower = {s.lower(): s for s in missing_samples}

    # Storage: gene_name -> cell_line -> [tpm_values]
    data_by_gene_cell = defaultdict(lambda: defaultdict(list))

    genes_seen = set()
    cells_found = set()

    with open(tpm_file, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f, delimiter='\t')

        # Use 'cell_line_raw' column (normalized cell line name from raw data)
        # NOT 'cell_line' which is from metadata Excel and is empty for 48 cell lines
        if 'cell_line_raw' not in reader.fieldnames:
            print("   ❌ 'cell_line_raw' column not found in TSV")
            print(f"   Available columns: {reader.fieldnames}")
            return 0

        print(f"   Processing rows...")
        rows_processed = 0

        for row in reader:
            rows_processed += 1
            if rows_processed % 500000 == 0:
                print(f"   Processed {rows_processed:,} rows, found {len(cells_found)} missing cell lines...", end='\r')

            gene_name = row.get('gene_name', row.get('gene_id'))
            cell_line_raw = row.get('cell_line_raw', '').strip()
            tpm_str = row.get('tpm', '0')

            if not gene_name or not cell_line_raw:
                continue

            # Normalize cell line name to match database format
            # Database has: "CALU-3", "NCI-H1299", "A549", "HCC827"
            # TSV has: "calu3", "h1299", "a549", "hcc827"
            cell_line_normalized = cell_line_raw.upper()

            # Handle NCI-H cell lines: h1299 → H1299 → NCI-H1299 (NOT NCI-H-1299!)
            if cell_line_normalized.startswith('H') and len(cell_line_normalized) > 1 and cell_line_normalized[1].isdigit():
                cell_line_normalized = 'NCI-' + cell_line_normalized
            else:
                # For other cell lines, add hyphen before numbers: CALU3 → CALU-3
                cell_line_normalized = re.sub(r'([A-Z]+)(\d)', r'\1-\2', cell_line_normalized)

            cell_line = cell_line_normalized

            # Check if this cell line is in our missing list
            cell_line_lower = cell_line.lower()
            if cell_line_lower not in missing_samples_lower:
                continue

            # Track that we found this cell line
            cells_found.add(cell_line)

            # Parse TPM value
            try:
                tpm_value = float(tpm_str)
            except (ValueError, TypeError):
                continue

            # Store: gene -> cell -> [tpm values from replicates]
            data_by_gene_cell[gene_name][cell_line].append(tpm_value)
            genes_seen.add(gene_name)

        print(f"\n   Processed {rows_processed:,} total rows")
        print(f"   Found {len(cells_found)} missing cell lines in data")
        print(f"   Found {len(genes_seen)} genes")

    if not cells_found:
        print(f"\n   ⚠️ None of the missing cell lines found in TPM file")
        print(f"   Missing (from DB): {list(missing_samples_lower.values())[:5]}")
        print(f"   Available in file: Check 'cell_line' column values")
        return 0

    print(f"\n   Cell lines to load: {', '.join(sorted(cells_found))}")

    # Now compute mean across replicates and insert into database
    print(f"\n📥 Computing means and loading into database...")

    cursor = conn.cursor()
    inserted = 0
    batch = []
    batch_size = 10000

    for gene_name, cell_dict in data_by_gene_cell.items():
        # Look up gene_id
        gene_id = gene_id_map.get(gene_name)
        if not gene_id:
            continue

        for cell_line, tpm_values in cell_dict.items():
            # Compute mean across replicates
            mean_tpm = sum(tpm_values) / len(tpm_values)

            # Use the original case cell line name from database
            db_cell_line = missing_samples_lower.get(cell_line.lower(), cell_line)

            batch.append((gene_id, db_cell_line, mean_tpm, 'fl3c'))
            inserted += 1

            # Batch insert
            if len(batch) >= batch_size:
                cursor.executemany(
                    "INSERT INTO gene_expression (gene_id, sample_id, tpm_value, dataset_source) VALUES (?, ?, ?, ?)",
                    batch
                )
                conn.commit()
                print(f"   Inserted {inserted:,} records...", end='\r')
                batch = []

    # Insert remaining
    if batch:
        cursor.executemany(
            "INSERT INTO gene_expression (gene_id, sample_id, tpm_value, dataset_source) VALUES (?, ?, ?, ?)",
            batch
        )
        conn.commit()

    print(f"\n   ✅ Inserted {inserted:,} expression records")
    return inserted

def main():
    print("="*80)
    print("🧬 Load Missing Cell Line Expression Data")
    print("="*80)

    # Check files
    if not check_prerequisites():
        sys.exit(1)

    # Connect to database
    conn = sqlite3.connect(DB_PATH)

    # Get current status
    print(f"\n📊 Current Database Status:")
    print("-"*80)
    total, with_data, without_data = get_current_status(conn)
    print(f"   Total cell lines: {total}")
    print(f"   With expression data: {with_data}")
    print(f"   Missing expression data: {len(without_data)}")

    if not without_data:
        print("\n✅ All cell lines already have expression data!")
        conn.close()
        return

    print(f"\n   Missing samples: {', '.join(without_data[:10])}")
    if len(without_data) > 10:
        print(f"   ... and {len(without_data) - 10} more")

    # Ask for confirmation
    print(f"\n⚠️  This will load expression data for {len(without_data)} cell lines.")
    print(f"   (Aggregating replicate TPM values by mean)")
    response = input("   Continue? (yes/no): ")
    if response.lower() not in ['yes', 'y']:
        print("Cancelled.")
        conn.close()
        return

    # Get gene ID mapping
    print(f"\n🔍 Loading gene ID mapping...")
    gene_id_map = get_gene_id_map(conn)
    print(f"   Found {len(gene_id_map):,} genes")

    # Load data (long format)
    inserted = load_expression_data_long_format(conn, TPM_FILE, without_data, gene_id_map)

    # Verify results
    print(f"\n📊 Final Database Status:")
    print("-"*80)
    total, with_data, without_data = get_current_status(conn)
    print(f"   Total cell lines: {total}")
    print(f"   With expression data: {with_data}")
    print(f"   Missing expression data: {len(without_data)}")

    if without_data:
        print(f"\n   Still missing: {', '.join(without_data[:10])}")

    conn.close()

    if inserted > 0:
        print(f"\n✅ Successfully loaded {inserted:,} expression records!")
        print(f"\n🔄 Next: Test your query again:")
        print(f"   'EGFR levels in mutant cells'")
        print(f"   Expected: 7-8 mutation types (was 1)")
    else:
        print(f"\n⚠️  No data was loaded. Check the error messages above.")

if __name__ == "__main__":
    main()
