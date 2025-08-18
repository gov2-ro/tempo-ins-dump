"""
Validation Rules System for Romanian INS Data Profiler

This module provides a modular validation framework that allows easy addition
of new data quality checks. Each validation rule is a separate class that 
implements specific checks for column names, data content, or file structure.

The system supports:
- Column name/label validation
- Data content validation (type inference, constraints)
- File structure validation
- Extensible rule registration system
- Detailed reporting with severity levels

Usage:
    validator = DataValidator()
    results = validator.validate_dataframe(df, file_path="path/to/file.csv")
"""

import pandas as pd
import re
import unicodedata
import numpy as np
from typing import Dict, List, Any, Optional, Union, Tuple
from abc import ABC, abstractmethod
from enum import Enum


class ValidationSeverity(Enum):
    """Severity levels for validation results."""
    INFO = "info"
    WARNING = "warning" 
    ERROR = "error"
    CRITICAL = "critical"


class ValidationResult:
    """Container for validation check results."""
    
    def __init__(
        self,
        rule_id: str,
        severity: ValidationSeverity,
        message: str,
        context: Dict[str, Any] = None,
        column_name: str = None,
        suggested_fix: str = None
    ):
        self.rule_id = rule_id
        self.severity = severity
        self.message = message
        self.context = context or {}
        self.column_name = column_name
        self.suggested_fix = suggested_fix
        
    def to_dict(self) -> Dict[str, Any]:
        """Convert result to dictionary for JSON serialization."""
        return {
            "rule_id": self.rule_id,
            "severity": self.severity.value,
            "message": self.message,
            "context": self.context,
            "column_name": self.column_name,
            "suggested_fix": self.suggested_fix
        }


class ValidationRule(ABC):
    """Abstract base class for all validation rules."""
    
    def __init__(self, rule_id: str, description: str):
        self.rule_id = rule_id
        self.description = description
    
    @abstractmethod
    def validate(self, df: pd.DataFrame, **context) -> List[ValidationResult]:
        """
        Execute the validation rule.
        
        Args:
            df: The dataframe to validate
            **context: Additional context (file_path, etc.)
            
        Returns:
            List of ValidationResult objects
        """
        pass


class ColumnNameValidationRule(ValidationRule):
    """Base class for column name/header validation rules."""
    
    def validate_column_name(self, column_name: str, index: int, **context) -> List[ValidationResult]:
        """
        Validate a specific column name.
        
        Args:
            column_name: The column name to validate
            index: Column index (0-based)
            **context: Additional context
            
        Returns:
            List of ValidationResult objects for this column
        """
        return []
    
    def validate(self, df: pd.DataFrame, **context) -> List[ValidationResult]:
        """Execute column name validation for all columns."""
        results = []
        for i, col_name in enumerate(df.columns):
            results.extend(self.validate_column_name(col_name, i, **context))
        return results


class ColumnDataValidationRule(ValidationRule):
    """Base class for column data content validation rules."""
    
    def validate_column_data(
        self, 
        column_name: str, 
        column_data: pd.Series, 
        index: int, 
        **context
    ) -> List[ValidationResult]:
        """
        Validate the data content of a specific column.
        
        Args:
            column_name: Name of the column
            column_data: The column data as pandas Series
            index: Column index (0-based)
            **context: Additional context
            
        Returns:
            List of ValidationResult objects for this column
        """
        return []
    
    def validate(self, df: pd.DataFrame, **context) -> List[ValidationResult]:
        """Execute column data validation for all columns."""
        results = []
        for i, (col_name, col_data) in enumerate(df.items()):
            results.extend(self.validate_column_data(col_name, col_data, i, **context))
        return results


class FileStructureValidationRule(ValidationRule):
    """Base class for file-level structure validation rules."""
    
    def validate_file_structure(self, df: pd.DataFrame, **context) -> List[ValidationResult]:
        """
        Validate overall file structure.
        
        Args:
            df: The complete dataframe
            **context: Additional context (file_path, etc.)
            
        Returns:
            List of ValidationResult objects
        """
        return []
    
    def validate(self, df: pd.DataFrame, **context) -> List[ValidationResult]:
        """Execute file structure validation."""
        return self.validate_file_structure(df, **context)


# Concrete validation rule implementations

class ValoareColumnRule(FileStructureValidationRule):
    """Validates presence and position of 'Valoare' column."""
    
    def __init__(self):
        super().__init__(
            rule_id="valoare_column_check",
            description="Checks for presence and proper positioning of 'Valoare' column"
        )
    
    def _normalize_header(self, header: str) -> str:
        """Normalize header for comparison."""
        h = str(header)
        h = unicodedata.normalize('NFKD', h).encode('ascii', 'ignore').decode('ascii')
        h = h.lower().strip()
        h = re.sub(r"[^a-z0-9:_ ]+", '', h)
        h = re.sub(r"\s+", ' ', h)
        return h
    
    def validate_file_structure(self, df: pd.DataFrame, **context) -> List[ValidationResult]:
        results = []
        
        if df.empty:
            results.append(ValidationResult(
                rule_id=self.rule_id,
                severity=ValidationSeverity.CRITICAL,
                message="DataFrame is empty",
                context={"check_type": "empty_file"}
            ))
            return results
        
        last_col_name = df.columns[-1]
        normalized_last = self._normalize_header(last_col_name)
        
        # Check if last column is 'valoare' by name or by content (mostly numeric)
        is_valoare_by_name = (
            normalized_last == 'valoare' or 
            normalized_last.startswith('valoare')
        )
        
        try:
            numeric_fraction = pd.to_numeric(df[last_col_name], errors='coerce').notnull().mean()
        except Exception:
            numeric_fraction = 0.0
        
        is_valoare_by_content = numeric_fraction >= 0.9
        
        if is_valoare_by_name or is_valoare_by_content:
            results.append(ValidationResult(
                rule_id=self.rule_id,
                severity=ValidationSeverity.INFO,
                message="Valid 'Valoare' column detected",
                context={
                    "check_type": "valoare_column_valid",
                    "column_name": last_col_name,
                    "by_name": is_valoare_by_name,
                    "by_content": is_valoare_by_content,
                    "numeric_fraction": round(numeric_fraction, 3)
                },
                column_name=last_col_name
            ))
        else:
            results.append(ValidationResult(
                rule_id=self.rule_id,
                severity=ValidationSeverity.ERROR,
                message="Missing or invalid 'Valoare' column",
                context={
                    "check_type": "valoare_column_missing",
                    "last_column": last_col_name,
                    "numeric_fraction": round(numeric_fraction, 3)
                },
                suggested_fix="Ensure the last column contains 'Valoare' in the header or is predominantly numeric"
            ))
        
        return results


class UMColumnRule(FileStructureValidationRule):
    """Validates presence and uniformity of Unit of Measurement (UM) column."""
    
    def __init__(self):
        super().__init__(
            rule_id="um_column_check", 
            description="Checks for presence and uniformity of Unit of Measurement column"
        )
    
    def _normalize_header(self, header: str) -> str:
        """Normalize header for comparison."""
        h = str(header)
        h = unicodedata.normalize('NFKD', h).encode('ascii', 'ignore').decode('ascii')
        h = h.lower().strip()
        h = re.sub(r"[^a-z0-9:_ ]+", '', h)
        h = re.sub(r"\s+", ' ', h)
        return h
    
    def validate_file_structure(self, df: pd.DataFrame, **context) -> List[ValidationResult]:
        results = []
        
        if df.empty or len(df.columns) < 2:
            return results
        
        columns = df.columns
        normalized_headers = [self._normalize_header(h) for h in columns]
        
        # Look for UM column - prefer penultimate, otherwise search headers
        um_col_name = None
        penultimate_header = columns[-2]
        penultimate_norm = self._normalize_header(penultimate_header)
        
        if (penultimate_norm.startswith('um') or 
            penultimate_norm.startswith('um:') or 
            penultimate_norm in ('unitati de masura', 'unitate de masura', 'unitati_masura')):
            um_col_name = penultimate_header
        else:
            # Search all headers for UM-like patterns
            for orig, norm in zip(columns, normalized_headers):
                if (norm.startswith('um') or 
                    'unitat' in norm or 
                    norm.startswith('unitati')):
                    um_col_name = orig
                    break
        
        if um_col_name is None:
            results.append(ValidationResult(
                rule_id=self.rule_id,
                severity=ValidationSeverity.WARNING,
                message="No Unit of Measurement (UM) column found",
                context={"check_type": "um_column_missing"},
                suggested_fix="Add a column with 'UM:' prefix or containing 'Unitate de masura'"
            ))
            return results
        
        # Analyze UM column uniformity
        uniformity_result = self._analyze_um_uniformity(df, um_col_name)
        results.append(uniformity_result)
        
        return results
    
    def _analyze_um_uniformity(self, df: pd.DataFrame, um_col_name: str) -> ValidationResult:
        """Analyze the uniformity of values in the UM column."""
        um_series_raw = df[um_col_name].dropna().astype(str)
        
        if um_series_raw.empty:
            return ValidationResult(
                rule_id=self.rule_id,
                severity=ValidationSeverity.WARNING,
                message="UM column exists but contains no values",
                context={
                    "check_type": "um_uniformity",
                    "uniformity": "No values"
                },
                column_name=um_col_name
            )
        
        # Normalize UM values for comparison
        def normalize_um_value(s: str) -> str:
            s = str(s).strip()
            s = unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode('ascii')
            s = re.sub(r'^(um[:\-\s]+)', '', s, flags=re.I)  # Remove UM: prefix
            s = s.lower().strip()
            s = re.sub(r"[^a-z0-9 ]+", ' ', s)
            s = re.sub(r"\s+", ' ', s)
            return s
        
        normalized_values = um_series_raw.map(normalize_um_value)
        valid = normalized_values.replace('', np.nan).dropna()
        
        if valid.empty:
            return ValidationResult(
                rule_id=self.rule_id,
                severity=ValidationSeverity.WARNING,
                message="UM column contains only empty values",
                context={
                    "check_type": "um_uniformity",
                    "uniformity": "No non-empty values"
                },
                column_name=um_col_name
            )
        
        counts = valid.value_counts()
        top_norm = counts.index[0]
        top_count = counts.iloc[0]
        uniformity_fraction = top_count / len(valid)
        
        if uniformity_fraction >= 0.95:
            # Find most common original value for this normalized value
            mask = normalized_values == top_norm
            try:
                representative_value = um_series_raw[mask].str.strip().mode().iloc[0]
            except Exception:
                representative_value = um_series_raw[mask].iloc[0].strip()
            
            # Clean up the representative value
            representative_value = re.sub(r'^(um[:\-\s]+)', '', representative_value, flags=re.I).strip()
            
            return ValidationResult(
                rule_id=self.rule_id,
                severity=ValidationSeverity.INFO,
                message="UM column is uniform",
                context={
                    "check_type": "um_uniformity",
                    "uniformity": "Uniform",
                    "uniformity_fraction": round(uniformity_fraction, 3),
                    "representative_value": representative_value,
                    "total_values": len(valid)
                },
                column_name=um_col_name
            )
        else:
            # Get top 3 most common values
            top_raw_values = um_series_raw.str.strip().value_counts().index[:3].tolist()
            top_raw_values = [re.sub(r'^(um[:\-\s]+)', '', t, flags=re.I).strip() for t in top_raw_values]
            
            return ValidationResult(
                rule_id=self.rule_id,
                severity=ValidationSeverity.WARNING,
                message="UM column is not uniform",
                context={
                    "check_type": "um_uniformity",
                    "uniformity": "Not Uniform",
                    "uniformity_fraction": round(uniformity_fraction, 3),
                    "top_values": top_raw_values,
                    "total_values": len(valid),
                    "unique_values": len(counts)
                },
                column_name=um_col_name,
                suggested_fix="Consider standardizing unit values for consistency"
            )


class ColumnNameConsistencyRule(ColumnNameValidationRule):
    """Validates column naming consistency and conventions."""
    
    def __init__(self):
        super().__init__(
            rule_id="column_name_consistency",
            description="Checks column names for consistency with INS naming conventions"
        )
    
    def validate_column_name(self, column_name: str, index: int, **context) -> List[ValidationResult]:
        results = []
        
        # Check for excessive whitespace
        if column_name != column_name.strip():
            results.append(ValidationResult(
                rule_id=self.rule_id,
                severity=ValidationSeverity.WARNING,
                message="Column name has leading/trailing whitespace",
                context={
                    "check_type": "whitespace",
                    "original": repr(column_name),
                    "cleaned": column_name.strip()
                },
                column_name=column_name,
                suggested_fix="Remove leading/trailing whitespace"
            ))
        
        # Check for very long column names
        if len(column_name) > 100:
            results.append(ValidationResult(
                rule_id=self.rule_id,
                severity=ValidationSeverity.WARNING,
                message="Column name is very long",
                context={
                    "check_type": "length",
                    "length": len(column_name),
                    "column_name": column_name[:50] + "..." if len(column_name) > 50 else column_name
                },
                column_name=column_name,
                suggested_fix="Consider shortening column name for better readability"
            ))
        
        # Check for empty or null column names
        if not column_name or str(column_name).strip() == '' or str(column_name).lower() in ['unnamed', 'nan']:
            results.append(ValidationResult(
                rule_id=self.rule_id,
                severity=ValidationSeverity.ERROR,
                message="Column name is empty or invalid",
                context={
                    "check_type": "empty",
                    "column_index": index
                },
                column_name=column_name,
                suggested_fix="Provide a meaningful column name"
            ))
        
        return results


class DataTypeConsistencyRule(ColumnDataValidationRule):
    """Validates data type consistency within columns."""
    
    def __init__(self):
        super().__init__(
            rule_id="data_type_consistency",
            description="Checks for data type consistency and mixed types within columns"
        )
    
    def validate_column_data(
        self, 
        column_name: str, 
        column_data: pd.Series, 
        index: int, 
        **context
    ) -> List[ValidationResult]:
        results = []
        
        if column_data.empty:
            results.append(ValidationResult(
                rule_id=self.rule_id,
                severity=ValidationSeverity.WARNING,
                message="Column is empty",
                context={"check_type": "empty_column"},
                column_name=column_name
            ))
            return results
        
        # Check for mixed numeric/string types
        non_null_data = column_data.dropna()
        if non_null_data.empty:
            results.append(ValidationResult(
                rule_id=self.rule_id,
                severity=ValidationSeverity.INFO,
                message="Column contains only null values",
                context={"check_type": "all_null"},
                column_name=column_name
            ))
            return results
        
        # Try to detect mixed types by checking conversion success rates
        if non_null_data.dtype == 'object':  # String-like data
            # Check if some values are numeric
            numeric_conversion = pd.to_numeric(non_null_data, errors='coerce')
            numeric_success_rate = numeric_conversion.notnull().mean()
            
            if 0.1 < numeric_success_rate < 0.9:  # Mixed numeric/string
                results.append(ValidationResult(
                    rule_id=self.rule_id,
                    severity=ValidationSeverity.WARNING,
                    message="Column contains mixed numeric and non-numeric values",
                    context={
                        "check_type": "mixed_types",
                        "numeric_success_rate": round(numeric_success_rate, 3),
                        "total_values": len(non_null_data),
                        "numeric_values": int(numeric_conversion.notnull().sum())
                    },
                    column_name=column_name,
                    suggested_fix="Consider data cleaning or type conversion"
                ))
        
        # Check for percentage values mixed with regular numbers
        if non_null_data.dtype in ['object']:
            percent_pattern = non_null_data.astype(str).str.endswith('%')
            percent_rate = percent_pattern.mean() if len(percent_pattern) > 0 else 0
            
            if 0.1 < percent_rate < 0.9:  # Mixed percentage and non-percentage
                results.append(ValidationResult(
                    rule_id=self.rule_id,
                    severity=ValidationSeverity.WARNING,
                    message="Column contains mixed percentage and non-percentage values",
                    context={
                        "check_type": "mixed_percentage",
                        "percentage_rate": round(percent_rate, 3),
                        "total_values": len(non_null_data)
                    },
                    column_name=column_name,
                    suggested_fix="Standardize format (all percentages or all raw numbers)"
                ))
        
        return results


class DataValidator:
    """Main data validation orchestrator."""
    
    def __init__(self):
        self.rules: List[ValidationRule] = []
        self._register_default_rules()
    
    def _register_default_rules(self):
        """Register the default set of validation rules."""
        self.rules = [
            ValoareColumnRule(),
            UMColumnRule(),
            ColumnNameConsistencyRule(),
            DataTypeConsistencyRule(),
        ]
    
    def add_rule(self, rule: ValidationRule):
        """Add a custom validation rule."""
        self.rules.append(rule)
    
    def remove_rule(self, rule_id: str) -> bool:
        """Remove a rule by ID. Returns True if rule was found and removed."""
        original_count = len(self.rules)
        self.rules = [r for r in self.rules if r.rule_id != rule_id]
        return len(self.rules) < original_count
    
    def validate_dataframe(
        self, 
        df: pd.DataFrame, 
        file_path: str = None,
        **additional_context
    ) -> List[ValidationResult]:
        """
        Run all validation rules on a dataframe.
        
        Args:
            df: DataFrame to validate
            file_path: Optional file path for context
            **additional_context: Additional context to pass to rules
            
        Returns:
            List of all validation results
        """
        context = {
            "file_path": file_path,
            **additional_context
        }
        
        all_results = []
        for rule in self.rules:
            try:
                results = rule.validate(df, **context)
                all_results.extend(results)
            except Exception as e:
                # If a rule fails, create an error result instead of crashing
                all_results.append(ValidationResult(
                    rule_id=rule.rule_id,
                    severity=ValidationSeverity.ERROR,
                    message=f"Validation rule failed: {str(e)}",
                    context={"error_type": "rule_execution_error", "exception": str(e)}
                ))
        
        return all_results
    
    def validate_dataframe_summary(
        self, 
        df: pd.DataFrame, 
        file_path: str = None,
        **additional_context
    ) -> Dict[str, Any]:
        """
        Run validation and return a summary with counts by severity.
        
        Returns:
            Dictionary with validation summary and detailed results
        """
        results = self.validate_dataframe(df, file_path, **additional_context)
        
        # Count by severity
        severity_counts = {}
        for severity in ValidationSeverity:
            severity_counts[severity.value] = sum(
                1 for r in results if r.severity == severity
            )
        
        # Extract file-level checks for backward compatibility
        file_checks = {}
        for result in results:
            if result.rule_id == "valoare_column_check":
                file_checks["last_col_is_valoare"] = result.severity in [ValidationSeverity.INFO]
            elif result.rule_id == "um_column_check":
                if "um_column_missing" in result.context.get("check_type", ""):
                    file_checks["um_col_exists"] = False
                elif "um_uniformity" in result.context.get("check_type", ""):
                    file_checks["um_col_exists"] = True
                    file_checks["um_col_uniformity"] = result.context.get("uniformity", "N/A")
                    file_checks["um_value"] = result.context.get("representative_value") or result.context.get("top_values", ["N/A"])[0] if isinstance(result.context.get("top_values"), list) else "N/A"
        
        return {
            "file_path": file_path,
            "validation_summary": {
                "total_checks": len(results),
                **severity_counts
            },
            "file_checks": file_checks,
            "detailed_results": [r.to_dict() for r in results]
        }


if __name__ == "__main__":
    # Example usage
    import pandas as pd
    
    # Create sample data
    sample_data = pd.DataFrame({
        "An": ["2020", "2021", "2022"],
        "Regiune": ["Nord", "Sud", "Centru"], 
        "UM: Persoane": ["Numar", "Numar", "Numar"],
        "Valoare": [1000, 1100, 1200]
    })
    
    validator = DataValidator()
    results = validator.validate_dataframe_summary(sample_data, "sample.csv")
    
    print("Validation Summary:")
    print(f"Total checks: {results['validation_summary']['total_checks']}")
    print(f"Errors: {results['validation_summary']['error']}")
    print(f"Warnings: {results['validation_summary']['warning']}")
    print(f"Info: {results['validation_summary']['info']}")
