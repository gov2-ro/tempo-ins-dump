# Modular Data Validation System

This directory contains a modular validation system that makes it easy to add, modify, and manage data quality checks for Romanian INS datasets.

## Overview

The validation system is designed around extensibility and separation of concerns:

- **`validation_rules.py`** - Core validation framework with base classes
- **`custom_validation_rules.py`** - Example custom validation rules 
- **`validation_example.py`** - Usage examples and demonstrations
- **`data_profiler.py`** - Updated to use the modular validation system

## Quick Start

### Basic Usage

```python
from validation_rules import DataValidator
import pandas as pd

# Load your data
df = pd.read_csv("your_data.csv")

# Create validator with default rules
validator = DataValidator()

# Run validation
results = validator.validate_dataframe_summary(df, "your_data.csv")

# Check results
print(f"Errors: {results['validation_summary']['error']}")
print(f"Warnings: {results['validation_summary']['warning']}")
```

### Adding Custom Rules

```python
from validation_rules import ColumnDataValidationRule, ValidationResult, ValidationSeverity

class MyCustomRule(ColumnDataValidationRule):
    def __init__(self):
        super().__init__(
            rule_id="my_custom_check",
            description="Checks for my specific requirement"
        )
    
    def validate_column_data(self, column_name, column_data, index, **context):
        results = []
        
        # Your validation logic here
        if some_condition:
            results.append(ValidationResult(
                rule_id=self.rule_id,
                severity=ValidationSeverity.WARNING,
                message="Found issue in column",
                column_name=column_name,
                suggested_fix="How to fix this issue"
            ))
        
        return results

# Add to validator
validator = DataValidator()
validator.add_rule(MyCustomRule())
```

## Built-in Validation Rules

### File Structure Rules

1. **ValoareColumnRule** - Validates presence and positioning of 'Valoare' column
2. **UMColumnRule** - Checks for Unit of Measurement column and uniformity
3. **DimensionColumnOrderRule** - Validates expected INS column structure

### Column Name Rules

1. **ColumnNameConsistencyRule** - Checks naming conventions and consistency

### Column Data Rules

1. **DataTypeConsistencyRule** - Validates data type consistency within columns
2. **PeriodColumnPatternRule** - Validates Romanian temporal formatting
3. **NumericPrecisionRule** - Checks for excessive decimal precision
4. **DataCompletenessRule** - Identifies columns with too many missing values

## Validation Severity Levels

- **CRITICAL** - System-level issues that prevent processing
- **ERROR** - Data issues that likely need fixing
- **WARNING** - Potential issues worth investigating  
- **INFO** - Informational findings about the data

## Rule Types

### ColumnNameValidationRule
For validating column headers and names:
```python
class MyColumnNameRule(ColumnNameValidationRule):
    def validate_column_name(self, column_name, index, **context):
        # Check column name
        return [ValidationResult(...)]
```

### ColumnDataValidationRule  
For validating the content of individual columns:
```python
class MyDataRule(ColumnDataValidationRule):
    def validate_column_data(self, column_name, column_data, index, **context):
        # Check column data
        return [ValidationResult(...)]
```

### FileStructureValidationRule
For validating overall file structure:
```python
class MyStructureRule(FileStructureValidationRule):
    def validate_file_structure(self, df, **context):
        # Check overall structure
        return [ValidationResult(...)]
```

## Integration with Data Profiler

The updated `data_profiler.py` automatically uses the validation system:

```bash
# Run with validation
python data_profiler.py path/to/data.csv --orchestrate

# The output JSON will include validation results:
{
  "file_checks": {
    "last_col_is_valoare": true,
    "um_col_exists": true,
    "validation_results": [...],
    "validation_summary": {"error": 0, "warning": 2, "info": 5}
  },
  "columns": [...]
}
```

## Examples

### Check Column Names
```python
from custom_validation_rules import DataCompletenessRule

# Add rule to check for missing data
validator = DataValidator()
validator.add_rule(DataCompletenessRule(missing_threshold=0.1))  # 10% threshold
```

### Validate Temporal Columns
```python
from custom_validation_rules import PeriodColumnPatternRule

# Check Romanian temporal formatting
validator = DataValidator() 
validator.add_rule(PeriodColumnPatternRule())
```

### Remove Unwanted Rules
```python
validator = DataValidator()
validator.remove_rule("data_type_consistency")  # Remove if not needed
```

## Adding Your Own Rules

1. **Identify the rule type** - Column name, column data, or file structure
2. **Inherit from appropriate base class** 
3. **Implement the validation method**
4. **Return ValidationResult objects**
5. **Add to validator**

### Example: Detect Romanian County Names

```python
class CountyNameRule(ColumnDataValidationRule):
    def __init__(self):
        super().__init__(
            rule_id="romanian_county_check",
            description="Validates Romanian county names"
        )
        
        # Romanian county names
        self.counties = {
            'alba', 'arad', 'arges', 'bacau', 'bihor', 'bistrita-nasaud',
            'botosani', 'brasov', 'braila', 'buzau', 'caras-severin',
            'calarasi', 'cluj', 'constanta', 'covasna', 'dambovita',
            'dolj', 'galati', 'giurgiu', 'gorj', 'harghita', 'hunedoara',
            'ialomita', 'iasi', 'ilfov', 'maramures', 'mehedinti',
            'mures', 'neamt', 'olt', 'prahova', 'satu-mare', 'salaj',
            'sibiu', 'suceava', 'teleorman', 'timis', 'tulcea',
            'vaslui', 'valcea', 'vrancea', 'bucuresti'
        }
    
    def validate_column_data(self, column_name, column_data, index, **context):
        results = []
        
        # Check if column name suggests it contains counties
        col_lower = column_name.lower()
        if 'judet' not in col_lower and 'regiune' not in col_lower:
            return results
        
        # Check data
        if column_data.dtype == 'object':
            non_null = column_data.dropna().str.lower().str.strip()
            unknown_counties = []
            
            for value in non_null.unique():
                if value not in self.counties and value not in ['total', 'national']:
                    unknown_counties.append(value)
            
            if unknown_counties:
                results.append(ValidationResult(
                    rule_id=self.rule_id,
                    severity=ValidationSeverity.WARNING,
                    message=f"Unknown county names detected: {unknown_counties[:3]}",
                    context={"unknown_counties": unknown_counties},
                    column_name=column_name,
                    suggested_fix="Verify county names against official Romanian list"
                ))
        
        return results

# Usage
validator = DataValidator()
validator.add_rule(CountyNameRule())
```

## Benefits

1. **Modular** - Add only the checks you need
2. **Extensible** - Easy to add new validation rules
3. **Consistent** - Standardized result format
4. **Detailed** - Rich context and suggestions for fixes
5. **Integrated** - Works with existing data profiler workflow
6. **Testable** - Each rule can be tested independently

## Best Practices

1. **Start with built-in rules** - They handle common INS data patterns
2. **Add custom rules incrementally** - Start simple, add complexity as needed
3. **Use appropriate severity levels** - INFO for observations, ERROR for real issues
4. **Provide suggested fixes** - Help users understand how to resolve issues
5. **Include context** - Add relevant metrics and details to validation results
6. **Test your rules** - Validate rules work correctly with sample data

Run `python validation_example.py` to see the system in action!


# Roadmap / TODOs

-[x] check if all files:
    -[x] have a variable/column named 'Valoare'
    -[x] have a valoare (last), UM (measuring unit) (second to last) and time (third to last) type columns at least

-[ ] column **label** checks 
    -[x] has '`', '|' or `,` in the name: label as `n-multiple`
    -[ ] has `Valoare` as the last column and all values are numbers
    -[x] geo Localitati|Judete|Macroregiuni, regiuni de dezvoltare si judete. has any of (regiuni, regiuni + dezvoltare, macroregiuni) - mark as such -> `n-geo` + `n-geo-localitati`, `n-geo-judete`, `n-geo-regiuni`, `n-geo-regiuni-dezvoltare`
    -[x] is time? is named: `Perioade|Luni|Trimestre|Ani` - mark it as `n-time`, `n-time-perioade`, `n-time-ani`, `n-time-luni` (it can have more types in one ex: [`n-time`, `n-time-ani`, `n-time-trimestre`])

-[ ] columns **data/values** checks
    -[x] is time: has `Anul <year>` | `luna august 2025` | `Trimestrul IV 2004` values, same labeling as above `d-time`, `d-time-ani`, `d-time-trimestre`
    -[x] has masculin / feminin `gender` (always check with and against lowercase) ✅ **ColumnDataGenderRule**
        -[x] has only masculin / feminin `gender-exclusive` ✅ **ColumnDataGenderRule**
    -[ ] has a preffix / suffix type of string (special case, multiple: time, where can have Perioade, Luni, Trimestre or grupe de varsta) `d-preffix`
    -[x] grupe vârstă `18-24 ani` ori vârstă (`9 ani`): `d-grupe-varsta`, `d-varste` ✅ **ColumnDataAgeGroupRule**
    -[x] has `rural` or `urban`? `d-mediu-geo` and `d-mediu-geo-exclusive` no other values besides rural/urban are found ✅ **ColumnDataResidenceRule**
    -[ ] has `total`? - has `total-{string}` ? - add `total-{string}` to labels
    -[ ] if detected kind, do all rows validate?
    -[ ] geo
        -[x] check common județe names to guess if it contains judete (Bihor, Gorj, Dolj, Hunedoara, Ilfov, Prahova) - `d-geo-judete` and add also precentage foud (of the attached list) `d-geo-judete-{number}` ✅ **ColumnDataGeographicRule**
        -[x] check common localități names to guess if it contains localități (Tuzla, Aiud) similar to above `d-geo-localitati*` ✅ **ColumnDataGeographicRule**
        -[x] regiuni: has `Regiunea {string}` `d-geo-regiune` ✅ **ColumnDataGeographicRule**
        -[x] macroregiuni: has `MACROREGIUNEA {string}` `d-geo-macroregiune` ✅ **ColumnDataGeographicRule**
        -[x] if any of the above, label it as `d-geo` ✅ **ColumnDataGeographicRule**
    -[ ] count values
    -[x] count unique values

-[ ] flags columns with inconsistencies between name and data guessed types

column label guesses/labeling are prefixed with `n-` (from name), content guesses are prefixed with `d-` (from data)
add a variable with all those flags as list, not a column for each.