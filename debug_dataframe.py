#!/usr/bin/env python3
"""
Check the DataFrame columns to see if validation_flags is included
"""

import pandas as pd
import sys
import json
sys.path.append('profiling')

from data_profiler import profile_and_validate_csv

def check_dataframe_columns():
    df_results, file_checks = profile_and_validate_csv('data/4-datasets/ro/AED109A.csv')
    
    print("=== DATAFRAME INFO ===")
    print(f"DataFrame shape: {df_results.shape}")
    print(f"DataFrame columns: {list(df_results.columns)}")
    
    print("\n=== SAMPLE RECORD ===")
    first_record = df_results.iloc[0].to_dict()
    print(json.dumps(first_record, indent=2, default=str))
    
    print("\n=== TO_DICT ORIENT RECORDS ===")
    records = df_results.to_dict(orient='records')
    print(f"Number of records: {len(records)}")
    print(f"First record keys: {list(records[0].keys())}")
    print(f"First record: {json.dumps(records[0], indent=2, default=str)}")

if __name__ == "__main__":
    check_dataframe_columns()
