""" 
reads indexes from db (previously built from meta jsons
loops through the csv files, if a matching index is found, reads the csv, leaves header row and values for last columns untouched, but replaces the other values with nomitemId (if it matches* dim_label x opt_label) and writes the compacted data to a new file

**if no match is found, leaves the currerent columns untouched but writes the exception to a log file
also write a log entry for each succesful file matched and processed. if files are found in folder but are in the index, or vice-versa, write a warning tow to the log

"""

lang = "ro"
# lang = "en"

 

import os, csv, sqlite3, logging
from tqdm import tqdm


# Configuration variables
input_csvs = "data/4-datasets/" + lang + "/"
db_path = "data/3-db/" + lang +  "/tempo-indexes.db"
db_table = 'fields'
compacted_folder = "data/5-compact-datasets/" + lang + "/"
logfile = "data/5-compact-datasets/" + lang+ "-compaction.log"

# Setup logging
logging.basicConfig(filename=logfile, level=logging.INFO,
                    format='%(asctime)s [%(levelname)s] %(message)s')


def main():
    # Connect to DB
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Get distinct fileids from the fields table
    cursor.execute(f"SELECT DISTINCT fileid FROM {db_table}")
    fileids_in_db = [row[0] for row in cursor.fetchall()]

    # Get list of csv files in input folder (without extension)
    input_files = [f[:-4] for f in os.listdir(input_csvs) if f.endswith('.csv')]
    
    # Check for files in folder but not in DB
    for f in input_files:
        if f not in fileids_in_db:
            logging.warning(f"File '{f}.csv' found in input folder but not in the DB index.")

    # Process each fileid
    for fileid in tqdm(fileids_in_db, desc="Processing files"):

        compacted_file = os.path.join(compacted_folder, f"{fileid}.csv")
        if os.path.exists(compacted_file):
            # Already compacted
            logging.info(f"Skipping '{fileid}.csv' because it is already compacted.")
            continue

        original_file = os.path.join(input_csvs, f"{fileid}.csv")
        if not os.path.exists(original_file):
            # CSV does not exist in input, log warning
            logging.warning(f"File '{fileid}.csv' present in DB index but not in input folder.")
            continue

        # Retrieve all field mappings for this fileid
        # We'll store them in a dictionary keyed by (dim_code, opt_label_lower)
        cursor.execute(f"SELECT dim_label, dimCode, opt_label, nomItemId FROM {db_table} WHERE fileid=?",
                       (fileid,))
        rows = cursor.fetchall()

        mapping = {}
        dim_labels_by_code = {}
        for dim_label, dim_code, opt_label, nom_item_id in rows:
            dim_labels_by_code[dim_code] = dim_label
            # Normalize opt_label by stripping and lowercasing
            key = (dim_code, opt_label.strip().lower())
            mapping[key] = nom_item_id

        # Process the CSV
        os.makedirs(compacted_folder, exist_ok=True)
        with open(original_file, 'r', newline='', encoding='utf-8') as infile:
            reader = csv.reader(infile)
            header = next(reader)  # Read header line

            # The last column is the values column, do not modify it
            last_col_index = len(header) - 1

            with open(compacted_file, 'w', newline='', encoding='utf-8') as outfile:
                writer = csv.writer(outfile)

                # Write header unchanged
                writer.writerow(header)

                # Process each data row
                for row_data in reader:
                    if not row_data:
                        # Empty line or something irregular
                        writer.writerow(row_data)
                        continue

                    new_row = row_data[:]
                    # Replace values except in the last column
                    for col_index in range(0, last_col_index):
                        original_value = row_data[col_index]
                        # Normalize the cell value for matching
                        cell_val_normalized = original_value.strip().lower()
                        dim_code = col_index + 1  # since dimCode is 1-based
                        
                        if (dim_code, cell_val_normalized) in mapping:
                            new_row[col_index] = str(mapping[(dim_code, cell_val_normalized)])
                        else:
                            # No match found, leave unchanged but log a warning
                            logging.warning(
                                f"No match in DB for '{fileid}.csv' at column '{header[col_index]}' "
                                f"with value '{original_value}'. Leaving unchanged."
                            )

                    # Write the processed row
                    writer.writerow(new_row)

        logging.info(f"Successfully processed and compacted '{fileid}.csv' into '{compacted_file}'")

    conn.close()
    logging.info("Compaction process completed.")


if __name__ == "__main__":
    main()
