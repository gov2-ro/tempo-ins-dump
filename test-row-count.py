#!/usr/bin/env python3
"""
Diagnostic script to compare row processing between DB and JSON versions
"""

import csv
import json
import sqlite3

fileid = "POP107D"
lang = "ro"

# Paths
input_csv = f"data/4-datasets/{lang}/{fileid}.csv"
json_meta = f"data/2-metas/{lang}/{fileid}.json"
db_path = f"data/3-db/{lang}/tempo-indexes.db"

print(f"\n{'='*60}")
print(f"Diagnostic Test for {fileid}")
print(f"{'='*60}\n")

# Count rows in input CSV
print("1. Counting rows in input CSV...")
with open(input_csv, 'r', encoding='utf-8') as f:
    reader = csv.reader(f)
    header = next(reader)
    row_count = sum(1 for row in reader)
    print(f"   Input CSV: {row_count + 1} total rows (including header)")
    print(f"   Columns: {len(header)}")

# Check JSON metadata
print("\n2. Checking JSON metadata...")
try:
    with open(json_meta, 'r', encoding='utf-8') as f:
        json_data = json.load(f)

    if 'dimensionsMap' in json_data:
        dims = json_data['dimensionsMap']
        print(f"   JSON dimensions: {len(dims)}")
        for dim in dims:
            opt_count = len(dim.get('options', []))
            print(f"     - Dim {dim['dimCode']}: {opt_count} options")

        # Build JSON mapping
        json_mapping = {}
        for dimension in dims:
            dim_code = dimension['dimCode']
            for option in dimension['options']:
                opt_label = option['label']
                nom_item_id = option['nomItemId']
                key = (dim_code, opt_label.strip().lower())
                json_mapping[key] = nom_item_id
        print(f"   Total JSON mapping entries: {len(json_mapping)}")
    else:
        print("   WARNING: No 'dimensionsMap' in JSON!")
except Exception as e:
    print(f"   ERROR reading JSON: {e}")

# Check DB metadata
print("\n3. Checking DB metadata...")
try:
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM fields WHERE fileid=?", (fileid,))
    db_count = cursor.fetchone()[0]
    print(f"   DB entries for {fileid}: {db_count}")

    cursor.execute("SELECT DISTINCT dimCode FROM fields WHERE fileid=? ORDER BY dimCode", (fileid,))
    dim_codes = [row[0] for row in cursor.fetchall()]
    print(f"   DB dimensions: {len(dim_codes)}")

    for dim_code in dim_codes:
        cursor.execute("SELECT COUNT(*) FROM fields WHERE fileid=? AND dimCode=?", (fileid, dim_code))
        opt_count = cursor.fetchone()[0]
        print(f"     - Dim {dim_code}: {opt_count} options")

    # Build DB mapping
    cursor.execute("SELECT dimCode, opt_label, nomItemId FROM fields WHERE fileid=?", (fileid,))
    db_rows = cursor.fetchall()

    db_mapping = {}
    for dim_code, opt_label, nom_item_id in db_rows:
        key = (dim_code, opt_label.strip().lower())
        db_mapping[key] = nom_item_id
    print(f"   Total DB mapping entries: {len(db_mapping)}")

    conn.close()
except Exception as e:
    print(f"   ERROR reading DB: {e}")

# Compare mappings
print("\n4. Comparing mappings...")
json_keys = set(json_mapping.keys())
db_keys = set(db_mapping.keys())

only_in_db = db_keys - json_keys
only_in_json = json_keys - db_keys
in_both = db_keys & json_keys

print(f"   Keys in both: {len(in_both)}")
print(f"   Only in DB: {len(only_in_db)}")
print(f"   Only in JSON: {len(only_in_json)}")

if only_in_db:
    print(f"\n   First 10 keys only in DB:")
    for key in list(only_in_db)[:10]:
        print(f"     {key}")

if only_in_json:
    print(f"\n   First 10 keys only in JSON:")
    for key in list(only_in_json)[:10]:
        print(f"     {key}")

# Sample test: Process first 1000 rows to see if there's a pattern
print("\n5. Testing first 1000 data rows...")
with open(input_csv, 'r', encoding='utf-8') as f:
    reader = csv.reader(f)
    header = next(reader)

    json_match_count = 0
    db_match_count = 0
    no_match_count = 0

    for i, row in enumerate(reader):
        if i >= 1000:
            break

        if not row:
            continue

        last_col_index = len(header) - 1
        row_has_json_match = True
        row_has_db_match = True

        for col_index in range(0, last_col_index):
            value = row[col_index].strip().lower()
            dim_code = col_index + 1
            key = (dim_code, value)

            if key not in json_mapping:
                row_has_json_match = False
            if key not in db_mapping:
                row_has_db_match = False

        if row_has_json_match:
            json_match_count += 1
        if row_has_db_match:
            db_match_count += 1
        if not row_has_json_match and not row_has_db_match:
            no_match_count += 1

print(f"   Rows with all values in JSON: {json_match_count}/1000")
print(f"   Rows with all values in DB: {db_match_count}/1000")
print(f"   Rows with no matches: {no_match_count}/1000")

print(f"\n{'='*60}\n")
