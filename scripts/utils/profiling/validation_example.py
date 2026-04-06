"""
Example: Using the Enhanced Validation System

This script demonstrates how to use the modular validation system 
with both built-in and custom rules for INS data validation.
"""

import pandas as pd
from validation_rules import DataValidator
from custom_validation_rules import create_enhanced_validator


def example_basic_validation():
    """Example using basic validation rules."""
    print("=== Basic Validation Example ===")
    
    # Create sample data
    data = pd.DataFrame({
        "An": ["2020", "2021", "2022"],
        "Regiune": ["Nord   ", "Sud", "Centru"],  # Note: whitespace in first entry
        "UM: Persoane": ["Numar", "Numar", "Numar"],
        "Valoare": [1000, 1100, 1200]
    })
    
    validator = DataValidator()
    results = validator.validate_dataframe_summary(data, "basic_example.csv")
    
    print(f"Total validation checks: {results['validation_summary']['total_checks']}")
    print(f"Errors: {results['validation_summary']['error']}")
    print(f"Warnings: {results['validation_summary']['warning']}")
    print(f"Info: {results['validation_summary']['info']}")
    print()


def example_enhanced_validation():
    """Example using enhanced validation with custom rules."""
    print("=== Enhanced Validation Example ===")
    
    # Create sample data with more issues
    data = pd.DataFrame({
        "Perioada": ["2020", "Anul 2021", "2022-2023", "2024"],  # Mixed formats
        "Regiune": ["Nord", "Sud", None, "Centru"],  # Missing values
        "Indicator": [1.2345678901, 2.1, 3.0, 4.5555555],  # Precision issues
        "UM: Persoane": ["Numar", "Numar", "Numar", "Numar"],
        "Valoare": [1000, 1100, 1200, None]  # Missing value
    })
    
    validator = create_enhanced_validator()
    results = validator.validate_dataframe_summary(data, "enhanced_example.csv")
    
    print(f"Total validation checks: {results['validation_summary']['total_checks']}")
    print(f"Errors: {results['validation_summary']['error']}")
    print(f"Warnings: {results['validation_summary']['warning']}")
    print(f"Info: {results['validation_summary']['info']}")
    
    print("\nDetailed Issues:")
    for result in results['detailed_results']:
        if result['severity'] in ['error', 'warning']:
            col_info = f" (Column: {result['column_name']})" if result.get('column_name') else ""
            print(f"  {result['severity'].upper()}: {result['message']}{col_info}")
            if result.get('suggested_fix'):
                print(f"    Fix: {result['suggested_fix']}")
    print()


def example_adding_custom_rule():
    """Example of adding a single custom rule."""
    print("=== Adding Custom Rule Example ===")
    
    from validation_rules import ColumnDataValidationRule, ValidationResult, ValidationSeverity
    
    class SimplePercentageRule(ColumnDataValidationRule):
        """Simple rule to detect percentage-like columns."""
        
        def __init__(self):
            super().__init__(
                rule_id="simple_percentage_check",
                description="Detects columns that might contain percentages"
            )
        
        def validate_column_data(self, column_name, column_data, index, **context):
            results = []
            
            if column_data.dtype == 'object':
                str_data = column_data.dropna().astype(str)
                if str_data.str.endswith('%').any():
                    pct_count = str_data.str.endswith('%').sum()
                    results.append(ValidationResult(
                        rule_id=self.rule_id,
                        severity=ValidationSeverity.INFO,
                        message=f"Column contains {pct_count} percentage values",
                        context={"percentage_count": pct_count},
                        column_name=column_name
                    ))
            
            return results
    
    # Create data with percentages
    data = pd.DataFrame({
        "Categorie": ["A", "B", "C"],
        "Procent": ["45%", "32%", "23%"],
        "Valoare": [100, 200, 300]
    })
    
    validator = DataValidator()
    validator.add_rule(SimplePercentageRule())
    
    results = validator.validate_dataframe_summary(data, "percentage_example.csv")
    
    for result in results['detailed_results']:
        if result['rule_id'] == 'simple_percentage_check':
            print(f"Custom Rule Result: {result['message']}")
    print()


def example_validation_with_real_file():
    """Example of validating an actual CSV file."""
    print("=== Real File Validation Example ===")
    print("This would work with an actual CSV file:")
    print()
    
    code_example = '''
    validator = create_enhanced_validator()
    
    # Validate a real CSV file
    df = pd.read_csv("path/to/your/ins_data.csv")
    results = validator.validate_dataframe_summary(df, "path/to/your/ins_data.csv")
    
    # Print summary
    print(f"Validation Summary for {results['file_path']}:")
    for severity, count in results['validation_summary'].items():
        if count > 0:
            print(f"  {severity}: {count}")
    
    # Print critical issues only
    for result in results['detailed_results']:
        if result['severity'] in ['error', 'critical']:
            print(f"CRITICAL: {result['message']}")
            if result.get('suggested_fix'):
                print(f"  Suggested fix: {result['suggested_fix']}")
    '''
    
    print(code_example)


if __name__ == "__main__":
    try:
        example_basic_validation()
        example_enhanced_validation()
        example_adding_custom_rule()
        example_validation_with_real_file()
        
        print("=== Summary ===")
        print("The validation system is now modular and extensible!")
        print("You can:")
        print("1. Use built-in rules for common INS data checks")
        print("2. Add custom rules for specific requirements")
        print("3. Remove rules you don't need")
        print("4. Get detailed reports with severity levels")
        print("5. Integrate with your existing profiling workflow")
        
    except ImportError as e:
        print(f"Import error: {e}")
        print("This example requires pandas. Install it or run from your data profiler environment.")
    except Exception as e:
        print(f"Error running example: {e}")
