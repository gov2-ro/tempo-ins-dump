




""" 
This script is designed as a command-line tool. It loads the rules, reads the input file, classifies each label, and saves the enriched data to a new CSV file. 
"""


import pandas as pd
import re
import os
import argparse
from tqdm import tqdm

class VariableClassifier:
    """
    Classifies variable labels using an external ruleset to assign both
    semantic categories and functional types.
    """

    def __init__(self, rules_csv_path: str):
        """Initializes the classifier by loading rules from a CSV file."""
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
                    "keywords": str(row['keyword']).split('|'),
                    "semantic_category": row['semantic_category'],
                    "functional_types": [ft.strip() for ft in str(row['functional_types']).split(',')],
                    "match_type": row['match_type'],
                }
                rules_list.append(rule)
            
            print(f"✅ Successfully loaded {len(rules_list)} rules from '{rules_csv_path}'")
            return rules_list
        except Exception as e:
            raise RuntimeError(f"Failed to load or parse the rules CSV file: {e}")

    def _normalize(self, label: str) -> str:
        """Normalizes a label for robust matching."""
        if pd.isna(label):
            return ""
        label = str(label).lower()
        label = re.sub(r'[^\w\s]', ' ', label) # Replace punctuation with space
        return label

    def classify(self, label: str) -> tuple[str, str]:
        """
        Classifies a single label and returns its semantic and functional categories.
        
        Returns:
            A tuple containing two strings: (semantic_tags, functional_tags)
        """
        norm_label = self._normalize(label)
        semantic_tags = set()
        functional_tags = set()

        for rule in self.rules:
            match_found = False
            if rule['match_type'] == 'prefix':
                if any(norm_label.startswith(kw.strip()) for kw in rule['keywords']):
                    match_found = True
            elif rule['match_type'] == 'exact':
                 if any(norm_label == kw.strip() for kw in rule['keywords']):
                    match_found = True
            else: # Default to 'keyword' (substring match)
                if any(kw.strip() in norm_label for kw in rule['keywords']):
                    match_found = True
            
            if match_found:
                semantic_tags.add(rule['semantic_category'])
                functional_tags.update(rule['functional_types'])

        return ", ".join(sorted(list(semantic_tags))), ", ".join(sorted(list(functional_tags)))

def process_classification(input_path, output_path, rules_path):
    """
    Main function to process an input CSV of variable labels and generate
    an output CSV with the new classification columns.
    """
    try:
        classifier = VariableClassifier(rules_path)

        print(f"➡️  Reading input labels from '{input_path}'...")
        if not os.path.exists(input_path):
            raise FileNotFoundError(f"Input file not found: {input_path}")
        
        df_input = pd.read_csv(input_path)
        input_column_name = df_input.columns[0]

        tqdm.pandas(desc="Classifying variables")
        
        # Apply the classification function which returns a tuple of two strings
        results = df_input[input_column_name].progress_apply(classifier.classify)
        
        # Split the tuple results into two new columns
        df_input[['semantic_categories', 'functional_types']] = pd.DataFrame(results.tolist(), index=df_input.index)

        df_input.to_csv(output_path, index=False, quoting=1)
        print(f"✅ Success! Classified variables saved to '{output_path}'")

    except Exception as e:
        print(f"❌ An error occurred: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Classify variable labels using an external rules CSV file."
    )
    parser.add_argument(
        '-i', '--input', 
        default='../data/repository/labels.csv', 
        help="Path to the input CSV with labels in the first column."
    )
    parser.add_argument(
        '-o', '--output', 
        default='../data/profiling/classified_variables.csv', 
        help="Path for the output CSV with classification columns."
    )
    parser.add_argument(
        '-r', '--rules', 
        default='rules-dictionaries/variable_classification_rules.csv', 
        help="Path to the CSV file containing classification rules."
    )
    
    args = parser.parse_args()
    
    process_classification(args.input, args.output, args.rules)