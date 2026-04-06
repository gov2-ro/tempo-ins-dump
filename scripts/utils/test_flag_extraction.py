#!/usr/bin/env python3
"""
Test validation flags extraction directly
"""

import pandas as pd
import sys
import json
sys.path.append('profiling')

from data_profiler import profile_and_validate_csv

def test_flag_extraction():
    df_results, file_checks = profile_and_validate_csv('data/4-datasets/ro/AED109A.csv')
    
    print("=== COLUMN RESULTS ===")
    print("DataFrame columns:")
    for idx, row in df_results.iterrows():
        col_name = row['column_name']
        validation_flags = row.get('validation_flags', 'MISSING')
        print(f"  {idx}: '{col_name}' -> {validation_flags}")
    
    print("\n=== MANUAL FLAG EXTRACTION TEST ===")
    validation_results = file_checks.get("validation_results", [])
    
    # Test with each column from df_results
    for idx, row in df_results.iterrows():
        col_name = row['column_name']
        print(f"\nTesting column: '{col_name}'")
        
        # Manual extraction like in data_profiler
        validation_flags = []
        for validation_result in validation_results:
            validation_col_name = validation_result.get("column_name")
            if validation_col_name is not None:
                validation_col_name = validation_col_name.strip()
                current_col_name = col_name.strip()
                print(f"  Comparing '{current_col_name}' == '{validation_col_name}': {current_col_name == validation_col_name}")
                if validation_col_name == current_col_name:
                    context = validation_result.get("context", {})
                    flags = context.get("validation_flags", [])
                    print(f"    Found flags: {flags}")
                    validation_flags.extend(flags)
        
        validation_flags = sorted(list(set(validation_flags)))
        print(f"  Final flags for '{col_name}': {validation_flags}")

if __name__ == "__main__":
    test_flag_extraction()
