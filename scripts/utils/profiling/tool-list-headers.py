import csv
import os
from pathlib import Path

input_folder = Path("data/4-datasets/ro")
output_folder = Path("data/2-csv-cols/ro")
output_folder.mkdir(parents=True, exist_ok=True)

for csv_file in input_folder.glob("*.csv"):
    with csv_file.open(newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        headers = next(reader)  # first row
    
    output_file = output_folder / f"{csv_file.stem}.txt"
    with output_file.open("w", encoding="utf-8") as out_f:
        out_f.write("\n".join(h.strip() for h in headers))

print("Done!")
