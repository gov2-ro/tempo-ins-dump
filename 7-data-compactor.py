""" 
reads indexes from db (previously built from meta jsons
loops through the csv files, if a matching index is found, reads the csv, leaves header row and values for last columns untouched, but replaces the other values with nomitemId (if it matches* dim_label x opt_label) and writes the compacted data to a new file

**if no match is found, leaves the currerent columns untouched but writes the exception to a log file
also write a log entry for each succesful file matched and processed. if files are found in folder but are in the index, or vice-versa, write a warning tow to the log

"""

lang = "ro"
# lang = "en"

 

import os, csv, json, logging, argparse


# Configuration variables
input_csvs = "data/4-datasets/" + lang + "/"
json_metas = "data/2-metas/" + lang + "/"
compacted_folder = "data/5-compact-datasets/" + lang + "/"
logfile = "data/5-compact-datasets/" + lang+ "-compaction.log"

# Setup logging
logging.basicConfig(filename=logfile, level=logging.INFO,
                    format='%(asctime)s [%(levelname)s] %(message)s')


def load_mapping_from_json(json_path):
    """
    Load dimension mappings from a JSON metadata file.
    Returns a tuple: (mapping, dim_labels_by_code)
    - mapping: dict with key (dim_code, opt_label_lower) -> nomItemId
    - dim_labels_by_code: dict with key dim_code -> dim_label
    """
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    mapping = {}
    dim_labels_by_code = {}

    if 'dimensionsMap' in data:
        for dimension in data['dimensionsMap']:
            dim_code = dimension['dimCode']
            dim_label = dimension['label']
            dim_labels_by_code[dim_code] = dim_label

            for option in dimension['options']:
                opt_label = option['label']
                nom_item_id = option['nomItemId']
                # Normalize opt_label by stripping and lowercasing
                key = (dim_code, opt_label.strip().lower())
                mapping[key] = nom_item_id

    return mapping, dim_labels_by_code


def main():
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='Compact data from CSV files using JSON metadata')
    parser.add_argument('--matrix', type=str, help='Process only a specific matrix (fileid) for debugging')
    args = parser.parse_args()

    # Get list of JSON metadata files (these are the fileids)
    json_files = [f[:-5] for f in os.listdir(json_metas) if f.endswith('.json')]
    fileids_available = json_files

    # Filter to specific matrix if requested
    if args.matrix:
        if args.matrix in fileids_available:
            fileids_available = [args.matrix]
            logging.info(f"Processing only matrix: {args.matrix}")
        else:
            logging.error(f"Matrix '{args.matrix}' not found in JSON metadata. Available matrices: {', '.join(fileids_available[:10])}...")
            print(f"Error: Matrix '{args.matrix}' not found in JSON metadata folder.")
            return

    # Get list of csv files in input folder (without extension)
    input_files = [f[:-4] for f in os.listdir(input_csvs) if f.endswith('.csv')]

    # Check for files in folder but not in JSON metadata
    for f in input_files:
        if f not in fileids_available:
            logging.warning(f"File '{f}.csv' found in input folder but no matching JSON metadata.")

    # Process each fileid
    for fileid in fileids_available:

        compacted_file = os.path.join(compacted_folder, f"{fileid}.csv")
        if os.path.exists(compacted_file):
            # Already compacted
            logging.info(f"Skipping '{fileid}.csv' because it is already compacted.")
            continue

        original_file = os.path.join(input_csvs, f"{fileid}.csv")
        if not os.path.exists(original_file):
            # CSV does not exist in input, log warning
            logging.warning(f"File '{fileid}.csv' has JSON metadata but not in input folder.")
            continue

        # Load mappings from JSON metadata file
        json_file = os.path.join(json_metas, f"{fileid}.json")
        if not os.path.exists(json_file):
            logging.warning(f"JSON metadata file '{fileid}.json' not found. Skipping.")
            continue

        try:
            mapping, dim_labels_by_code = load_mapping_from_json(json_file)
        except Exception as e:
            logging.error(f"Error loading JSON metadata for '{fileid}.json': {e}")
            continue

        # Process the CSV
        os.makedirs(compacted_folder, exist_ok=True)
        rows_read = 0
        rows_written = 0

        with open(original_file, 'r', newline='', encoding='utf-8') as infile:
            reader = csv.reader(infile)
            header = next(reader)  # Read header line

            # The last column is the values column, do not modify it
            last_col_index = len(header) - 1

            with open(compacted_file, 'w', newline='', encoding='utf-8') as outfile:
                writer = csv.writer(outfile)

                # Write header unchanged
                writer.writerow(header)
                rows_written += 1

                # Process each data row
                for row_data in reader:
                    rows_read += 1

                    if not row_data:
                        # Empty line or something irregular
                        writer.writerow(row_data)
                        rows_written += 1
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
                                f"No match in metadata for '{fileid}.csv' at column '{header[col_index]}' "
                                f"with value '{original_value}'. Leaving unchanged."
                            )

                    # Write the processed row
                    writer.writerow(new_row)
                    rows_written += 1

        # Verify row counts match (rows_read doesn't include header, rows_written does)
        expected_output_rows = rows_read + 1  # +1 for header
        if rows_written == expected_output_rows:
            logging.info(f"Successfully processed and compacted '{fileid}.csv': {rows_read} data rows + header = {rows_written} total rows")
        else:
            logging.error(f"ROW COUNT MISMATCH for '{fileid}.csv': read {rows_read} data rows but wrote {rows_written} total rows (expected {expected_output_rows})")
            print(f"WARNING: Row count mismatch for {fileid}.csv - see log for details")

    logging.info("Compaction process completed.")


if __name__ == "__main__":
    main()
