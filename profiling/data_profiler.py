import pandas as pd
import os
import argparse
import logging
from tqdm import tqdm

# Suppress verbose logs from libraries to keep output clean
logging.basicConfig(level=logging.ERROR)

def guess_column_type(column: pd.Series) -> str:
    """
    Analyzes the content of a pandas Series to guess its data type.
    Priority: percent > float > integer > string.
    """
    # Drop missing values to not interfere with type checking
    col_non_null = column.dropna()

    if col_non_null.empty:
        return "empty"

    # 1. Check for Percentage type (strings ending in '%')
    if col_non_null.dtype == 'object':
        try:
            # Check if all non-null values are strings ending with '%' and the rest is numeric
            if col_non_null.str.endswith('%').all():
                pd.to_numeric(col_non_null.str.rstrip('%'))
                return "percent"
        except (AttributeError, ValueError):
            # Not all values are strings or the part before '%' is not numeric
            pass

    # 2. Try to convert to numeric, coercing errors to NaN
    col_numeric = pd.to_numeric(col_non_null, errors='coerce')
    
    # If all original non-null values became null after coercion, it's a string column
    if col_numeric.isnull().all():
        return "string"

    # 3. Check for Float type
    # If the coerced numeric series contains any non-integer value, it's a float.
    if (col_numeric != col_numeric.round()).any():
        return "float"
        
    # 4. Check for Integer type
    # If all numeric values are whole numbers, it's an integer.
    if col_numeric.notnull().all():
        return "integer"

    # 5. Fallback to String
    return "string"


def profile_and_validate_csv(file_path: str):
    """
    Performs validation checks and profiles each column of a given CSV file.

    Args:
        file_path (str): The path to the input CSV file.

    Returns:
        pd.DataFrame: A DataFrame containing the profiling results.
    """
    df = pd.read_csv(file_path)

    if df.empty:
        raise ValueError("CSV file is empty.")

    num_rows, num_cols = df.shape
    columns = df.columns

    # --- 1. Perform File-Level Validity Checks ---
    last_col_name = columns[-1]
    um_col_name = columns[-2]

    # Check 1: Last column name
    check_valoare = (last_col_name == 'Valoare')

    # Check 2: UM column name
    check_um_exists = um_col_name.startswith('UM:') or um_col_name == 'Unitati de masura'

    # Check 3: UM column uniformity
    um_uniformity = "N/A"
    um_value = "N/A"
    if check_um_exists:
        is_uniform = df[um_col_name].nunique() == 1
        um_uniformity = "Uniform" if is_uniform else "Not Uniform"
        if is_uniform:
            um_value = df[um_col_name].dropna().unique()[0]

    # --- 2. Profile Each Column ---
    results = []
    for i, col_name in enumerate(columns):
        column_data = df[col_name]
        
        guessed_type = guess_column_type(column_data)
        
        nunique = None
        options_sample = None
        
        if guessed_type in ["string", "empty"]:
            nunique = column_data.nunique()
            # Provide a sample of unique values if cardinality is low
            if nunique <= 15:
                options_sample = ' | '.join(map(str, column_data.dropna().unique()))
            else:
                options_sample = f"High cardinality ({nunique})"

        results.append({
            "column_index": i,
            "column_name": col_name,
            "guessed_type": guessed_type,
            "unique_values_count": nunique,
            "unique_values_sample": options_sample
        })
        
    # Convert per-column results to DataFrame
    df_results = pd.DataFrame(results)

    # Append file-level checks as summary rows at the end of the file
    summary_rows = [
        {"column_index": "", "column_name": "last_col_is_valoare", "guessed_type": str(check_valoare), "unique_values_count": "", "unique_values_sample": ""},
        {"column_index": "", "column_name": "um_col_exists", "guessed_type": str(check_um_exists), "unique_values_count": "", "unique_values_sample": ""},
        {"column_index": "", "column_name": "um_col_uniformity", "guessed_type": um_uniformity, "unique_values_count": "", "unique_values_sample": ""},
        {"column_index": "", "column_name": "um_value", "guessed_type": str(um_value), "unique_values_count": "", "unique_values_sample": ""},
    ]

    summary_df = pd.DataFrame(summary_rows)

    return pd.concat([df_results, summary_df], ignore_index=True)


def main():
    """Main function to run the script from the command line."""
    parser = argparse.ArgumentParser(
        description="Validate and profile the data within a Romanian INS-style CSV file."
    )
    parser.add_argument(
        'input_paths',
        nargs='+',
        help="Path(s) to the input CSV file(s) or directories containing CSVs."
    )
    parser.add_argument(
        '-o', '--output_dir',
        default='../data/profiling/datasets/',
        help="Directory to save the output CSV profile reports."
    )
    parser.add_argument(
        '-f', '--force',
        action='store_true',
        help="Force overwrite of existing profile reports."
    )
    
    args = parser.parse_args()

    # Create output directory if it doesn't exist
    os.makedirs(args.output_dir, exist_ok=True)

    # --- Collect all CSV files from the input paths ---
    all_csv_files = []
    for path in args.input_paths:
        if os.path.isdir(path):
            # If the path is a directory, find all CSV files within it
            for filename in os.listdir(path):
                if filename.lower().endswith('.csv'):
                    all_csv_files.append(os.path.join(path, filename))
        elif os.path.isfile(path) and path.lower().endswith('.csv'):
            # If the path is a single CSV file, add it to the list
            all_csv_files.append(path)
        else:
            tqdm.write(f"Warning: Skipping '{path}' as it is not a valid CSV file or directory.")

    if not all_csv_files:
        print("No CSV files found in the specified paths. Exiting.")
        return

    print(f"Found {len(all_csv_files)} CSV file(s) to process...")
    
    for input_path in tqdm(all_csv_files, desc="Profiling Files"):
        try:
            base_name = os.path.basename(input_path)
            output_filename = f"{os.path.splitext(base_name)[0]}_profile.csv"
            output_path = os.path.join(args.output_dir, output_filename)

            if os.path.exists(output_path) and not args.force:
                tqdm.write(f"Skipping '{base_name}': Profile already exists. Use -f to overwrite.")
                continue

            # Generate the profile
            profile_df = profile_and_validate_csv(input_path)
            
            # Save the profile to a new CSV
            profile_df.to_csv(output_path, index=False, quoting=1)
            tqdm.write(f"Successfully generated profile for '{base_name}' -> '{output_path}'")

        except FileNotFoundError:
            tqdm.write(f"Error: Input file not found at '{input_path}'")
        except Exception as e:
            tqdm.write(f"Error processing '{base_name}': {e}")
            
    print("\nProfiling complete.")


if __name__ == "__main__":
    main()