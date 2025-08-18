"""
Data Profiler for Romanian INS CSV Files

This script analyzes and profiles CSV files from the Romanian National Institute 
of Statistics (INS) tempo-online.insse.ro database. It performs validation checks
and detailed column profiling to understand the structure and content of datasets.

Key features:
- Validates CSV structure (checks for 'Valoare' column, UM/units column)
- Profiles each column with type detection (integer, float, percent, string, temporal)
- Detects and normalizes temporal columns (years, quarters, months)
- Analyzes unit of measurement (UM) column uniformity
- Optional integration with variable classification system
- Generates detailed CSV and JSON reports for further processing

The profiler is designed to handle the specific formatting conventions used
in Romanian statistical data, including period representations and unit labels.
"""

import pandas as pd
import os
import argparse
import logging
from tqdm import tqdm
import unicodedata
import re
import numpy as np
import json
from variable_classifier import classify_headers_in_file
from unit_classifier import UnitClassifier
from validation_rules import DataValidator
import math

# Suppress verbose logs from libraries to keep output clean
logging.basicConfig(level=logging.ERROR)

def convert_numpy_types(obj):
    """
    Recursively convert NumPy types to JSON-serializable Python types.
    
    Args:
        obj: Any object that might contain NumPy types
        
    Returns:
        Object with NumPy types converted to Python equivalents
    """
    if isinstance(obj, np.bool_):
        return bool(obj)
    elif isinstance(obj, np.integer):
        return int(obj)
    elif isinstance(obj, np.floating):
        return float(obj)
    elif isinstance(obj, np.ndarray):
        return obj.tolist()
    elif isinstance(obj, dict):
        return {key: convert_numpy_types(value) for key, value in obj.items()}
    elif isinstance(obj, list):
        return [convert_numpy_types(item) for item in obj]
    elif isinstance(obj, tuple):
        return tuple(convert_numpy_types(item) for item in obj)
    else:
        return obj

def trim_headers(cols):
    return [str(c).strip() for c in cols]

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
    Now uses the modular validation system for data quality checks.

    Args:
        file_path (str): The path to the input CSV file.

    Returns:
        tuple: (pd.DataFrame with profiling results, dict with file checks and validation results)
    """
    df = pd.read_csv(file_path)

    if df.empty:
        raise ValueError("CSV file is empty.")

    num_rows, num_cols = df.shape
    columns = df.columns

    # Trim header spaces for consistent handling
    columns = trim_headers(df.columns)
    df.columns = columns

    # --- 1. Use Modular Validation System ---
    validator = DataValidator()
    validation_summary = validator.validate_dataframe_summary(df, file_path)
    
    # Extract file_checks for backward compatibility
    file_checks = validation_summary.get("file_checks", {})
    
    # Add UM label extraction for backward compatibility
    um_col_name = None
    for col in columns:
        normalized = str(col).lower().strip()
        if normalized.startswith('um') or 'unitat' in normalized:
            um_col_name = col
            break
    
    if um_col_name:
        raw_h = str(um_col_name).strip()
        # Extract UM label from header (text after 'UM:' or 'Unitate de masura')
        s = re.sub(r'^(um[:\-\s]+)', '', raw_h, flags=re.I).strip()
        s = re.sub(r'^(unitati?|unitate)\s+(de\s+)?masura[:\-\s]*', '', s, flags=re.I).strip()
        file_checks["um_label"] = s if s else None
    else:
        file_checks["um_label"] = None
    
    # Add validation results to file_checks
    file_checks["validation_results"] = validation_summary.get("detailed_results", [])
    file_checks["validation_summary"] = validation_summary.get("validation_summary", {})

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
        luna = norm.str.contains(r'\bluna\b')

        total = len(norm)
        cnt_year_exact = int(year_exact.sum())
        cnt_year_with_anul = int(year_with_anul.sum())
        cnt_range = int(years_range.sum())
        cnt_trimestru = int(trimestru.sum())
        cnt_luna = int(luna.sum())

        # cleaned series: extract year when possible, or clean Luna prefix
        def extract_year(val: str) -> str:
            # For Luna patterns, remove "Luna " prefix but keep month + year
            if 'luna' in val.lower():
                cleaned_val = re.sub(r'^\s*luna\s+', '', val, flags=re.I).strip()
                return cleaned_val
            # For other patterns, extract just the year
            m = re.search(r'(\d{4})', val)
            return m.group(1) if m else val.strip()

        cleaned = s.map(lambda v: extract_year(v))

        # decide type
        # if most entries are luna -> 'luna'
        if total > 0 and (cnt_luna / total) >= 0.5:
            return cleaned, 'luna'
        
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

        # Override guessed type for UM column (check from validation results)
        is_um_column = False
        for validation_result in file_checks.get("validation_results", []):
            if (validation_result.get("rule_id") == "um_column_check" and 
                validation_result.get("column_name") == col_name):
                is_um_column = True
                break
        
        if is_um_column:
            guessed_type = 'um'

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
    
    return df_results, file_checks


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
    parser.add_argument(
        '--rules',
        default='rules-dictionaries/variable_classification_rules.csv',
        help='Path to variable classification rules CSV (used by orchestrator)'
    )
    parser.add_argument(
        '--unit-rules',
        default='rules-dictionaries/unit_rules.csv',
        help='Path to unit classification rules CSV (used by orchestrator)'
    )
    parser.add_argument(
        '--orchestrate',
        action='store_true',
        help='Also run variable classifier and write combined JSON outputs per CSV.'
    )
    parser.add_argument(
        '--combined_out',
        default='../data/profiling/combined/',
        help='Directory to write combined JSON outputs when --orchestrate is used.'
    )
    
    args = parser.parse_args()

    # Create output directory if it doesn't exist
    os.makedirs(args.output_dir, exist_ok=True)
    if args.orchestrate:
        os.makedirs(args.combined_out, exist_ok=True)
        try:
            unit_classifier = UnitClassifier(args.unit_rules)
        except Exception as e:
            print(f"Error initializing UnitClassifier: {e}")
            unit_classifier = None
    else:
        unit_classifier = None

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
                # tqdm.write(f"Skipping '{base_name}': Profile already exists. Use -f to overwrite.")
                continue

            # Generate the profile
            profile_out = profile_and_validate_csv(input_path)
            # Backward compatibility: profile_and_validate_csv now returns (df, file_checks)
            if isinstance(profile_out, tuple):
                profile_df, file_checks = profile_out
            else:
                profile_df, file_checks = profile_out, {
                    "last_col_is_valoare": None,
                    "um_col_exists": None,
                    "um_col_uniformity": None,
                    "um_value": None,
                }

            # Save the profile to a new CSV
            profile_df.to_csv(output_path, index=False, quoting=1)
            tqdm.write(f"Successfully generated profile for '{base_name}' -> '{output_path}'")

                # If requested, also classify headers and write combined JSON
            if args.orchestrate:
                try:
                    headers_class = classify_headers_in_file(input_path, args.rules)
                except Exception as e:
                    headers_class = {"error": str(e)}

                # Classify UM if possible
                if unit_classifier and file_checks.get("um_value") and file_checks["um_value"] != 'N/A':
                    try:
                        um_tags = unit_classifier.classify(file_checks["um_value"])
                        file_checks["um_classification"] = um_tags
                    except Exception as e:
                        file_checks["um_classification"] = f"Error: {e}"

                # Merge header classifications into per-column profile entries by column_name
                merged_profile = []
                # Build quick lookup from header label to classification
                class_map = {}
                if isinstance(headers_class, list):
                    for item in headers_class:
                        if isinstance(item, dict) and 'label' in item:
                            class_map[str(item['label']).strip()] = {
                                'semantic_categories': item.get('semantic_categories', ''),
                                'functional_types': item.get('functional_types', '')
                            }

                for rec in profile_df.to_dict(orient='records'):
                    name = str(rec.get('column_name', '')).strip()
                    cls = class_map.get(name, None)
                    if cls:
                        rec.update(cls)
                    # Drop non-relevant or NaN fields for cleaner JSON
                    uvc = rec.get('unique_values_count', None)
                    if (uvc is None) or (isinstance(uvc, float) and math.isnan(uvc)):
                        rec.pop('unique_values_count', None)
                    uvs = rec.get('unique_values_sample', None)
                    if uvs is None:
                        rec.pop('unique_values_sample', None)
                    merged_profile.append(rec)

                combined = {
                    "source_csv": os.path.abspath(input_path),
                    "file_checks": convert_numpy_types(file_checks),
                    "columns": merged_profile
                }

                combined_path = os.path.join(args.combined_out, os.path.splitext(base_name)[0] + '.json')
                with open(combined_path, 'w', encoding='utf-8') as cf:
                    json.dump(combined, cf, ensure_ascii=False, indent=2)
                    print(combined_path)
                # tqdm.write(f"Wrote combined JSON -> {combined_path}")

        except FileNotFoundError:
            tqdm.write(f"Error: Input file not found at '{input_path}'")
        except Exception as e:
            tqdm.write(f"Error processing '{base_name}': {e}")
            
    print("\nProfiling complete.")


if __name__ == "__main__":
    main()