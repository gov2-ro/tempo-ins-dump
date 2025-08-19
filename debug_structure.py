#!/usr/bin/env python3
"""
Debug the actual structure of validation results
"""

import pandas as pd
import sys
import json
sys.path.append('profiling')

from validation_rules import DataValidator
from ins_validation_rules import (
    INSFileStructureRule, ColumnNameMultipleIndicatorRule, ColumnNameGeographicRule,
    ColumnNameTemporalRule, ColumnDataTemporalRule, ColumnDataGenderRule,
    ColumnDataGeographicRule, ColumnDataAgeGroupRule, ColumnDataResidenceRule,
    ColumnDataTotalRule, ColumnDataPrefixSuffixRule, ColumnConsistencyRule
)

def debug_validation_structure():
    # Load a sample file
    df = pd.read_csv('data/4-datasets/ro/AED109A.csv')
    
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
    
    # Run validation
    validation_summary = validator.validate_dataframe_summary(df, 'AED109A.csv')
    
    print("=== VALIDATION SUMMARY STRUCTURE ===")
    print(json.dumps(validation_summary, indent=2, default=str))
    
    print("\n=== FILE_CHECKS STRUCTURE ===")
    file_checks = validation_summary.get("file_checks", {})
    print(json.dumps(file_checks, indent=2, default=str))

if __name__ == "__main__":
    debug_validation_structure()
