import pandas as pd
from ydata_profiling import ProfileReport
import os
from tqdm import tqdm
import logging

# --- Configuration ---
# Set the directory where your CSV files are located.
INPUT_DIR = 'data-samples/datasets/' 
# Set the directory where the HTML reports will be saved.
OUTPUT_DIR = 'profiling_reports/'

# --- Setup Logging ---
# Suppress noisy logs from underlying libraries (e.g., matplotlib)
logging.basicConfig(level=logging.ERROR)


def generate_all_profiles():
    """
    Finds all CSV files in the INPUT_DIR, generates a ydata-profiling report
    for each, and saves it as an HTML file in the OUTPUT_DIR.
    """
    print(f"Starting data profiling...")
    print(f"Input directory: '{os.path.abspath(INPUT_DIR)}'")
    print(f"Output directory: '{os.path.abspath(OUTPUT_DIR)}'")

    # 1. Create the output directory if it doesn't exist
    try:
        os.makedirs(OUTPUT_DIR, exist_ok=True)
    except OSError as e:
        print(f"Error creating directory {OUTPUT_DIR}: {e}")
        return

    # 2. Get a list of all CSV files in the input directory
    try:
        csv_files = [f for f in os.listdir(INPUT_DIR) if f.endswith('.csv')]
        if not csv_files:
            print(f"Warning: No CSV files found in '{INPUT_DIR}'. Exiting.")
            return
    except FileNotFoundError:
        print(f"Error: Input directory '{INPUT_DIR}' not found. Please check the path.")
        return

    print(f"Found {len(csv_files)} CSV files to profile.")

    # 3. Loop through each CSV file and generate a report
    for filename in tqdm(csv_files, desc="Generating Reports"):
        input_path = os.path.join(INPUT_DIR, filename)
        base_name = os.path.splitext(filename)[0]
        output_filename = f"{base_name}_profile.html"
        output_path = os.path.join(OUTPUT_DIR, output_filename)

        try:
            # Read the CSV file into a pandas DataFrame
            # Added error_bad_lines=False and warn_bad_lines=True for robustness
            df = pd.read_csv(input_path, on_bad_lines='warn')

            if df.empty:
                tqdm.write(f"Skipping empty file: {filename}")
                continue

            # Generate the profile report
            # Using minimal=True can speed up the process if you only need basic stats
            profile = ProfileReport(
                df, 
                title=f"Data Profile for {base_name}",
                explorative=True
            )

            # Save the report to an HTML file
            profile.to_file(output_path)
            
        except Exception as e:
            # Handle potential errors like file corruption or parsing issues
            tqdm.write(f"Could not process {filename}. Error: {e}")

    print("\nProfiling complete!")
    print(f"All reports have been saved to the '{OUTPUT_DIR}' directory.")


if __name__ == "__main__":
    generate_all_profiles()