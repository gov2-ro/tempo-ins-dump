#!/usr/bin/env python3
"""
Test the exact JSON generation process
"""

import pandas as pd
import sys
import json
import os
import math
sys.path.append('profiling')

from data_profiler import profile_and_validate_csv, convert_numpy_types

def test_json_generation():
    input_path = 'data/4-datasets/ro/AED109A.csv'
    profile_df, file_checks = profile_and_validate_csv(input_path)
    
    print("=== BEFORE JSON PROCESSING ===")
    records = profile_df.to_dict(orient='records')
    print(f"First record validation_flags: {records[0].get('validation_flags', 'MISSING')}")
    
    # Simulate the same processing as in main()
    headers_class = []  # Empty for test
    
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
    
    print(f"\n=== CLASS MAP ===")
    print(f"Class map: {class_map}")

    for rec in profile_df.to_dict(orient='records'):
        print(f"\n=== PROCESSING RECORD ===")
        print(f"Original record keys: {list(rec.keys())}")
        print(f"Original validation_flags: {rec.get('validation_flags', 'MISSING')}")
        
        name = str(rec.get('column_name', '')).strip()
        cls = class_map.get(name, None)
        print(f"Column name: '{name}', cls: {cls}")
        
        if cls:
            print(f"Before update: {list(rec.keys())}")
            rec.update(cls)
            print(f"After update: {list(rec.keys())}")
        
        # Drop non-relevant or NaN fields for cleaner JSON
        uvc = rec.get('unique_values_count', None)
        if (uvc is None) or (isinstance(uvc, float) and math.isnan(uvc)):
            rec.pop('unique_values_count', None)
        uvs = rec.get('unique_values_sample', None)
        if uvs is None:
            rec.pop('unique_values_sample', None)
        
        print(f"Final record keys: {list(rec.keys())}")
        print(f"Final validation_flags: {rec.get('validation_flags', 'MISSING')}")
        
        merged_profile.append(rec)

    combined = {
        "source_csv": os.path.abspath(input_path),
        "file_checks": convert_numpy_types(file_checks),
        "columns": merged_profile
    }
    
    print(f"\n=== FINAL COMBINED JSON ===")
    print(f"First column validation_flags: {combined['columns'][0].get('validation_flags', 'MISSING')}")
    
    # Write to test file
    with open('/tmp/test_output.json', 'w', encoding='utf-8') as cf:
        json.dump(combined, cf, ensure_ascii=False, indent=2)
    
    print("Wrote test JSON to /tmp/test_output.json")
    
    # Read it back
    with open('/tmp/test_output.json', 'r', encoding='utf-8') as rf:
        data = json.load(rf)
    
    print(f"\n=== READ BACK FROM FILE ===")
    print(f"First column validation_flags: {data['columns'][0].get('validation_flags', 'MISSING')}")

if __name__ == "__main__":
    test_json_generation()
