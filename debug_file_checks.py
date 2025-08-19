#!/usr/bin/env python3
"""
Debug what's in file_checks during data profiler execution
"""

import pandas as pd
import sys
import json
sys.path.append('profiling')

from data_profiler import profile_and_validate_csv

def debug_file_checks():
    # Load the same file that data_profiler uses
    df_results, file_checks = profile_and_validate_csv('data/4-datasets/ro/AED109A.csv')
    
    print("=== FILE_CHECKS CONTENTS ===")
    print(json.dumps(file_checks, indent=2, default=str))
    
    print("\n=== VALIDATION RESULTS COUNT ===")
    validation_results = file_checks.get("validation_results", [])
    print(f"Number of validation results: {len(validation_results)}")
    
    for i, result in enumerate(validation_results):
        column_name = result.get("column_name")
        context = result.get("context", {})
        flags = context.get("validation_flags", [])
        print(f"  {i}: {result.get('rule_id')} | {column_name} | {flags}")

if __name__ == "__main__":
    debug_file_checks()
