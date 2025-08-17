""" 
todo

- [ ] add description
- [ ] add progress bar


"""

lang = "ro"
# lang = "en"

""" 
y not go through indexes/matrices.csv ? - flag?
"""

input_folder="data/2-metas/" + lang
output_folder="data/4-datasets/" + lang

import requests
import json
from urllib3.exceptions import InsecureRequestWarning
import logging
from typing import Dict, List, Any
import os
import pathlib

# Suppress only the single InsecureRequestWarning
requests.packages.urllib3.disable_warnings(category=InsecureRequestWarning)

# Set up logging
logging.basicConfig(level=logging.INFO,
                   format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def load_matrix_definition(file_path: str) -> Dict:
    """Load and parse the matrix definition file."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error loading matrix definition: {e}")
        raise

def encode_query_parameters(matrix_def: Dict) -> str:
    """
    Convert matrix definition to encoded query format.
    Format: dimension1:value1,value2:value3,value4:...
    """
    encoded_parts = []
    
    for dim in matrix_def["dimensionsMap"]:
        # Filter out "Total" options when there are alternatives
        options = dim["options"]
        if len(options) > 1:
            options = [opt for opt in options if opt["label"].strip().lower() != "total"]
        
        if options:
            # Add nomItemIds for this dimension
            item_ids = [str(opt["nomItemId"]) for opt in options]
            encoded_parts.append(",".join(item_ids))
    
    # Join all parts with colon
    return ":".join(encoded_parts)

def convert_to_pivot_payload(matrix_def: Dict, matrix_code: str) -> Dict:
    """Convert matrix definition to pivot API payload format."""
    encoded_query = encode_query_parameters(matrix_def)
    
    payload = {
        "language": "ro",
        "encQuery": encoded_query,
        "matCode": matrix_code,
        "matMaxDim": matrix_def["details"]["matMaxDim"],
        "matUMSpec": matrix_def["details"]["matUMSpec"],
        "matRegJ": matrix_def["details"].get("matRegJ", 0)  # Default to 0 if not present
    }
    
    return payload

def fetch_insse_pivot_data(matrix_code: str, matrix_def: Dict, output_dir: str) -> None:
    """
    Fetch data from INSSE Pivot API using the matrix definition.
    
    Args:
        matrix_code: The code of the matrix (e.g., 'POP108B')
        matrix_def: The loaded matrix definition dictionary
        output_dir: Directory to save output files
    """
    # Convert to pivot payload format
    logger.info(f"Converting matrix definition for {matrix_code} to pivot payload format")
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
        logger.info(f"Making pivot request for {matrix_code}")
        response = requests.post(url, json=payload, headers=headers, verify=False)
        response.raise_for_status()
        
        # Save CSV response
        output_file = os.path.join(output_dir, f"{matrix_code}.csv")
        with open(output_file, 'wb') as f:
            f.write(response.content)
        logger.info(f"Saved pivot data to {output_file}")
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Error making pivot request for {matrix_code}: {e}")
        if hasattr(e.response, 'text'):
            logger.error(f"Response content: {e.response.text[:500]}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error processing {matrix_code} pivot: {e}")
        raise

def process_matrices_folder(input_folder: str, output_folder: str) -> None:
    """
    Process all JSON files in the input folder and fetch their pivot data.
    
    Args:
        input_folder: Path to folder containing matrix definition JSON files
        output_folder: Path to folder where results should be saved
    """
    # Create output folder if it doesn't exist
    os.makedirs(output_folder, exist_ok=True)
    
    # Get all JSON files in input folder
    input_path = pathlib.Path(input_folder)
    json_files = list(input_path.glob('*.json'))
    
    if not json_files:
        logger.warning(f"No JSON files found in {input_folder}")
        return
    
    logger.info(f"Found {len(json_files)} JSON files to process")
    
    for json_file in json_files:
        try:
            # Extract matrix code from filename (assuming format like "POP107D sample.json")
            matrix_code = json_file.stem.split()[0]
            
            logger.info(f"Processing {json_file.name}")
            
            # Load matrix definition
            matrix_def = load_matrix_definition(str(json_file))
            
            # Fetch pivot data
            fetch_insse_pivot_data(matrix_code, matrix_def, output_folder)
            
        except Exception as e:
            logger.error(f"Error processing {json_file.name}: {e}")
            continue
    
    logger.info("Finished processing all matrix files")

if __name__ == "__main__":
    process_matrices_folder(        input_folder,        output_folder)