#!/usr/bin/env python3
"""
Quick test script to debug the validation flags extraction
"""

import pandas as pd
import sys
sys.path.append('profiling')

from validation_rules import DataValidator
from ins_validation_rules import (
    INSFileStructureRule, ColumnNameMultipleIndicatorRule, ColumnNameGeographicRule,
    ColumnNameTemporalRule, ColumnDataTemporalRule, ColumnDataGenderRule,
    ColumnDataGeographicRule, ColumnDataAgeGroupRule, ColumnDataResidenceRule,
    ColumnDataTotalRule, ColumnDataPrefixSuffixRule, ColumnConsistencyRule
)

def test_validation():
    # Load a sample file
    df = pd.read_csv('data/4-datasets/ro/AED109A.csv')
    
    print(f"Loaded CSV with {len(df.columns)} columns:")
    for i, col in enumerate(df.columns):
        print(f"  {i}: {col}")
    
    # Create validator with INS rules
    validator = DataValidator()
    
    # Add INS-specific validation rules
    validator.add_rule(INSFileStructureRule())
    validator.add_rule(ColumnNameMultipleIndicatorRule())
    validator.add_rule(ColumnNameGeographicRule())
    validator.add_rule(ColumnNameTemporalRule())
    validator.add_rule(ColumnDataTemporalRule())
    validator.add_rule(ColumnDataGenderRule())
    validator.add_rule(ColumnDataGeographicRule())
    validator.add_rule(ColumnDataAgeGroupRule())
    validator.add_rule(ColumnDataResidenceRule())
    validator.add_rule(ColumnDataTotalRule())
    validator.add_rule(ColumnDataPrefixSuffixRule())
    validator.add_rule(ColumnConsistencyRule())
    
    print(f"\nValidator has {len(validator.rules)} rules")
    for rule in validator.rules:
        print(f"  - {rule.rule_id}")
    
    # Run validation
    validation_summary = validator.validate_dataframe_summary(df, 'AED109A.csv')
    
    print(f"\nValidation Summary:")
    print(f"  Total results: {len(validation_summary.get('detailed_results', []))}")
    print(f"  Summary: {validation_summary.get('validation_summary', {})}")
    
    print(f"\nDetailed Results:")
    for result in validation_summary.get('detailed_results', []):
        rule_id = result.get('rule_id')
        column_name = result.get('column_name', 'N/A')
        context = result.get('context', {})
        flags = context.get('validation_flags', [])
        
        print(f"  Rule: {rule_id} | Column: {column_name} | Flags: {flags}")
        if flags:
            print(f"    Context: {context}")

if __name__ == "__main__":
    test_validation()
