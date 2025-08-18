"""
Custom Validation Rules for INS Data

This module shows examples of how to extend the validation system with 
custom rules specific to Romanian INS data characteristics.
"""

from validation_rules import (
    ValidationRule, 
    ValidationResult, 
    ValidationSeverity,
    ColumnDataValidationRule,
    FileStructureValidationRule
)
import pandas as pd
import re
from typing import List


class PeriodColumnPatternRule(ColumnDataValidationRule):
    """
    Validates that period columns follow expected Romanian INS patterns.
    Checks for proper formatting of years, quarters, months, etc.
    """
    
    def __init__(self):
        super().__init__(
            rule_id="period_column_patterns",
            description="Validates Romanian temporal period formatting (years, quarters, months)"
        )
    
    def validate_column_data(
        self, 
        column_name: str, 
        column_data: pd.Series, 
        index: int, 
        **context
    ) -> List[ValidationResult]:
        results = []
        
        # Skip non-string columns
        if column_data.dtype not in ['object'] and not pd.api.types.is_string_dtype(column_data):
            return results
        
        non_null_data = column_data.dropna().astype(str)
        if non_null_data.empty or len(non_null_data) < 3:
            return results
        
        # Check if this looks like a period column
        sample_values = non_null_data.head(10).str.lower()
        
        # Look for Romanian temporal keywords
        temporal_keywords = ['an', 'anul', 'trimestrul', 'luna', 'semestrul']
        has_temporal_keywords = any(
            keyword in ' '.join(sample_values.tolist()) 
            for keyword in temporal_keywords
        )
        
        # Look for year patterns (4 digits)
        has_year_pattern = sample_values.str.contains(r'\b\d{4}\b').any()
        
        if not (has_temporal_keywords or has_year_pattern):
            return results  # Not a period column
        
        # Analyze patterns in the data
        pattern_issues = []
        
        # Check for inconsistent year formats
        year_patterns = {
            'plain_year': non_null_data.str.match(r'^\d{4}$'),
            'anul_prefix': non_null_data.str.contains(r'\banul\s+\d{4}'),
            'range_format': non_null_data.str.contains(r'\d{4}\s*-\s*\d{4}')
        }
        
        active_patterns = sum(1 for pattern in year_patterns.values() if pattern.any())
        if active_patterns > 1:
            pattern_counts = {name: pattern.sum() for name, pattern in year_patterns.items() if pattern.any()}
            pattern_issues.append(f"Mixed year formats: {pattern_counts}")
        
        # Check for quarter consistency  
        quarter_indicators = non_null_data.str.contains(r'trimestrul', case=False)
        if quarter_indicators.any() and not quarter_indicators.all():
            pattern_issues.append(f"Inconsistent quarter formatting: {quarter_indicators.sum()}/{len(non_null_data)} entries")
        
        # Check for month consistency
        month_indicators = non_null_data.str.contains(r'\bluna\b', case=False)
        if month_indicators.any() and not month_indicators.all():
            pattern_issues.append(f"Inconsistent month formatting: {month_indicators.sum()}/{len(non_null_data)} entries")
        
        if pattern_issues:
            results.append(ValidationResult(
                rule_id=self.rule_id,
                severity=ValidationSeverity.WARNING,
                message="Inconsistent temporal formatting detected",
                context={
                    "check_type": "period_formatting",
                    "issues": pattern_issues,
                    "total_values": len(non_null_data)
                },
                column_name=column_name,
                suggested_fix="Standardize temporal format across all entries"
            ))
        else:
            results.append(ValidationResult(
                rule_id=self.rule_id,
                severity=ValidationSeverity.INFO,
                message="Consistent temporal formatting",
                context={
                    "check_type": "period_formatting",
                    "pattern_type": self._detect_primary_pattern(non_null_data)
                },
                column_name=column_name
            ))
        
        return results
    
    def _detect_primary_pattern(self, data: pd.Series) -> str:
        """Detect the primary temporal pattern in the data."""
        sample = data.head(5).str.lower()
        
        if sample.str.contains(r'trimestrul').any():
            return "quarterly"
        elif sample.str.contains(r'\bluna\b').any():
            return "monthly" 
        elif sample.str.contains(r'\d{4}\s*-\s*\d{4}').any():
            return "year_range"
        elif sample.str.match(r'^\d{4}$').any():
            return "annual"
        else:
            return "mixed_temporal"


class NumericPrecisionRule(ColumnDataValidationRule):
    """
    Validates numeric precision and detects potential rounding issues.
    """
    
    def __init__(self, max_decimal_places: int = 6):
        super().__init__(
            rule_id="numeric_precision_check",
            description=f"Checks for excessive decimal precision (>{max_decimal_places} places)"
        )
        self.max_decimal_places = max_decimal_places
    
    def validate_column_data(
        self, 
        column_name: str, 
        column_data: pd.Series, 
        index: int, 
        **context
    ) -> List[ValidationResult]:
        results = []
        
        # Try to convert to numeric
        numeric_data = pd.to_numeric(column_data, errors='coerce')
        valid_numeric = numeric_data.dropna()
        
        if valid_numeric.empty:
            return results  # Not a numeric column
        
        # Check for excessive decimal places
        decimal_places = []
        for value in valid_numeric.head(100):  # Sample first 100 values
            if pd.isna(value):
                continue
            str_val = f"{value:.10f}".rstrip('0').rstrip('.')
            if '.' in str_val:
                decimal_places.append(len(str_val.split('.')[1]))
            else:
                decimal_places.append(0)
        
        if decimal_places:
            max_decimals = max(decimal_places)
            avg_decimals = sum(decimal_places) / len(decimal_places)
            
            if max_decimals > self.max_decimal_places:
                results.append(ValidationResult(
                    rule_id=self.rule_id,
                    severity=ValidationSeverity.WARNING,
                    message=f"Excessive decimal precision detected",
                    context={
                        "check_type": "decimal_precision",
                        "max_decimal_places": max_decimals,
                        "avg_decimal_places": round(avg_decimals, 2),
                        "threshold": self.max_decimal_places,
                        "sample_size": len(decimal_places)
                    },
                    column_name=column_name,
                    suggested_fix=f"Consider rounding to {self.max_decimal_places} decimal places"
                ))
        
        # Check for suspiciously round numbers (might indicate data quality issues)
        rounded_fraction = (valid_numeric % 1 == 0).mean()
        if rounded_fraction > 0.95 and len(valid_numeric) > 10:
            results.append(ValidationResult(
                rule_id=self.rule_id,
                severity=ValidationSeverity.INFO,
                message="Data appears to be predominantly whole numbers",
                context={
                    "check_type": "rounded_numbers",
                    "rounded_fraction": round(rounded_fraction, 3),
                    "total_values": len(valid_numeric)
                },
                column_name=column_name
            ))
        
        return results


class DimensionColumnOrderRule(FileStructureValidationRule):
    """
    Validates the expected order of dimension columns in INS datasets.
    Romanian INS data typically follows: [Dimensions...] -> [UM] -> [Valoare]
    """
    
    def __init__(self):
        super().__init__(
            rule_id="dimension_column_order",
            description="Validates expected column ordering for INS datasets"
        )
    
    def validate_file_structure(self, df: pd.DataFrame, **context) -> List[ValidationResult]:
        results = []
        
        if len(df.columns) < 3:
            return results  # Too few columns to validate structure
        
        columns = df.columns.tolist()
        
        # Check if last column is likely 'Valoare'
        last_col = columns[-1].lower().strip()
        is_valoare_last = 'valoare' in last_col
        
        # Check if second-to-last column is likely 'UM'
        um_col = columns[-2].lower().strip() if len(columns) >= 2 else ""
        is_um_second_last = 'um' in um_col or 'unitat' in um_col
        
        if is_valoare_last and is_um_second_last:
            results.append(ValidationResult(
                rule_id=self.rule_id,
                severity=ValidationSeverity.INFO,
                message="Standard INS column structure detected",
                context={
                    "check_type": "column_order",
                    "structure": "dimensions -> UM -> valoare",
                    "dimension_columns": len(columns) - 2
                }
            ))
        else:
            issues = []
            if not is_valoare_last:
                issues.append("Last column is not 'Valoare'")
            if not is_um_second_last:
                issues.append("Second-to-last column is not 'UM'")
            
            results.append(ValidationResult(
                rule_id=self.rule_id,
                severity=ValidationSeverity.WARNING,
                message="Non-standard column structure",
                context={
                    "check_type": "column_order",
                    "issues": issues,
                    "columns": columns
                },
                suggested_fix="Rearrange columns to: [dimensions...] -> [UM column] -> [Valoare]"
            ))
        
        return results


class DataCompletenessRule(ColumnDataValidationRule):
    """
    Validates data completeness and identifies columns with excessive missing values.
    """
    
    def __init__(self, missing_threshold: float = 0.3):
        super().__init__(
            rule_id="data_completeness_check",
            description=f"Identifies columns with >{missing_threshold*100}% missing values"
        )
        self.missing_threshold = missing_threshold
    
    def validate_column_data(
        self, 
        column_name: str, 
        column_data: pd.Series, 
        index: int, 
        **context
    ) -> List[ValidationResult]:
        results = []
        
        total_rows = len(column_data)
        if total_rows == 0:
            return results
        
        missing_count = column_data.isnull().sum()
        missing_fraction = missing_count / total_rows
        
        if missing_fraction > self.missing_threshold:
            results.append(ValidationResult(
                rule_id=self.rule_id,
                severity=ValidationSeverity.ERROR if missing_fraction > 0.7 else ValidationSeverity.WARNING,
                message=f"High percentage of missing values: {missing_fraction:.1%}",
                context={
                    "check_type": "missing_values",
                    "missing_count": missing_count,
                    "total_count": total_rows,
                    "missing_fraction": round(missing_fraction, 3),
                    "threshold": self.missing_threshold
                },
                column_name=column_name,
                suggested_fix="Investigate data collection process or consider dropping column"
            ))
        elif missing_count > 0:
            results.append(ValidationResult(
                rule_id=self.rule_id,
                severity=ValidationSeverity.INFO,
                message=f"Some missing values: {missing_fraction:.1%}",
                context={
                    "check_type": "missing_values",
                    "missing_count": missing_count,
                    "missing_fraction": round(missing_fraction, 3)
                },
                column_name=column_name
            ))
        
        return results


# Example of how to create a validator with custom rules
def create_enhanced_validator():
    """
    Creates a DataValidator with additional custom rules for INS data.
    """
    from validation_rules import DataValidator
    
    validator = DataValidator()
    
    # Add custom rules
    validator.add_rule(PeriodColumnPatternRule())
    validator.add_rule(NumericPrecisionRule(max_decimal_places=4))
    validator.add_rule(DimensionColumnOrderRule())
    validator.add_rule(DataCompletenessRule(missing_threshold=0.2))
    
    return validator


if __name__ == "__main__":
    # Example usage
    import pandas as pd
    
    # Create sample data with various issues
    sample_data = pd.DataFrame({
        "An": ["2020", "Anul 2021", "2022-2023", "2024"],  # Mixed year formats
        "Regiune": ["Nord", "Sud", None, "Centru"],  # Some missing values
        "Indicator": [1.2345678901, 2.1, 3.0, 4.5555555],  # Mixed precision
        "UM: Persoane": ["Numar", "Numar", "Numar", "Numar"],
        "Valoare": [1000, 1100, 1200, None]  # Some missing in values
    })
    
    # Create enhanced validator
    validator = create_enhanced_validator()
    
    # Run validation
    results = validator.validate_dataframe_summary(sample_data, "example.csv")
    
    # Print results
    print("Enhanced Validation Results:")
    print(f"Total checks: {results['validation_summary']['total_checks']}")
    for severity in ['error', 'warning', 'info']:
        count = results['validation_summary'].get(severity, 0)
        if count > 0:
            print(f"{severity.title()}: {count}")
    
    print("\nDetailed Results:")
    for result in results['detailed_results']:
        if result['severity'] in ['error', 'warning']:
            print(f"  {result['severity'].upper()}: {result['message']} ({result.get('column_name', 'file-level')})")
