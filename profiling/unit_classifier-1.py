import pandas as pd
import re
import os
import argparse
from tqdm import tqdm

class UnitClassifier:
    """
    A classifier to guess the semantic type and properties of a Unit of Measurement (UM) label.
    It reads its configuration from an external CSV file, making it flexible and maintainable.
    """

    def __init__(self, rules_csv_path: str):
        """
        Initializes the classifier by loading and parsing rules from a specified CSV file.
        """
        self.rules = self._load_rules(rules_csv_path)

    def _load_rules(self, rules_csv_path: str) -> list:
        """Loads and processes classification rules from the external CSV file."""
        if not os.path.exists(rules_csv_path):
            raise FileNotFoundError(f"Rules file not found at: {rules_csv_path}")
        
        try:
            df_rules = pd.read_csv(rules_csv_path)
            df_rules = df_rules.sort_values(by='priority').reset_index(drop=True)
            
            rules_list = []
            for _, row in df_rules.iterrows():
                rule = {
                    "tag": row['tag'],
                    "keywords": str(row['keywords']).split('|'),
                    "match_type": row['match_type'],
                }
                rules_list.append(rule)
            
            print(f"✅ Successfully loaded {len(rules_list)} rules from '{rules_csv_path}'")
            return rules_list
        except Exception as e:
            raise RuntimeError(f"Failed to load or parse the rules CSV file: {e}")

    def _normalize(self, label: str) -> str:
        """Converts label to lowercase for case-insensitive matching."""
        return str(label).lower()

    def classify(self, label: str) -> str:
        """
        Classifies a UM label using the loaded rules and returns a comma-separated string of tags.
        """
        if pd.isna(label) or not str(label).strip():
            return "unknown"

        norm_label = self._normalize(label)
        tags = set()

        for rule in self.rules:
            match_found = False
            match_type = rule['match_type']

            if match_type == 'exact':
                if any(norm_label == kw for kw in rule['keywords']):
                    match_found = True
            elif match_type == 'prefix':
                if any(norm_label.startswith(kw) for kw in rule['keywords']):
                    match_found = True
            elif match_type == 'keyword':
                if any(kw in norm_label for kw in rule['keywords']):
                    match_found = True
            
            if match_found:
                tags.add(rule['tag'])

        if not tags:
            tags.add("other")
            
        return ", ".join(sorted(list(tags)))

def process_file(input_path, output_path, rules_path):
    """
    Main function to process an input CSV of UM labels and generate an output CSV with classifications.
    """
    try:
        # 1. Initialize the classifier with the rules file
        classifier = UnitClassifier(rules_path)

        # 2. Load the input data
        print(f"➡️  Reading input labels from '{input_path}'...")
        if not os.path.exists(input_path):
            raise FileNotFoundError(f"Input file not found: {input_path}")
        
        df_input = pd.read_csv(input_path)
        input_column_name = df_input.columns[0] # Process the first column by default

        # 3. Apply the classification
        tqdm.pandas(desc="Classifying labels")
        df_input['suggested_tags'] = df_input[input_column_name].progress_apply(classifier.classify)

        # 4. Save the results
        df_input.to_csv(output_path, index=False, quoting=1) # quoting=1 ensures all fields are quoted
        print(f"✅ Success! Classified labels saved to '{output_path}'")

    except Exception as e:
        print(f"❌ An error occurred: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Classify Unit of Measurement (UM) labels based on an external rules file."
    )
    parser.add_argument(
        '-i', '--input', 
        default='input_ums.csv', 
        help="Path to the input CSV file with UM labels in the first column."
    )
    parser.add_argument(
        '-o', '--output', 
        default='classified_ums.csv', 
        help="Path for the output CSV file with classified tags."
    )
    parser.add_argument(
        '-r', '--rules', 
        default='unit_rules.csv', 
        help="Path to the CSV file containing classification rules."
    )
    
    args = parser.parse_args()
    
    process_file(args.input, args.output, args.rules)