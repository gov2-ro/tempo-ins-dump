""" 
### todo

- [ ] count cells
- [x] query Localitati Judete
- [ ] handle batch partial donwloads for larger than 30k cells

- [ ] add description ?
- [x] add progress bar
- [x] add Excel/HTML table download functionality
- [x] add flag to control Excel downloads (disabled by default)
- [ ] fails at bigger downloads
    - [x] detect empty datasets
    - [ ] split larger downloads into options then recombine - detect filters with 3 options (one is total so 2) or max 5 options in order of number of options excluding last field with UM


Usage:
    python 6-fetch-csv.py                          # Downloads CSV files for all matrices
    python 6-fetch-csv.py --xls                    # Downloads both CSV and Excel/HTML for all matrices
    python 6-fetch-csv.py --matrix POP107D         # Downloads CSV for a specific matrix
    python 6-fetch-csv.py --matrix POP107D --xls   # Downloads both formats for a specific matrix
    python 6-fetch-csv.py --force                  # Force overwrite existing files
    python 6-fetch-csv.py --matrix POP107D --force --xls # Downloads specific matrix, both formats, overwriting existing files

Notes:
- CSV files are saved to data/4-datasets/{lang}/
- Excel files (actually HTML tables) are saved to data/4-datasets/xls/ (only when --xls flag is used)
- By default, only CSV files are downloaded. Use --xls flag to also download Excel/HTML files.
"""

lang = "ro"
# lang = "en"

""" 
y not go through indexes/matrices.csv ? - flag?
"""

input_folder="data/2-metas/" + lang
output_folder="data/4-datasets/" + lang
xls_output_folder="data/4-datasets/xls"

import requests
import json
import time
from urllib3.exceptions import InsecureRequestWarning
import logging
from typing import Dict, List, Any, Optional
import os
import pathlib
import argparse
from tqdm import tqdm
import csv
import copy

# Suppress only the single InsecureRequestWarning
requests.packages.urllib3.disable_warnings(category=InsecureRequestWarning)

# Set up logging
logging.basicConfig(level=logging.INFO,
                   format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Set up file logging for empty dataset warnings
log_folder = "data/logs"
os.makedirs(log_folder, exist_ok=True)
file_handler = logging.FileHandler(os.path.join(log_folder, 'fetch-csv.log'), encoding='utf-8')
file_handler.setLevel(logging.WARNING)
file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logger.addHandler(file_handler)

# Set up logging for Judet-split datasets
judet_split_log_file = os.path.join(log_folder, 'judet-split-datasets.log')
judet_split_logger = logging.FileHandler(judet_split_log_file, encoding='utf-8')
judet_split_logger.setLevel(logging.INFO)
judet_split_logger.setFormatter(logging.Formatter('%(asctime)s - %(message)s'))
judet_logger = logging.getLogger('judet_split')
judet_logger.addHandler(judet_split_logger)
judet_logger.setLevel(logging.INFO)

# Set up logging for oversized datasets (exceed cell limit)
oversized_log_file = os.path.join(log_folder, 'oversized-datasets.log')
oversized_logger_handler = logging.FileHandler(oversized_log_file, encoding='utf-8')
oversized_logger_handler.setLevel(logging.WARNING)
oversized_logger_handler.setFormatter(logging.Formatter('%(asctime)s - %(message)s'))
oversized_logger = logging.getLogger('oversized')
oversized_logger.addHandler(oversized_logger_handler)
oversized_logger.setLevel(logging.WARNING)

def load_matrix_definition(file_path: str) -> Dict:
    """Load and parse the matrix definition file."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        tqdm.write(f"Error loading matrix definition: {e}")
        raise

def encode_query_parameters(matrix_def: Dict, include_totals: bool = False) -> str:
    """
    Convert matrix definition to encoded query format.
    Format: dimension1:value1,value2:value3,value4:...

    Args:
        matrix_def: Matrix definition dictionary
        include_totals: If False, filter out "Total" options when alternatives exist.
                       If True, include all options including "Total".
    """
    encoded_parts = []

    for dim in matrix_def["dimensionsMap"]:
        options = dim["options"]

        # Filter out "Total" options when there are alternatives (unless include_totals=True)
        if len(options) > 1 and not include_totals:
            options = [opt for opt in options if opt["label"].strip().lower() != "total"]

        if options:
            # Add nomItemIds for this dimension
            item_ids = [str(opt["nomItemId"]) for opt in options]
            encoded_parts.append(",".join(item_ids))

    # Join all parts with colon
    return ":".join(encoded_parts)

def count_csv_rows(file_path: str) -> int:
    """
    Count the number of data rows in a CSV file (excluding header).

    Args:
        file_path: Path to the CSV file

    Returns:
        Number of data rows (0 if only header exists)
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            # Count non-empty lines, excluding the header
            data_rows = len([line for line in lines[1:] if line.strip()])
            return data_rows
    except Exception as e:
        logger.error(f"Error counting rows in {file_path}: {e}")
        return -1

def calculate_cell_count(matrix_def: Dict, include_totals: bool = False) -> int:
    """
    Calculate the total number of cells that would be requested.
    Formula: multiply the count of options for each dimension.

    Args:
        matrix_def: Matrix definition dictionary
        include_totals: If False, exclude "Total" options from count

    Returns:
        Total number of cells
    """
    total_cells = 1
    dimension_counts = []

    for dim in matrix_def["dimensionsMap"]:
        options = dim["options"]

        # Filter out "Total" options if requested
        if not include_totals and len(options) > 1:
            options = [opt for opt in options if opt["label"].strip().lower() != "total"]

        option_count = len(options)
        dimension_counts.append((dim.get("label", "Unknown"), option_count))
        total_cells *= option_count

    return total_cells

def load_siruta_mapping() -> Dict[str, str]:
    """
    Load SIRUTA to Judet mapping from data/meta/uat-siruta.csv

    Returns:
        Dictionary mapping SIRUTA code to Judet name
    """
    siruta_file = "data/meta/uat-siruta.csv"
    siruta_map = {}

    try:
        with open(siruta_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                siruta_code = row['SIRUTA'].strip()
                judet_name = row['Judet'].strip()
                siruta_map[siruta_code] = judet_name

        logger.info(f"Loaded {len(siruta_map)} SIRUTA to Judet mappings")
        return siruta_map
    except Exception as e:
        logger.error(f"Error loading SIRUTA mapping: {e}")
        raise

def has_judete_and_localitati(matrix_def: Dict) -> tuple[bool, Optional[Dict], Optional[Dict]]:
    """
    Check if matrix definition has both 'Judete' and 'Localitati' dimensions.

    Args:
        matrix_def: Matrix definition dictionary

    Returns:
        Tuple of (has_both, judete_dim, localitati_dim)
    """
    judete_dim = None
    localitati_dim = None

    for dim in matrix_def.get("dimensionsMap", []):
        label = dim.get("label", "").strip().lower()
        if label == "judete":
            judete_dim = dim
        elif label in ["localitati", "localitati "]:  # Handle trailing space
            localitati_dim = dim

    has_both = judete_dim is not None and localitati_dim is not None
    return has_both, judete_dim, localitati_dim

def extract_siruta_from_label(label: str) -> Optional[str]:
    """
    Extract SIRUTA code from a locality label.
    Format: "1017 MUNICIPIUL ALBA IULIA" -> "1017"

    Args:
        label: Locality label

    Returns:
        SIRUTA code or None if not found
    """
    parts = label.strip().split()
    if parts and parts[0].isdigit():
        return parts[0]
    return None

def group_localities_by_judet(localitati_dim: Dict, judete_dim: Dict, siruta_map: Dict[str, str]) -> Dict[str, List[Dict]]:
    """
    Group localities by their Judet using SIRUTA codes.

    Args:
        localitati_dim: Localitati dimension dictionary
        judete_dim: Judete dimension dictionary
        siruta_map: SIRUTA to Judet mapping

    Returns:
        Dictionary mapping Judet nomItemId to list of locality options
    """
    # Create mapping of Judet names to their nomItemId (case-insensitive)
    judet_name_to_id = {}
    for opt in judete_dim.get("options", []):
        judet_label = opt.get("label", "").strip()
        if judet_label.lower() != "total":
            # Store both original and lowercase for matching
            judet_name_to_id[judet_label.lower()] = {
                'nomItemId': opt["nomItemId"],
                'original_name': judet_label
            }

    # Group localities by Judet
    judet_localities = {}
    unmatched_localities = []

    for locality_opt in localitati_dim.get("options", []):
        label = locality_opt.get("label", "").strip()

        # Skip TOTAL
        if label.upper() == "TOTAL":
            continue

        # Extract SIRUTA code
        siruta_code = extract_siruta_from_label(label)
        if not siruta_code:
            unmatched_localities.append(label)
            continue

        # Find Judet for this SIRUTA code
        judet_name_from_csv = siruta_map.get(siruta_code)
        if not judet_name_from_csv:
            unmatched_localities.append(f"{label} (SIRUTA: {siruta_code})")
            continue

        # Find Judet nomItemId (case-insensitive lookup)
        judet_info = judet_name_to_id.get(judet_name_from_csv.lower())
        if not judet_info:
            unmatched_localities.append(f"{label} -> {judet_name_from_csv} (no ID)")
            continue

        judet_id = judet_info['nomItemId']
        judet_name = judet_info['original_name']

        # Add to group
        if judet_id not in judet_localities:
            judet_localities[judet_id] = {
                'judet_name': judet_name,
                'judet_id': judet_id,
                'localities': []
            }
        judet_localities[judet_id]['localities'].append(locality_opt)

    if unmatched_localities:
        logger.warning(f"Could not match {len(unmatched_localities)} localities to Judete")
        for unmatched in unmatched_localities[:10]:  # Log first 10
            logger.debug(f"  Unmatched: {unmatched}")

    return judet_localities

def convert_to_pivot_payload(matrix_def: Dict, matrix_code: str, include_totals: bool = False) -> Dict:
    """
    Convert matrix definition to pivot API payload format.

    Args:
        matrix_def: Matrix definition dictionary
        matrix_code: The matrix code
        include_totals: If True, include "Total" options in the query
    """
    # encoded_query = encode_query_parameters(matrix_def, include_totals=include_totals)
    encoded_query = encode_query_parameters(matrix_def, include_totals=include_totals)

    payload = {
        "language": "ro",
        "encQuery": encoded_query,
        "matCode": matrix_code,
        "matMaxDim": matrix_def["details"]["matMaxDim"],
        "matUMSpec": matrix_def["details"]["matUMSpec"],
        "matRegJ": matrix_def["details"].get("matRegJ", 0)  # Default to 0 if not present
    }

    return payload

def fetch_by_judet_split(matrix_code: str, matrix_def: Dict, output_dir: str,
                         judete_dim: Dict, localitati_dim: Dict, siruta_map: Dict[str, str]) -> bool:
    """
    Fetch data by splitting into per-Judet requests.
    Saves partial files and combines them into the final CSV.

    Args:
        matrix_code: The matrix code
        matrix_def: Matrix definition dictionary
        output_dir: Output directory
        judete_dim: Judete dimension dictionary
        localitati_dim: Localitati dimension dictionary
        siruta_map: SIRUTA to Judet mapping

    Returns:
        True if successful, False otherwise
    """
    # Create partial files directory
    partial_dir = "data/4-datasets/judet-localitate"
    os.makedirs(partial_dir, exist_ok=True)

    # Group localities by Judet
    tqdm.write(f"Grouping localities by Judet for {matrix_code}...")
    judet_groups = group_localities_by_judet(localitati_dim, judete_dim, siruta_map)

    if not judet_groups:
        tqdm.write(f"ERROR: No localities grouped for {matrix_code}")
        return False

    tqdm.write(f"Found {len(judet_groups)} Judete to fetch")

    # Prepare request URL and headers
    url = 'http://statistici.insse.ro:8077/tempo-ins/pivot'
    headers = {
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'en-GB,en;q=0.7',
        'Cache-Control': 'no-cache',
        'Connection': 'keep-alive',
        'Content-Type': 'application/json',
        'Origin': 'http://statistici.insse.ro:8077',
        'Pragma': 'no-cache',
        'Referer': 'http://statistici.insse.ro:8077/tempo-online/',
        'Sec-GPC': '1',
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36'
    }

    partial_files = []
    all_data_rows = []
    header_row = None

    # Fetch data for each Judet
    for judet_id, group_info in tqdm(judet_groups.items(), desc=f"Fetching {matrix_code} by Judet", leave=False):
        judet_name = group_info['judet_name']
        localities = group_info['localities']

        tqdm.write(f"  Fetching {judet_name} ({len(localities)} localities)...")

        # Create modified matrix definition for this Judet
        modified_def = copy.deepcopy(matrix_def)

        # Update dimensions: set specific Judet and its localities
        for dim in modified_def["dimensionsMap"]:
            dim_label = dim.get("label", "").strip().lower()

            if dim_label == "judete":
                # Keep only this specific Judet
                dim["options"] = [opt for opt in dim["options"] if opt["nomItemId"] == judet_id]

            elif dim_label in ["localitati", "localitati "]:
                # Keep only localities for this Judet
                dim["options"] = localities

        # Create payload
        payload = convert_to_pivot_payload(modified_def, matrix_code, include_totals=False)

        # Make request
        try:
            response = requests.post(url, json=payload, headers=headers, verify=False)
            response.raise_for_status()

            # Check for errors
            response_text = response.content.decode('utf-8', errors='ignore')
            if ('celule' in response_text.lower() and '30000' in response_text) or \
               ('pragul' in response_text.lower() and 'celule' in response_text.lower()):
                tqdm.write(f"    WARNING: {judet_name} exceeds cell limit, skipping")
                logger.warning(f"{matrix_code} - Judet {judet_name} exceeds cell limit")
                continue

            # Save partial file
            partial_file = os.path.join(partial_dir, f"{matrix_code}_{judet_name}.csv")
            with open(partial_file, 'wb') as f:
                f.write(response.content)
            partial_files.append(partial_file)

            # Read and accumulate data
            with open(partial_file, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                if lines:
                    if header_row is None:
                        header_row = lines[0]
                    # Add data rows (skip header)
                    data_rows = [line for line in lines[1:] if line.strip()]
                    all_data_rows.extend(data_rows)
                    tqdm.write(f"    Got {len(data_rows)} rows from {judet_name}")

        except Exception as e:
            tqdm.write(f"    ERROR fetching {judet_name}: {e}")
            logger.error(f"{matrix_code} - Error fetching Judet {judet_name}: {e}")
            continue

    # Combine all partial files
    if not all_data_rows:
        tqdm.write(f"ERROR: No data collected for {matrix_code}")
        return False

    combined_file = os.path.join(output_dir, f"{matrix_code}.csv")
    with open(combined_file, 'w', encoding='utf-8') as f:
        if header_row:
            f.write(header_row)
        for row in all_data_rows:
            f.write(row)

    tqdm.write(f"SUCCESS: Combined {len(all_data_rows)} rows from {len(partial_files)} Judete")
    tqdm.write(f"Saved to {combined_file}")

    # Log success
    judet_logger.info(f"{matrix_code} - Successfully fetched using Judet-split approach ({len(partial_files)} Judete, {len(all_data_rows)} rows)")

    return True

def fetch_insse_pivot_data(matrix_code: str, matrix_def: Dict, output_dir: str, force_overwrite: bool = False) -> None:
    """
    Fetch data from INSSE Pivot API using the matrix definition.

    Args:
        matrix_code: The code of the matrix (e.g., 'POP108B')
        matrix_def: The loaded matrix definition dictionary
        output_dir: Directory to save output files
        force_overwrite: If True, overwrite existing files. If False, skip existing files.
    """
    # Check if file already exists
    output_file = os.path.join(output_dir, f"{matrix_code}.csv")
    if os.path.exists(output_file) and not force_overwrite:
        tqdm.write(f"File {output_file} already exists, skipping {matrix_code}")
        return

    # Calculate expected cell count BEFORE making request
    cell_count = calculate_cell_count(matrix_def, include_totals=False)
    cell_limit = 275000  # Safe margin below actual API limit

    if cell_count > cell_limit:
        tqdm.write(f"WARNING: Estimated {cell_count:,} cells exceeds limit ({cell_limit:,})")

        # Check if we can use Judet-split approach
        has_both, judete_dim, localitati_dim = has_judete_and_localitati(matrix_def)

        if has_both:
            # Use Judet-split approach directly for oversized datasets with both dimensions
            tqdm.write(f"Dataset has Judete+Localitati dimensions, using Judet-split approach...")
            logger.info(f"{matrix_code} - Using Judet-split approach for oversized dataset ({cell_count:,} cells)")

            try:
                # Load SIRUTA mapping
                siruta_map = load_siruta_mapping()

                # Attempt Judet-split fetch
                success = fetch_by_judet_split(
                    matrix_code, matrix_def, output_dir,
                    judete_dim, localitati_dim, siruta_map
                )

                if success:
                    # Verify the combined file has data
                    retry_row_count = count_csv_rows(output_file)
                    if retry_row_count > 0:
                        success_msg = f"JUDET-SPLIT SUCCESS: {matrix_code} fetched {retry_row_count} rows"
                        tqdm.write(success_msg)
                        logger.info(f"{matrix_code}.csv - {success_msg}")
                        return  # Success, exit function

                tqdm.write(f"JUDET-SPLIT FAILED: Could not fetch data")
                logger.warning(f"{matrix_code}.csv - Judet-split fetch failed for oversized dataset")

            except Exception as e:
                tqdm.write(f"JUDET-SPLIT EXCEPTION: {e}")
                logger.error(f"{matrix_code}.csv - Judet-split failed: {e}")

        # Cannot handle this oversized dataset - skip it
        warning_msg = f"SKIPPED: {matrix_code} - {cell_count:,} cells exceeds limit. Needs sequential dimension processing."
        tqdm.write(warning_msg)
        oversized_logger.warning(f"{matrix_code} - {cell_count:,} cells (limit: {cell_limit:,})")
        logger.warning(warning_msg)
        return

    tqdm.write(f"Estimated cells: {cell_count:,}")

    # Convert to pivot payload format
    tqdm.write(f"Converting matrix definition for {matrix_code} to pivot payload format")
    payload = convert_to_pivot_payload(matrix_def, matrix_code)
    
    # Save payload for reference (commented out as per previous script)
    # payload_file = os.path.join(output_dir, f"pivot-payload-{matrix_code}.json")
    # with open(payload_file, 'w', encoding='utf-8') as f:
    #     json.dump(payload, f, ensure_ascii=False, indent=2)
    
    # Prepare request
    url = 'http://statistici.insse.ro:8077/tempo-ins/pivot'
    headers = {
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'en-GB,en;q=0.7',
        'Cache-Control': 'no-cache',
        'Connection': 'keep-alive',
        'Content-Type': 'application/json',
        'Origin': 'http://statistici.insse.ro:8077',
        'Pragma': 'no-cache',
        'Referer': 'http://statistici.insse.ro:8077/tempo-online/',
        'Sec-GPC': '1',
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36'
    }
    
    try:
        # Make request
        tqdm.write(f"Making pivot request for {matrix_code}")
        response = requests.post(url, json=payload, headers=headers, verify=False)
        response.raise_for_status()

        # Check for cell limit error from INS API
        # Error message: "Selectia dvs actuala ar solicita X celule... pragul de 30000 de celule"
        response_text = response.content.decode('utf-8', errors='ignore')
        if ('celule' in response_text.lower() and '30000' in response_text) or \
           ('pragul' in response_text.lower() and 'celule' in response_text.lower()):
            error_msg = f"SKIPPED: {matrix_code} - Query exceeds INS API cell limit (30,000 cells)"
            tqdm.write(error_msg)
            logger.warning(f"{matrix_code}.csv - {error_msg} | Response: {response_text[:500]}")
            # Don't save the error response as a CSV file
            return

        # Save CSV response
        with open(output_file, 'wb') as f:
            f.write(response.content)
        tqdm.write(f"Saved pivot data to {output_file}")

        # Check if CSV has data rows
        row_count = count_csv_rows(output_file)
        if row_count == 0:
            warning_msg = f"WARNING: {matrix_code}.csv has only header row (no data rows)"
            tqdm.write(warning_msg)

            # Log detailed information about empty dataset
            response_headers = dict(response.headers)
            content_length = response_headers.get('Content-Length', 'N/A')
            content_type = response_headers.get('Content-Type', 'N/A')

            # Get first 1000 chars of response for debugging
            response_preview = response_text[:1000] if len(response_text) <= 1000 else response_text[:1000] + '...'

            logger.warning(
                f"{matrix_code}.csv - Empty dataset (excluding Totals) | "
                f"Content-Length: {content_length} | "
                f"Content-Type: {content_type} | "
                f"Status: {response.status_code} | "
                f"Response headers: {response_headers} | "
                f"Response content: {response_preview}"
            )

            # Check if this dataset has both Judete and Localitati dimensions
            has_both, judete_dim, localitati_dim = has_judete_and_localitati(matrix_def)

            if has_both:
                # RETRY using Judet-split approach
                tqdm.write(f"Dataset has both Judete and Localitati dimensions")
                tqdm.write(f"Retrying {matrix_code} using Judet-split approach...")
                logger.info(f"{matrix_code} - Retrying with Judet-split approach")

                try:
                    # Load SIRUTA mapping
                    siruta_map = load_siruta_mapping()

                    # Attempt Judet-split fetch
                    success = fetch_by_judet_split(
                        matrix_code, matrix_def, output_dir,
                        judete_dim, localitati_dim, siruta_map
                    )

                    if success:
                        # Verify the combined file has data
                        retry_row_count = count_csv_rows(output_file)
                        if retry_row_count > 0:
                            success_msg = f"JUDET-SPLIT SUCCESS: {matrix_code} now has {retry_row_count} rows"
                            tqdm.write(success_msg)
                            logger.info(f"{matrix_code}.csv - {success_msg}")
                            return  # Success, exit function
                        else:
                            tqdm.write(f"JUDET-SPLIT FAILED: {matrix_code} still has no data")
                            logger.warning(f"{matrix_code}.csv - Judet-split produced no data")
                    else:
                        tqdm.write(f"JUDET-SPLIT FAILED: Could not fetch data")
                        logger.warning(f"{matrix_code}.csv - Judet-split fetch failed")

                except Exception as e:
                    tqdm.write(f"JUDET-SPLIT EXCEPTION: {e}")
                    logger.error(f"{matrix_code}.csv - Judet-split retry failed: {e}")

            # FALLBACK: RETRY with "Total" options included
            tqdm.write(f"Retrying {matrix_code} WITH 'Total' options included...")
            logger.info(f"{matrix_code} - Retrying with include_totals=True")

            try:
                # Create new payload with totals included
                payload_with_totals = convert_to_pivot_payload(matrix_def, matrix_code, include_totals=True)

                # Make retry request
                retry_response = requests.post(url, json=payload_with_totals, headers=headers, verify=False)
                retry_response.raise_for_status()

                # Check for cell limit error on retry
                retry_text = retry_response.content.decode('utf-8', errors='ignore')
                if ('celule' in retry_text.lower() and '30000' in retry_text) or \
                   ('pragul' in retry_text.lower() and 'celule' in retry_text.lower()):
                    error_msg = f"RETRY FAILED: {matrix_code} - Query with Totals exceeds INS API cell limit (30,000 cells)"
                    tqdm.write(error_msg)
                    logger.warning(f"{matrix_code}.csv - {error_msg}")
                    # Keep the original empty file
                else:
                    # Save retry response
                    with open(output_file, 'wb') as f:
                        f.write(retry_response.content)

                    # Check if retry produced data
                    retry_row_count = count_csv_rows(output_file)
                    if retry_row_count > 0:
                        success_msg = f"RETRY SUCCESS: {matrix_code} now has {retry_row_count} rows with 'Total' options included"
                        tqdm.write(success_msg)
                        logger.info(f"{matrix_code}.csv - {success_msg}")
                    else:
                        fail_msg = f"RETRY FAILED: {matrix_code} still has no data even with 'Total' options"
                        tqdm.write(fail_msg)
                        logger.warning(f"{matrix_code}.csv - {fail_msg}")

                        # Also fetch Excel/HTML version to help diagnose the issue
                        try:
                            tqdm.write(f"Fetching Excel/HTML version for diagnosis...")
                            debug_folder = os.path.join("data/logs/empty-datasets")
                            os.makedirs(debug_folder, exist_ok=True)
                            fetch_insse_excel_data(matrix_code, matrix_def, debug_folder, force_overwrite=True)
                            tqdm.write(f"Saved diagnostic Excel/HTML to {debug_folder}/{matrix_code}.xls")
                        except Exception as e:
                            tqdm.write(f"Failed to fetch diagnostic Excel/HTML: {e}")

            except Exception as e:
                tqdm.write(f"RETRY EXCEPTION: Failed to retry {matrix_code} with Totals: {e}")
                logger.error(f"{matrix_code}.csv - Retry with Totals failed: {e}")

        elif row_count > 0:
            tqdm.write(f"Dataset has {row_count} data rows")
        
    except requests.exceptions.RequestException as e:
        tqdm.write(f"Error making pivot request for {matrix_code}: {e}")
        if hasattr(e.response, 'text'):
            tqdm.write(f"Response content: {e.response.text[:500]}")
        raise
    except Exception as e:
        tqdm.write(f"Unexpected error processing {matrix_code} pivot: {e}")
        raise

def fetch_insse_excel_data(matrix_code: str, matrix_def: Dict, output_dir: str, force_overwrite: bool = False) -> None:
    """
    Fetch Excel data from INSSE Excel API using the matrix definition.
    Note: The Excel endpoint actually returns HTML table format, not true Excel files.
    
    Args:
        matrix_code: The code of the matrix (e.g., 'POP108B')
        matrix_def: The loaded matrix definition dictionary
        output_dir: Directory to save output files
        force_overwrite: If True, overwrite existing files. If False, skip existing files.
    """
    # Check if file already exists
    output_file = os.path.join(output_dir, f"{matrix_code}.xls")
    if os.path.exists(output_file) and not force_overwrite:
        tqdm.write(f"File {output_file} already exists, skipping {matrix_code}")
        return
    
    # Convert to excel payload format (same as pivot)
    tqdm.write(f"Converting matrix definition for {matrix_code} to excel payload format")
    payload = convert_to_pivot_payload(matrix_def, matrix_code)
    
    # Prepare request
    url = 'http://statistici.insse.ro:8077/tempo-ins/excel'
    headers = {
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'en-GB,en;q=0.7',
        'Cache-Control': 'no-cache',
        'Connection': 'keep-alive',
        'Content-Type': 'application/json',
        'Origin': 'http://statistici.insse.ro:8077',
        'Pragma': 'no-cache',
        'Referer': 'http://statistici.insse.ro:8077/tempo-online/',
        'Sec-GPC': '1',
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36'
    }
    
    try:
        # Make request
        tqdm.write(f"Making excel request for {matrix_code}")
        response = requests.post(url, json=payload, headers=headers, verify=False)
        response.raise_for_status()
        
        # Save Excel response
        with open(output_file, 'wb') as f:
            f.write(response.content)
        tqdm.write(f"Saved excel data to {output_file}")
        
    except requests.exceptions.RequestException as e:
        tqdm.write(f"Error making excel request for {matrix_code}: {e}")
        if hasattr(e.response, 'text'):
            tqdm.write(f"Response content: {e.response.text[:500]}")
        raise
    except Exception as e:
        tqdm.write(f"Unexpected error processing {matrix_code} excel: {e}")
        raise

def process_matrices_folder(input_folder: str, output_folder: str, xls_output_folder: str, force_overwrite: bool = False, download_xls: bool = False) -> None:
    """
    Process all JSON files in the input folder and fetch their pivot data (CSV and optionally Excel).
    
    Args:
        input_folder: Path to folder containing matrix definition JSON files
        output_folder: Path to folder where CSV results should be saved
        xls_output_folder: Path to folder where Excel results should be saved
        force_overwrite: If True, overwrite existing files. If False, skip existing files.
        download_xls: If True, also download Excel/HTML files. If False, only download CSV files.
    """
    # Create output folders if they don't exist
    os.makedirs(output_folder, exist_ok=True)
    if download_xls:
        os.makedirs(xls_output_folder, exist_ok=True)
    
    # Get all JSON files in input folder
    input_path = pathlib.Path(input_folder)
    json_files = list(input_path.glob('*.json'))
    
    if not json_files:
        logger.warning(f"No JSON files found in {input_folder}")
        return
    
    logger.info(f"Found {len(json_files)} JSON files to process")
    
    # Add progress bar for batch processing
    with tqdm(json_files, desc="Processing matrices", unit="matrix") as pbar:
        for json_file in pbar:
            try:
                # Extract matrix code from filename (assuming format like "POP107D sample.json")
                matrix_code = json_file.stem.split()[0]
                
                # Update progress bar description
                pbar.set_description(f"Processing {matrix_code}")
                tqdm.write(f"Processing {json_file.name}")
                
                # Load matrix definition
                matrix_def = load_matrix_definition(str(json_file))
                
                # Fetch CSV data
                fetch_insse_pivot_data(matrix_code, matrix_def, output_folder, force_overwrite)
                
                # Fetch Excel data only if requested
                if download_xls:
                    fetch_insse_excel_data(matrix_code, matrix_def, xls_output_folder, force_overwrite)
                
            except Exception as e:
                tqdm.write(f"Error processing {json_file.name}: {e}")
                continue
    
    logger.info("Finished processing all matrix files")

def process_single_matrix(matrix_code: str, input_folder: str, output_folder: str, xls_output_folder: str, force_overwrite: bool = False, download_xls: bool = False) -> None:
    """
    Process a single matrix by its code (CSV and optionally Excel).
    
    Args:
        matrix_code: The matrix code to process (e.g., 'POP107D')
        input_folder: Path to folder containing matrix definition JSON files
        output_folder: Path to folder where CSV results should be saved
        xls_output_folder: Path to folder where Excel results should be saved
        force_overwrite: If True, overwrite existing files. If False, skip existing files.
        download_xls: If True, also download Excel/HTML files. If False, only download CSV files.
    """
    # Create output folders if they don't exist
    os.makedirs(output_folder, exist_ok=True)
    if download_xls:
        os.makedirs(xls_output_folder, exist_ok=True)
    
    # Find the JSON file for this matrix code
    input_path = pathlib.Path(input_folder)
    json_files = list(input_path.glob(f'{matrix_code}*.json'))
    
    if not json_files:
        logger.error(f"No JSON file found for matrix code '{matrix_code}' in {input_folder}")
        return
    
    if len(json_files) > 1:
        logger.warning(f"Multiple files found for matrix code '{matrix_code}', using first one: {json_files[0].name}")
    
    json_file = json_files[0]
    
    try:
        # Determine total steps based on whether XLS download is enabled
        total_steps = 2 if download_xls else 1
        
        # Add progress bar for single matrix processing
        with tqdm(total=total_steps, desc=f"Processing {matrix_code}", unit="file") as pbar:
            tqdm.write(f"Processing single matrix: {json_file.name}")
            
            # Load matrix definition
            matrix_def = load_matrix_definition(str(json_file))
            
            # Fetch CSV data
            pbar.set_description(f"Downloading CSV for {matrix_code}")
            fetch_insse_pivot_data(matrix_code, matrix_def, output_folder, force_overwrite)
            pbar.update(1)
            # time.sleep(1)
            # Fetch Excel data only if requested
            if download_xls:
                # wait 1 second
                # time.sleep(1)
                pbar.set_description(f"Downloading Excel for {matrix_code}")
                fetch_insse_excel_data(matrix_code, matrix_def, xls_output_folder, force_overwrite)
                pbar.update(1)
            
            tqdm.write(f"Successfully processed matrix {matrix_code}")
        
    except Exception as e:
        tqdm.write(f"Error processing matrix {matrix_code}: {e}")
        raise

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Fetch CSV data from INSSE for matrices (Excel/HTML optional with --xls flag)')
    parser.add_argument('--matrix', '-m', type=str, help='Process a single matrix by code (e.g., POP107D)')
    parser.add_argument('--force', '-f', action='store_true', help='Force overwrite existing files')
    parser.add_argument('--xls', '-x', action='store_true', help='Also download Excel/HTML files (disabled by default)')
    
    args = parser.parse_args()
    
    if args.matrix:
        logger.info(f"Processing single matrix: {args.matrix}")
        process_single_matrix(args.matrix, input_folder, output_folder, xls_output_folder, args.force, args.xls)
    else:
        logger.info("Processing all matrices in folder")
        process_matrices_folder(input_folder, output_folder, xls_output_folder, args.force, args.xls)