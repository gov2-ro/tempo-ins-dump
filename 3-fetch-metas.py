
import csv
import requests
import os
import time
import random
from tqdm import tqdm
import argparse

# --- Configuration ---
INPUT_CSV_PATH = '/Users/pax/devbox/gov2/tempo-ins-dump/data/1-indexes/ro/matrices.csv'
OUTPUT_DIR = '/Users/pax/devbox/gov2/tempo-ins-dump/data/2-metas/ro/'
BASE_URL = 'http://statistici.insse.ro:8077/tempo-ins/matrix/'

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    'Accept': 'application/json, text/javascript, */*; q=0.01',
    'Accept-Language': 'en-US,en;q=0.9',
    'Referer': 'http://statistici.insse.ro:8077/tempo-online/',
    'X-Requested-With': 'XMLHttpRequest',
    'Connection': 'keep-alive',
}

# --- Argument Parsing ---
parser = argparse.ArgumentParser(description='Download matrix metadata from tempo-ins.')
parser.add_argument('--force', action='store_true', help='Force overwrite of existing files.')
args = parser.parse_args()

# --- Main Script ---
def fetch_metas():
    """
    Reads matrix codes from a CSV, downloads corresponding JSON metadata,
    and saves it to files.
    """
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    try:
        with open(INPUT_CSV_PATH, mode='r', encoding='utf-8') as infile:
            reader = csv.DictReader(infile)
            matrices = list(reader)
    except FileNotFoundError:
        print(f"Error: Input file not found at {INPUT_CSV_PATH}")
        return

    print(f"Found {len(matrices)} matrices to process.")

    for matrix in tqdm(matrices, desc="Fetching Metas"):
        code = matrix.get('code')
        if not code:
            tqdm.write("Skipping row with no 'code'.")
            continue

        output_filepath = os.path.join(OUTPUT_DIR, f"{code}.json")

        if not args.force and os.path.exists(output_filepath):
            tqdm.write(f"Skipping {code}, file already exists.")
            continue

        url = f"{BASE_URL}{code}"

        try:
            response = requests.get(url, headers=HEADERS)
            response.raise_for_status()  # Raise an exception for bad status codes

            with open(output_filepath, 'w', encoding='utf-8') as outfile:
                outfile.write(response.text)

            # Random wait to be nice to the server
            time.sleep(random.uniform(0.4, 1.2))

        except requests.exceptions.RequestException as e:
            tqdm.write(f"Error downloading {url}: {e}")
        except IOError as e:
            tqdm.write(f"Error writing file {output_filepath}: {e}")


if __name__ == '__main__':
    fetch_metas()
    print("Done.")
