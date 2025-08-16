""" 
if it has more than 15 rows, only keep middle 5, first and last 5 rows, write to folder with the same name as target
"""

import csv
import os
from pathlib import Path

input_folder = Path("data/4-datasets/ro")
output_folder = Path("data/datasets-samples/ro")
output_folder.mkdir(parents=True, exist_ok=True)

csv_files = list(input_folder.glob("*.csv"))
print(f"Found {len(csv_files)} CSV files to process...")

for i, csv_file in enumerate(csv_files, 1):
    with csv_file.open(newline="", encoding="utf-8") as f:
        reader = list(csv.reader(f))
    
    header, rows = reader[0], reader[1:]
    row_count = len(rows)

    if row_count > 15:
        first5 = rows[:5]
        last5 = rows[-5:]
        middle_start = (row_count - 5) // 2
        middle5 = rows[middle_start:middle_start + 5]
        sampled_rows = first5 + middle5 + last5
        # print(f"{i:4d}/{len(csv_files)}: {csv_file.name} ({row_count} rows → 15 rows)")
    else:
        sampled_rows = rows
        print(f"{i:4d}/{len(csv_files)}: {csv_file.name} ({row_count} rows → kept all)")

    out_path = output_folder / csv_file.name
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(sampled_rows)

print(f"\nSampling complete! Processed {len(csv_files)} files.")
