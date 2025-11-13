#!/usr/bin/env python3
"""
Test with actual variable classifier to see what happens
"""

import pandas as pd
import sys
import json
import os
sys.path.append('profiling')

from data_profiler import profile_and_validate_csv
from variable_classifier import classify_headers_in_file

def test_with_classifier():
    input_path = 'data/4-datasets/ro/AED109A.csv'
    rules_path = 'profiling/rules-dictionaries/variable_classification_rules.csv'
    
    profile_df, file_checks = profile_and_validate_csv(input_path)
    
    print("=== PROFILE DF COLUMNS ===")
    print(f"DataFrame columns: {list(profile_df.columns)}")
    print(f"First record validation_flags: {profile_df.iloc[0]['validation_flags']}")
    
    # Try the variable classifier
    try:
        headers_class = classify_headers_in_file(input_path, rules_path)
        print(f"\n=== CLASSIFIER RESULTS ===")
        print(f"Type: {type(headers_class)}")
        if isinstance(headers_class, list):
            print(f"Length: {len(headers_class)}")
            for i, item in enumerate(headers_class[:3]):  # Show first 3
                print(f"  {i}: {item}")
        else:
            print(f"Content: {headers_class}")
            
    except Exception as e:
        print(f"Classification error: {e}")
        headers_class = []
    
    # Test the class_map building
    class_map = {}
    if isinstance(headers_class, list):
        for item in headers_class:
            if isinstance(item, dict) and 'label' in item:
                class_map[str(item['label']).strip()] = {
                    'semantic_categories': item.get('semantic_categories', ''),
                    'functional_types': item.get('functional_types', '')
                }
    
    print(f"\n=== CLASS MAP ===")
    for key, val in class_map.items():
        print(f"  '{key}': {val}")

    # Test the merging process
    test_record = profile_df.iloc[0].to_dict()
    print(f"\n=== BEFORE MERGING ===")
    print(f"Record keys: {list(test_record.keys())}")
    print(f"validation_flags: {test_record.get('validation_flags', 'MISSING')}")
    
    name = str(test_record.get('column_name', '')).strip()
    cls = class_map.get(name, None)
    print(f"\nColumn: '{name}', cls: {cls}")
    
    if cls:
        test_record.update(cls)
        print(f"After update keys: {list(test_record.keys())}")
        print(f"validation_flags: {test_record.get('validation_flags', 'MISSING')}")

if __name__ == "__main__":
    test_with_classifier()
