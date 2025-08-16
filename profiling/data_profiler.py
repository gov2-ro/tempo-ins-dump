import pandas as pd
import os
import argparse
import logging
from tqdm import tqdm
import unicodedata
import re
import numpy as np

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
    # Normalize header names for robust matching
    def normalize_header(h: str) -> str:
        h = str(h)
        h = unicodedata.normalize('NFKD', h).encode('ascii', 'ignore').decode('ascii')
        h = h.lower().strip()
        h = re.sub(r"[^a-z0-9:_ ]+", '', h)
        h = re.sub(r"\s+", ' ', h)
        return h

    normalized_headers = [normalize_header(h) for h in columns]

    # Detect last column being 'valoare' either by header or by content (numeric)
    last_col_name = columns[-1]
    normalized_last = normalize_header(last_col_name)
    # consider header match OR if the last column is mostly numeric -> treat as 'Valoare'
    try:
        last_col_numeric_frac = pd.to_numeric(df[last_col_name], errors='coerce').notnull().mean()
    except Exception:
        last_col_numeric_frac = 0.0

    check_valoare = (normalized_last == 'valoare') or normalized_last.startswith('valoare') or (last_col_numeric_frac >= 0.9)

    # Detect UM column: prefer penultimate, otherwise search headers
    um_col_name = None
    penultimate_header = columns[-2]
    penultimate_norm = normalize_header(penultimate_header)

    if penultimate_norm.startswith('um') or penultimate_norm.startswith('um:') or penultimate_norm in ('unitati de masura', 'unitate de masura', 'unitati_masura'):
        um_col_name = penultimate_header
    else:
        # search headers for something that starts with 'um' or contains 'unitat'
        for orig, norm in zip(columns, normalized_headers):
            if norm.startswith('um') or 'unitat' in norm or norm.startswith('unitati'):
                um_col_name = orig
                break

    check_um_exists = um_col_name is not None

    # Check UM column uniformity and extract representative unit value
    um_uniformity = 'N/A'
    um_value = 'N/A'
    if check_um_exists:
        # Work with non-null values as strings
        um_series_raw = df[um_col_name].dropna().astype(str)

        if um_series_raw.empty:
            um_uniformity = 'No values'
        else:
            # Normalize unit values (remove 'UM:' prefix, collapse spaces, lowercase)
            def normalize_um_value(s: str) -> str:
                s = str(s).strip()
                s = unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode('ascii')
                # drop leading 'UM:' or similar labels
                s = re.sub(r'^(um[:\-\s]+)', '', s, flags=re.I)
                s = s.lower().strip()
                s = re.sub(r"[^a-z0-9 ]+", ' ', s)
                s = re.sub(r"\s+", ' ', s)
                return s

            normalized_values = um_series_raw.map(normalize_um_value)
            # remove empty strings
            valid = normalized_values.replace('', np.nan).dropna()

            if valid.empty:
                um_uniformity = 'No non-empty values'
            else:
                counts = valid.value_counts()
                top_norm = counts.index[0]
                top_count = counts.iloc[0]
                frac = top_count / len(valid)

                if frac >= 0.95:
                    um_uniformity = 'Uniform'
                    # pick the most common original raw value for that normalized value
                    mask = normalized_values == top_norm
                    try:
                        candidate = um_series_raw[mask].str.strip().mode().iloc[0]
                    except Exception:
                        candidate = um_series_raw[mask].iloc[0].strip()
                    # remove leading UM label if present
                    candidate = re.sub(r'^(um[:\-\s]+)', '', candidate, flags=re.I).strip()
                    um_value = candidate
                else:
                    um_uniformity = 'Not Uniform'
                    # report top 3 original raw values (stripped)
                    top_raw = um_series_raw.str.strip().value_counts().index[:3].tolist()
                    top_raw = [re.sub(r'^(um[:\-\s]+)', '', t, flags=re.I).strip() for t in top_raw]
                    um_value = ', '.join(top_raw)

    # provide debug: if penultimate header looked like 'um' but was detected incorrectly due to spaces, log normalized headers
    # (kept here for maintainers; not printed normally)

    # --- 2. Profile Each Column ---
    # helper to detect period-like formats and return cleaned series + inferred period type
    def detect_and_clean_period_series(series: pd.Series):
        # work on non-null string representations
        s = series.dropna().astype(str).map(lambda x: unicodedata.normalize('NFKD', x).encode('ascii', 'ignore').decode('ascii').strip())
        if s.empty:
            return None, None

        norm = s.str.lower()
        # patterns
        year_exact = norm.str.match(r'^\d{4}$')
        year_with_anul = norm.str.contains(r'\banul\b\s*\d{4}')
        years_range = norm.str.contains(r'\b\d{4}\s*-\s*\d{4}\b') | norm.str.contains(r'anii\b')
        trimestru = norm.str.contains(r'trimestrul')

        total = len(norm)
        cnt_year_exact = int(year_exact.sum())
        cnt_year_with_anul = int(year_with_anul.sum())
        cnt_range = int(years_range.sum())
        cnt_trimestru = int(trimestru.sum())

        # cleaned series: extract year when possible
        def extract_year(val: str) -> str:
            m = re.search(r'(\d{4})', val)
            return m.group(1) if m else val.strip()

        cleaned = s.map(lambda v: extract_year(v))

        # decide type
        # if most entries are trimestru -> 'trimestru'
        if total > 0 and (cnt_trimestru / total) >= 0.5:
            return cleaned, 'trimestru'

        # if large majority are year-like (exact or with 'anul') and no ranges -> 'year'
        if total > 0 and ((cnt_year_exact + cnt_year_with_anul) / total) >= 0.9 and cnt_range == 0:
            return cleaned, 'year'

        # if mixed (years + ranges or other) -> 'year+'
        if total > 0 and ((cnt_year_exact + cnt_year_with_anul + cnt_range) / total) >= 0.5:
            return cleaned, 'year+'

        return None, None

    results = []
    for i, col_name in enumerate(columns):
        column_data = df[col_name]

        # First, try to detect special period-like columns and get cleaned values
        cleaned_series, period_type = (None, None)
        if column_data.dtype == 'object' or pd.api.types.is_string_dtype(column_data):
            try:
                cleaned_series, period_type = detect_and_clean_period_series(column_data)
            except Exception:
                cleaned_series, period_type = None, None

        if period_type is not None:
            # use cleaned series (years) to decide numeric types, but set guessed_type to the period type
            guessed_type = period_type
            # for downstream cardinality/sample use cleaned values
            use_series_for_sample = cleaned_series
        else:
            guessed_type = guess_column_type(column_data)
            use_series_for_sample = column_data

        nunique = None
        options_sample = None

        if guessed_type in ["string", "empty"] or period_type is not None:
            # compute unique/sample on cleaned or original string values
            nunique = use_series_for_sample.nunique()
            if nunique <= 15:
                options_sample = ' | '.join(map(str, use_series_for_sample.dropna().unique()))
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