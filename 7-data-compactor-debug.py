"""
Debug version with row counting to identify where rows might be lost
"""

lang = "ro"

import os, csv, json, logging, argparse


# Configuration variables
input_csvs = "data/4-datasets/" + lang + "/"
json_metas = "data/2-metas/" + lang + "/"
compacted_folder = "data/5-compact-datasets/" + lang + "/"
logfile = "data/5-compact-datasets/" + lang+ "-compaction-debug.log"

# Setup logging
logging.basicConfig(filename=logfile, level=logging.INFO,
                    format='%(asctime)s [%(levelname)s] %(message)s')


def load_mapping_from_json(json_path):
    """
    Load dimension mappings from a JSON metadata file.
    Returns a tuple: (mapping, dim_labels_by_code)
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
                key = (dim_code, opt_label.strip().lower())
                mapping[key] = nom_item_id

    return mapping, dim_labels_by_code


def main():
    parser = argparse.ArgumentParser(description='Compact data from CSV files using JSON metadata')
    parser.add_argument('--matrix', type=str, help='Process only a specific matrix (fileid) for debugging')
    args = parser.parse_args()

    json_files = [f[:-5] for f in os.listdir(json_metas) if f.endswith('.json')]
    fileids_available = json_files

    if args.matrix:
        if args.matrix in fileids_available:
            fileids_available = [args.matrix]
            logging.info(f"Processing only matrix: {args.matrix}")
            print(f"Processing only matrix: {args.matrix}")
        else:
            logging.error(f"Matrix '{args.matrix}' not found in JSON metadata.")
            print(f"Error: Matrix '{args.matrix}' not found in JSON metadata folder.")
            return

    input_files = [f[:-4] for f in os.listdir(input_csvs) if f.endswith('.csv')]

    for f in input_files:
        if f not in fileids_available:
            logging.warning(f"File '{f}.csv' found in input folder but no matching JSON metadata.")

    for fileid in fileids_available:

        compacted_file = os.path.join(compacted_folder, f"{fileid}.csv")
        if os.path.exists(compacted_file):
            logging.info(f"Skipping '{fileid}.csv' because it is already compacted.")
            continue

        original_file = os.path.join(input_csvs, f"{fileid}.csv")
        if not os.path.exists(original_file):
            logging.warning(f"File '{fileid}.csv' has JSON metadata but not in input folder.")
            continue

        json_file = os.path.join(json_metas, f"{fileid}.json")
        if not os.path.exists(json_file):
            logging.warning(f"JSON metadata file '{fileid}.json' not found. Skipping.")
            continue

        try:
            mapping, dim_labels_by_code = load_mapping_from_json(json_file)
            logging.info(f"Loaded {len(mapping)} mapping entries for '{fileid}'")
            print(f"Loaded {len(mapping)} mapping entries for '{fileid}'")
        except Exception as e:
            logging.error(f"Error loading JSON metadata for '{fileid}.json': {e}")
            continue

        # Process the CSV with row counting
        os.makedirs(compacted_folder, exist_ok=True)

        print(f"Opening input file: {original_file}")
        rows_read = 0
        rows_written = 0

        try:
            with open(original_file, 'r', newline='', encoding='utf-8') as infile:
                reader = csv.reader(infile)
                header = next(reader)
                last_col_index = len(header) - 1

                print(f"Header has {len(header)} columns")
                print(f"Opening output file: {compacted_file}")

                with open(compacted_file, 'w', newline='', encoding='utf-8') as outfile:
                    writer = csv.writer(outfile)
                    writer.writerow(header)
                    rows_written += 1

                    for row_data in reader:
                        rows_read += 1

                        if rows_read % 1000000 == 0:
                            print(f"  Processed {rows_read:,} rows...")
                            logging.info(f"Processed {rows_read:,} rows for '{fileid}'")

                        if not row_data:
                            writer.writerow(row_data)
                            rows_written += 1
                            continue

                        new_row = row_data[:]
                        for col_index in range(0, last_col_index):
                            original_value = row_data[col_index]
                            cell_val_normalized = original_value.strip().lower()
                            dim_code = col_index + 1

                            if (dim_code, cell_val_normalized) in mapping:
                                new_row[col_index] = str(mapping[(dim_code, cell_val_normalized)])
                            else:
                                logging.warning(
                                    f"No match in metadata for '{fileid}.csv' at column '{header[col_index]}' "
                                    f"with value '{original_value}'. Leaving unchanged."
                                )

                        writer.writerow(new_row)
                        rows_written += 1

            print(f"Completed: Read {rows_read:,} rows, wrote {rows_written:,} rows (including header)")
            logging.info(f"Successfully processed '{fileid}.csv': read {rows_read:,} rows, wrote {rows_written:,} rows")

        except Exception as e:
            print(f"ERROR during processing: {e}")
            logging.error(f"Error processing '{fileid}.csv': {e}")
            import traceback
            traceback.print_exc()
            logging.error(traceback.format_exc())

    logging.info("Compaction process completed.")
    print("Compaction process completed.")


if __name__ == "__main__":
    main()
