"""
INS-specific Validation Rules for Romanian Statistical Data

This module implements validation rules specifically designed for Romanian 
National Institute of Statistics (INS) data requirements.
"""

import pandas as pd
import re
import unicodedata
from typing import List, Dict, Set
from validation_rules import (
    FileStructureValidationRule, 
    ColumnNameValidationRule,
    ColumnDataValidationRule,
    ValidationResult, 
    ValidationSeverity
)


class INSFileStructureRule(FileStructureValidationRule):
    """
    Validates that files follow the expected INS structure:
    [...dimensions] -> [UM column] -> [Valoare column]
    Also checks for presence of temporal dimension.
    """
    
    def __init__(self):
        super().__init__(
            rule_id="ins_file_structure",
            description="Validates INS file structure: dimensions -> UM -> Valoare, with temporal column"
        )
    
    def validate_file_structure(self, df: pd.DataFrame, **context) -> List[ValidationResult]:
        results = []
        
        if df.empty or len(df.columns) < 3:
            results.append(ValidationResult(
                rule_id=self.rule_id,
                severity=ValidationSeverity.CRITICAL,
                message="File has fewer than 3 columns, cannot validate INS structure",
                context={"check_type": "insufficient_columns", "column_count": len(df.columns)},
                suggested_fix="INS files should have at least temporal, UM, and Valoare columns"
            ))
            return results
        
        columns = df.columns.tolist()
        
        # Check last column (should be Valoare)
        last_col = columns[-1]
        is_valoare_last = self._is_valoare_column(df, last_col)
        
        # Check second to last column (should be UM)
        second_last_col = columns[-2]
        is_um_second_last = self._is_um_column(second_last_col)
        
        # Check third to last column (should be temporal)
        third_last_col = columns[-3] if len(columns) >= 3 else None
        is_time_third_last = self._is_temporal_column(third_last_col) if third_last_col else False
        
        # Track structure issues
        structure_issues = []
        structure_flags = []
        
        if not is_valoare_last:
            structure_issues.append("Last column is not 'Valoare'")
            structure_flags.append("no-valoare-last")
        
        if not is_um_second_last:
            structure_issues.append("Second-to-last column is not UM (measuring unit)")
            structure_flags.append("no-um-second-last")
        
        if not is_time_third_last and len(columns) >= 3:
            structure_issues.append("Third-to-last column does not appear to be temporal")
            structure_flags.append("no-time-third-last")
        
        # Generate validation result
        if structure_issues:
            results.append(ValidationResult(
                rule_id=self.rule_id,
                severity=ValidationSeverity.WARNING,
                message=f"Non-standard INS file structure detected",
                context={
                    "check_type": "file_structure",
                    "issues": structure_issues,
                    "structure_flags": structure_flags,
                    "columns": columns,
                    "expected_structure": "dimensions -> UM -> Valoare"
                },
                suggested_fix="Rearrange columns to follow INS standard: [...dimensions] -> [UM] -> [Valoare]"
            ))
        else:
            results.append(ValidationResult(
                rule_id=self.rule_id,
                severity=ValidationSeverity.INFO,
                message="File follows standard INS structure",
                context={
                    "check_type": "file_structure",
                    "structure_flags": ["standard-ins-structure"],
                    "dimension_columns": len(columns) - 2
                }
            ))
        
        return results
    
    def _is_valoare_column(self, df: pd.DataFrame, column_name: str) -> bool:
        """Check if column is likely a 'Valoare' column."""
        # Check by name
        col_lower = column_name.lower().strip()
        if 'valoare' in col_lower:
            return True
        
        # Check by content (mostly numeric)
        try:
            numeric_fraction = pd.to_numeric(df[column_name], errors='coerce').notnull().mean()
            return numeric_fraction >= 0.9
        except:
            return False
    
    def _is_um_column(self, column_name: str) -> bool:
        """Check if column is likely a UM (measuring unit) column."""
        col_lower = column_name.lower().strip()
        return (
            col_lower.startswith('um') or 
            'unitat' in col_lower or 
            'masura' in col_lower
        )
    
    def _is_temporal_column(self, column_name: str) -> bool:
        """Check if column is likely temporal based on name."""
        if not column_name:
            return False
        
        col_lower = column_name.lower().strip()
        temporal_keywords = [
            'an', 'ani', 'anul', 'perioada', 'perioade',
            'luna', 'luni', 'trimestru', 'trimestre',
            'semestru', 'semestre', 'timp', 'data'
        ]
        
        return any(keyword in col_lower for keyword in temporal_keywords)


class ColumnNameMultipleIndicatorRule(ColumnNameValidationRule):
    """
    Detects column names that contain multiple value indicators like ', |, or ,.
    Labels these columns as 'n-multiple'.
    """
    
    def __init__(self):
        super().__init__(
            rule_id="column_name_multiple_indicator",
            description="Detects columns with multiple value indicators (', |, ,) in names"
        )
    
    def validate_column_name(self, column_name: str, index: int, **context) -> List[ValidationResult]:
        results = []
        
        # Check for multiple value indicators
        multiple_chars = ["'", "|", ","]
        found_chars = [char for char in multiple_chars if char in column_name]
        
        if found_chars:
            results.append(ValidationResult(
                rule_id=self.rule_id,
                severity=ValidationSeverity.INFO,
                message=f"Column name contains multiple value indicators: {', '.join(found_chars)}",
                context={
                    "check_type": "multiple_indicators",
                    "found_characters": found_chars,
                    "validation_flags": ["n-multiple"]
                },
                column_name=column_name
            ))
        
        return results


class ColumnNameGeographicRule(ColumnNameValidationRule):
    """
    Detects column names that indicate geographic content.
    Labels columns with geographic indicators as 'n-geo' and specific subtypes.
    """
    
    def __init__(self):
        super().__init__(
            rule_id="column_name_geographic",
            description="Detects column names with geographic indicators"
        )
        
        # Geographic indicators and their corresponding flags
        self.geo_indicators = {
            # General geographic terms
            'localitati': 'n-geo-localitati',
            'localitate': 'n-geo-localitati',
            'judete': 'n-geo-judete',
            'judet': 'n-geo-judete',
            'judetul': 'n-geo-judete',
            
            # Regions
            'regiuni': 'n-geo-regiuni',
            'regiune': 'n-geo-regiuni',
            'regiunea': 'n-geo-regiuni',
            'regiuni de dezvoltare': 'n-geo-regiuni-dezvoltare',
            'regiune de dezvoltare': 'n-geo-regiuni-dezvoltare',
            'regiunea de dezvoltare': 'n-geo-regiuni-dezvoltare',
            
            # Macroregions
            'macroregiuni': 'n-geo-macroregiuni',
            'macroregiune': 'n-geo-macroregiuni',
            'macroregiunea': 'n-geo-macroregiuni',
        }
    
    def validate_column_name(self, column_name: str, index: int, **context) -> List[ValidationResult]:
        results = []
        
        col_lower = column_name.lower().strip()
        detected_flags = []
        
        # Check for geographic indicators
        for indicator, flag in self.geo_indicators.items():
            if indicator in col_lower:
                detected_flags.append(flag)
        
        if detected_flags:
            # Always add the generic 'n-geo' flag
            validation_flags = ['n-geo'] + list(set(detected_flags))
            
            results.append(ValidationResult(
                rule_id=self.rule_id,
                severity=ValidationSeverity.INFO,
                message=f"Geographic column detected: {', '.join(detected_flags)}",
                context={
                    "check_type": "geographic_column",
                    "detected_indicators": detected_flags,
                    "validation_flags": validation_flags
                },
                column_name=column_name
            ))
        
        return results


class ColumnNameTemporalRule(ColumnNameValidationRule):
    """
    Detects column names that indicate temporal content.
    Labels columns with temporal indicators as 'n-time' and specific subtypes.
    """
    
    def __init__(self):
        super().__init__(
            rule_id="column_name_temporal",
            description="Detects column names with temporal indicators"
        )
        
        # Temporal indicators and their corresponding flags
        self.temporal_indicators = {
            # General time terms
            'perioade': 'n-time-perioade',
            'perioada': 'n-time-perioade',
            
            # Years
            'ani': 'n-time-ani',
            'an': 'n-time-ani',
            'anul': 'n-time-ani',
            'anual': 'n-time-ani',
            
            # Months
            'luni': 'n-time-luni',
            'luna': 'n-time-luni',
            'lunar': 'n-time-luni',
            
            # Quarters
            'trimestre': 'n-time-trimestre',
            'trimestru': 'n-time-trimestre',
            'trimestrul': 'n-time-trimestre',
            'trimestrial': 'n-time-trimestre',
            
            # Semesters
            'semestre': 'n-time-semestre',
            'semestru': 'n-time-semestre',
            'semestrul': 'n-time-semestre',
        }
    
    def validate_column_name(self, column_name: str, index: int, **context) -> List[ValidationResult]:
        results = []
        
        col_lower = column_name.lower().strip()
        detected_flags = []
        
        # Check for temporal indicators
        for indicator, flag in self.temporal_indicators.items():
            # Use word boundaries to avoid false matches like "Persoane" containing "an"
            import re
            if re.search(r'\b' + re.escape(indicator) + r'\b', col_lower):
                detected_flags.append(flag)
        
        if detected_flags:
            # Always add the generic 'n-time' flag
            validation_flags = ['n-time'] + list(set(detected_flags))
            
            results.append(ValidationResult(
                rule_id=self.rule_id,
                severity=ValidationSeverity.INFO,
                message=f"Temporal column detected: {', '.join(detected_flags)}",
                context={
                    "check_type": "temporal_column",
                    "detected_indicators": detected_flags,
                    "validation_flags": validation_flags
                },
                column_name=column_name
            ))
        
        return results


class ColumnDataTemporalRule(ColumnDataValidationRule):
    """
    Detects temporal data content in columns.
    Labels columns with temporal data as 'd-time' and specific subtypes.
    """
    
    def __init__(self):
        super().__init__(
            rule_id="column_data_temporal",
            description="Detects temporal data patterns in column content"
        )
    
    def validate_column_data(
        self, 
        column_name: str, 
        column_data: pd.Series, 
        index: int, 
        **context
    ) -> List[ValidationResult]:
        results = []
        
        # Only process string/object columns
        if column_data.dtype not in ['object'] and not pd.api.types.is_string_dtype(column_data):
            return results
        
        non_null_data = column_data.dropna().astype(str)
        if non_null_data.empty:
            return results
        
        # Sample for pattern detection (first 20 values)
        sample_data = non_null_data.head(20)
        total_sample = len(sample_data)
        
        if total_sample < 3:
            return results
        
        detected_flags = []
        pattern_counts = {}
        
        # Check for various temporal patterns
        import re
        
        # Year patterns: "Anul 2020", "2020"
        year_pattern1 = sample_data.str.contains(r'\bAnul\s+\d{4}\b', case=False, na=False)
        year_pattern2 = sample_data.str.match(r'^\d{4}$', na=False)
        year_count = year_pattern1.sum() + year_pattern2.sum()
        if year_count > 0:
            pattern_counts['d-time-ani'] = year_count
        
        # Month patterns: "Luna ianuarie 2020", "Ianuarie 2020"  
        month_pattern = sample_data.str.contains(r'\b(?:luna|ianuarie|februarie|martie|aprilie|mai|iunie|iulie|august|septembrie|octombrie|noiembrie|decembrie)\b', case=False, na=False)
        month_count = month_pattern.sum()
        if month_count > 0:
            pattern_counts['d-time-luni'] = month_count
        
        # Quarter patterns: "Trimestrul I 2020", "T1 2020"
        quarter_pattern = sample_data.str.contains(r'\b(?:trimestrul|trimestru)\s+(?:I|II|III|IV|1|2|3|4)\b', case=False, na=False)
        quarter_count = quarter_pattern.sum()
        if quarter_count > 0:
            pattern_counts['d-time-trimestre'] = quarter_count
        
        # General period patterns
        period_pattern = sample_data.str.contains(r'\b(?:perioada)\b', case=False, na=False)
        period_count = period_pattern.sum()
        if period_count > 0:
            pattern_counts['d-time-perioade'] = period_count
        
        # If we found temporal patterns, add them to detected flags
        if pattern_counts:
            detected_flags = ['d-time'] + list(pattern_counts.keys())
            
            # Calculate coverage percentages
            total_coverage = sum(pattern_counts.values()) / total_sample
            
            results.append(ValidationResult(
                rule_id=self.rule_id,
                severity=ValidationSeverity.INFO,
                message=f"Temporal data detected: {', '.join(pattern_counts.keys())}",
                context={
                    "check_type": "temporal_data",
                    "validation_flags": detected_flags,
                    "pattern_counts": pattern_counts,
                    "coverage": round(total_coverage, 3),
                    "sample_size": total_sample
                },
                column_name=column_name
            ))
        
        return results


class ColumnDataGenderRule(ColumnDataValidationRule):
    """
    Detects gender data content in columns.
    Labels columns with gender data as 'd-gender' and checks for exclusivity.
    """
    
    def __init__(self):
        super().__init__(
            rule_id="column_data_gender",
            description="Detects gender data patterns in column content"
        )
        
        # Gender indicators (lowercase for comparison)
        self.male_indicators = {'masculin', 'm', 'barbati'}
        self.female_indicators = {'feminin', 'f', 'femei'}
        
    def validate_column_data(
        self, 
        column_name: str, 
        column_data: pd.Series, 
        index: int, 
        **context
    ) -> List[ValidationResult]:
        results = []
        
        # Only process string/object columns
        if column_data.dtype not in ['object'] and not pd.api.types.is_string_dtype(column_data):
            return results
        
        non_null_data = column_data.dropna().astype(str)
        if non_null_data.empty:
            return results
        
        # Convert to lowercase for comparison
        lower_data = non_null_data.str.lower().str.strip()
        unique_values = set(lower_data.unique())
        
        if len(unique_values) < 2:
            return results  # Need at least 2 values to detect gender
        
        # Check for gender indicators
        male_found = bool(unique_values & self.male_indicators)
        female_found = bool(unique_values & self.female_indicators)
        
        if male_found or female_found:
            detected_flags = ['d-gender']
            gender_info = {}
            
            # Check what gender values were found
            found_male_values = unique_values & self.male_indicators
            found_female_values = unique_values & self.female_indicators
            
            if found_male_values:
                gender_info['male_values'] = list(found_male_values)
            if found_female_values:
                gender_info['female_values'] = list(found_female_values)
            
            # Check if it's gender-exclusive (only male/female values, no others)
            gender_values = self.male_indicators | self.female_indicators
            non_gender_values = unique_values - gender_values - {'total'}  # Exclude 'total'
            
            if not non_gender_values:
                detected_flags.append('d-gender-exclusive')
                gender_info['is_exclusive'] = True
            else:
                gender_info['is_exclusive'] = False
                gender_info['other_values'] = list(non_gender_values)
            
            # Calculate coverage
            gender_count = sum(1 for val in lower_data if val in gender_values)
            coverage = gender_count / len(lower_data)
            
            results.append(ValidationResult(
                rule_id=self.rule_id,
                severity=ValidationSeverity.INFO,
                message=f"Gender data detected ({'exclusive' if gender_info.get('is_exclusive') else 'mixed'})",
                context={
                    "check_type": "gender_data",
                    "validation_flags": detected_flags,
                    "gender_info": gender_info,
                    "coverage": round(coverage, 3),
                    "total_values": len(lower_data),
                    "unique_values": len(unique_values)
                },
                column_name=column_name
            ))
        
        return results


class ColumnDataGeographicRule(ColumnDataValidationRule):
    """
    Detects geographic data content in columns.
    Labels columns with geographic data as 'd-geo' and specific subtypes.
    """
    
    def __init__(self):
        super().__init__(
            rule_id="column_data_geographic",
            description="Detects geographic data patterns in column content"
        )
        
        # Romanian counties (județe) - lowercase for comparison
        self.counties = {
            'alba', 'arad', 'argeș', 'bacău', 'bihor', 'bistrița-năsăud',
            'botoșani', 'brașov', 'brăila', 'buzău', 'caraș-severin',
            'călărași', 'cluj', 'constanța', 'covasna', 'dâmbovița',
            'dolj', 'galați', 'giurgiu', 'gorj', 'harghita', 'hunedoara',
            'ialomița', 'iași', 'ilfov', 'maramureș', 'mehedinți',
            'mureș', 'neamț', 'olt', 'prahova', 'satu mare', 'sălaj',
            'sibiu', 'suceava', 'teleorman', 'timiș', 'tulcea',
            'vaslui', 'vâlcea', 'vrancea', 'bucurești'
        }
        
        # Common Romanian localities
        self.localities = {
            'tuzla', 'aiud', 'deva', 'alba iulia', 'arad', 'pitești', 'bacău',
            'oradea', 'bistrița', 'botoșani', 'brașov', 'brăila', 'buzău',
            'reșița', 'călărași', 'cluj-napoca', 'constanța', 'sfântu gheorghe',
            'târgoviște', 'craiova', 'galați', 'giurgiu', 'târgu jiu',
            'miercurea ciuc', 'deva', 'slobozia', 'iași', 'bucurești',
            'baia mare', 'drobeta-turnu severin', 'târgu mureș', 'piatra neamț',
            'slatina', 'ploiești', 'satu mare', 'zalău', 'sibiu', 'suceava',
            'alexandria', 'timișoara', 'tulcea', 'vaslui', 'râmnicu vâlcea',
            'focșani'
        }
        
        # Region patterns
        self.region_patterns = [
            r'\bregiunea\s+[\w\s]+\b',
            r'\bmacroregiunea\s+[\w\s]+\b'
        ]
        
    def validate_column_data(
        self, 
        column_name: str, 
        column_data: pd.Series, 
        index: int, 
        **context
    ) -> List[ValidationResult]:
        results = []
        
        # Only process string/object columns
        if column_data.dtype not in ['object'] and not pd.api.types.is_string_dtype(column_data):
            return results
        
        non_null_data = column_data.dropna().astype(str)
        if non_null_data.empty:
            return results
        
        # Normalize data for comparison
        normalized_data = non_null_data.str.lower().str.strip()
        unique_values = set(normalized_data.unique())
        
        detected_flags = []
        geo_info = {}
        
        # Check for counties
        found_counties = unique_values & self.counties
        if found_counties:
            detected_flags.append('d-geo-judete')
            geo_info['counties'] = list(found_counties)
            county_coverage = len(found_counties) / len(self.counties)
            geo_info['county_coverage'] = round(county_coverage, 3)
        
        # Check for localities
        found_localities = unique_values & self.localities
        if found_localities:
            detected_flags.append('d-geo-localitati')
            geo_info['localities'] = list(found_localities)
            locality_coverage = len(found_localities) / len(self.localities)
            geo_info['locality_coverage'] = round(locality_coverage, 3)
        
        # Check for region patterns
        region_matches = []
        macroregion_matches = []
        
        for value in normalized_data:
            for pattern in self.region_patterns:
                if re.search(pattern, value):
                    if 'regiunea' in value and 'regiunea' not in [m.split()[0] for m in region_matches]:
                        region_matches.append(value)
                    elif 'macroregiunea' in value and 'macroregiunea' not in [m.split()[0] for m in macroregion_matches]:
                        macroregion_matches.append(value)
        
        if region_matches:
            detected_flags.append('d-geo-regiune')
            geo_info['regions'] = list(set(region_matches))
        
        if macroregion_matches:
            detected_flags.append('d-geo-macroregiune')
            geo_info['macroregions'] = list(set(macroregion_matches))
        
        # If any geographic data found, add general flag
        if detected_flags:
            detected_flags.insert(0, 'd-geo')
            
            # Calculate total geographic coverage
            geo_values = found_counties | found_localities
            
            # Add region values if found
            for value in normalized_data:
                for pattern in self.region_patterns:
                    if re.search(pattern, value):
                        geo_values.add(value)
            
            geo_coverage = len(geo_values) / len(unique_values) if unique_values else 0
            
            results.append(ValidationResult(
                rule_id=self.rule_id,
                severity=ValidationSeverity.INFO,
                message=f"Geographic data detected: {', '.join(detected_flags[1:])}",
                context={
                    "check_type": "geographic_data",
                    "validation_flags": detected_flags,
                    "geo_info": geo_info,
                    "coverage": round(geo_coverage, 3),
                    "total_values": len(normalized_data),
                    "unique_values": len(unique_values)
                },
                column_name=column_name
            ))
        
        return results


class ColumnDataAgeGroupRule(ColumnDataValidationRule):
    """
    Detects age group and age data content in columns.
    Labels columns with age data as 'd-grupe-varsta' or 'd-varste'.
    """
    
    def __init__(self):
        super().__init__(
            rule_id="column_data_age",
            description="Detects age group and age data patterns in column content"
        )
        
        # Age group patterns (ranges like "18-24 ani")
        self.age_group_patterns = [
            r'\b\d{1,2}-\d{1,2}\s+ani\b',  # 18-24 ani
            r'\b\d{1,2}\s*-\s*\d{1,2}\s+ani\b',  # 18 - 24 ani
            r'\b\d{1,2}-\d{1,2}\s+ani\b',  # Similar patterns
        ]
        
        # Individual age patterns (like "9 ani")
        self.age_patterns = [
            r'\b\d{1,3}\s+ani?\b',  # 9 ani, 25 ani
            r'\b\d{1,3}\s+an\b',   # 1 an
        ]
        
        # Age-related keywords
        self.age_keywords = {
            'varsta', 'varste', 'ani', 'grupe', 'grupa',
            'varsta', 'vârstă', 'vârste'
        }
        
    def validate_column_data(
        self, 
        column_name: str, 
        column_data: pd.Series, 
        index: int, 
        **context
    ) -> List[ValidationResult]:
        results = []
        
        # Only process string/object columns
        if column_data.dtype not in ['object'] and not pd.api.types.is_string_dtype(column_data):
            return results
        
        non_null_data = column_data.dropna().astype(str)
        if non_null_data.empty:
            return results
        
        # Normalize data for comparison
        normalized_data = non_null_data.str.lower().str.strip()
        unique_values = set(normalized_data.unique())
        
        detected_flags = []
        age_info = {}
        
        # Check for age group patterns
        age_group_matches = []
        for pattern in self.age_group_patterns:
            for value in normalized_data:
                matches = re.findall(pattern, value)
                age_group_matches.extend(matches)
        
        if age_group_matches:
            detected_flags.append('d-grupe-varsta')
            age_info['age_groups'] = list(set(age_group_matches))
            age_info['age_group_count'] = len(set(age_group_matches))
        
        # Check for individual age patterns
        age_matches = []
        for pattern in self.age_patterns:
            for value in normalized_data:
                matches = re.findall(pattern, value)
                age_matches.extend(matches)
        
        if age_matches:
            detected_flags.append('d-varste')
            age_info['ages'] = list(set(age_matches))
            age_info['age_count'] = len(set(age_matches))
        
        # Check for age-related keywords in column name or data
        col_lower = column_name.lower()
        has_age_keywords = any(keyword in col_lower for keyword in self.age_keywords)
        
        # If we found age patterns or age keywords, report it
        if detected_flags or has_age_keywords:
            if not detected_flags:
                # If no patterns but has keywords, mark as potential age data
                detected_flags.append('d-varste-potential')
                age_info['reason'] = 'Column name suggests age data'
            
            # Calculate coverage
            age_pattern_count = 0
            for value in normalized_data:
                for pattern in self.age_group_patterns + self.age_patterns:
                    if re.search(pattern, value):
                        age_pattern_count += 1
                        break
            
            coverage = age_pattern_count / len(normalized_data) if normalized_data.size > 0 else 0
            
            results.append(ValidationResult(
                rule_id=self.rule_id,
                severity=ValidationSeverity.INFO,
                message=f"Age data detected: {', '.join(detected_flags)}",
                context={
                    "check_type": "age_data",
                    "validation_flags": detected_flags,
                    "age_info": age_info,
                    "coverage": round(coverage, 3),
                    "total_values": len(normalized_data),
                    "unique_values": len(unique_values),
                    "has_age_keywords": has_age_keywords
                },
                column_name=column_name
            ))
        
        return results


class ColumnDataResidenceRule(ColumnDataValidationRule):
    """
    Detects rural/urban residence data content in columns.
    Labels columns with residence data as 'd-mediu-geo' and checks for exclusivity.
    """
    
    def __init__(self):
        super().__init__(
            rule_id="column_data_residence",
            description="Detects rural/urban residence data patterns in column content"
        )
        
        # Rural/urban indicators (lowercase for comparison)
        self.rural_indicators = {'rural', 'sat', 'sate', 'comuna', 'comune'}
        self.urban_indicators = {'urban', 'oras', 'orase', 'municipiu', 'municipii', 'oras'}
        
    def validate_column_data(
        self, 
        column_name: str, 
        column_data: pd.Series, 
        index: int, 
        **context
    ) -> List[ValidationResult]:
        results = []
        
        # Only process string/object columns
        if column_data.dtype not in ['object'] and not pd.api.types.is_string_dtype(column_data):
            return results
        
        non_null_data = column_data.dropna().astype(str)
        if non_null_data.empty:
            return results
        
        # Convert to lowercase for comparison
        lower_data = non_null_data.str.lower().str.strip()
        unique_values = set(lower_data.unique())
        
        if len(unique_values) < 1:
            return results
        
        # Check for rural/urban indicators
        rural_found = bool(unique_values & self.rural_indicators)
        urban_found = bool(unique_values & self.urban_indicators)
        
        if rural_found or urban_found:
            detected_flags = ['d-mediu-geo']
            residence_info = {}
            
            # Check what residence values were found
            found_rural_values = unique_values & self.rural_indicators
            found_urban_values = unique_values & self.urban_indicators
            
            if found_rural_values:
                residence_info['rural_values'] = list(found_rural_values)
            if found_urban_values:
                residence_info['urban_values'] = list(found_urban_values)
            
            # Check if it's residence-exclusive (only rural/urban values, no others)
            residence_values = self.rural_indicators | self.urban_indicators
            non_residence_values = unique_values - residence_values - {'total'}  # Exclude 'total'
            
            if not non_residence_values:
                detected_flags.append('d-mediu-geo-exclusive')
                residence_info['is_exclusive'] = True
            else:
                residence_info['is_exclusive'] = False
                residence_info['other_values'] = list(non_residence_values)
            
            # Calculate coverage
            residence_count = sum(1 for val in lower_data if val in residence_values)
            coverage = residence_count / len(lower_data)
            
            results.append(ValidationResult(
                rule_id=self.rule_id,
                severity=ValidationSeverity.INFO,
                message=f"Residence data detected ({'exclusive' if residence_info.get('is_exclusive') else 'mixed'})",
                context={
                    "check_type": "residence_data",
                    "validation_flags": detected_flags,
                    "residence_info": residence_info,
                    "coverage": round(coverage, 3),
                    "total_values": len(lower_data),
                    "unique_values": len(unique_values)
                },
                column_name=column_name
            ))
        
        return results


class ColumnDataTotalRule(ColumnDataValidationRule):
    """
    Detects 'total' values and their variants in columns.
    Labels columns with total data as 'd-total' and specific subtypes.
    """
    
    def __init__(self):
        super().__init__(
            rule_id="column_data_total",
            description="Detects total values and their variants in column content"
        )
        
        # Total indicators (lowercase for comparison)
        self.total_indicators = {'total', 'totale', 'total general', 'general'}
        
        # Pattern for "total {string}" variants
        self.total_pattern = r'\btotal\s+[\w\s]+\b'
        
    def validate_column_data(
        self, 
        column_name: str, 
        column_data: pd.Series, 
        index: int, 
        **context
    ) -> List[ValidationResult]:
        results = []
        
        # Only process string/object columns
        if column_data.dtype not in ['object'] and not pd.api.types.is_string_dtype(column_data):
            return results
        
        non_null_data = column_data.dropna().astype(str)
        if non_null_data.empty:
            return results
        
        # Convert to lowercase for comparison
        lower_data = non_null_data.str.lower().str.strip()
        unique_values = set(lower_data.unique())
        
        detected_flags = []
        total_info = {}
        
        # Check for basic total indicators
        found_totals = unique_values & self.total_indicators
        if found_totals:
            detected_flags.append('d-total')
            total_info['basic_totals'] = list(found_totals)
        
        # Check for "total {string}" patterns
        total_variants = []
        for value in unique_values:
            if re.search(self.total_pattern, value):
                total_variants.append(value)
                # Extract the specific variant
                match = re.search(r'total\s+([\w\s]+)', value)
                if match:
                    variant_name = match.group(1).strip()
                    flag_name = f'd-total-{variant_name.replace(" ", "-")}'
                    if flag_name not in detected_flags:
                        detected_flags.append(flag_name)
        
        if total_variants:
            if 'd-total' not in detected_flags:
                detected_flags.insert(0, 'd-total')
            total_info['total_variants'] = total_variants
        
        # If any totals found, create result
        if detected_flags:
            # Calculate coverage
            total_count = 0
            for value in lower_data:
                if value in self.total_indicators or re.search(self.total_pattern, value):
                    total_count += 1
            
            coverage = total_count / len(lower_data) if lower_data.size > 0 else 0
            
            results.append(ValidationResult(
                rule_id=self.rule_id,
                severity=ValidationSeverity.INFO,
                message=f"Total values detected: {', '.join(detected_flags)}",
                context={
                    "check_type": "total_data",
                    "validation_flags": detected_flags,
                    "total_info": total_info,
                    "coverage": round(coverage, 3),
                    "total_values": len(lower_data),
                    "unique_values": len(unique_values)
                },
                column_name=column_name
            ))
        
        return results


class ColumnDataPrefixSuffixRule(ColumnDataValidationRule):
    """
    Detects prefix/suffix patterns in column data.
    Labels columns with consistent prefix/suffix patterns as 'd-prefix' or 'd-suffix'.
    """
    
    def __init__(self):
        super().__init__(
            rule_id="column_data_prefix_suffix",
            description="Detects prefix/suffix patterns in column content"
        )
        
        # Common Romanian prefixes and suffixes in statistical data
        self.common_prefixes = {
            'anul', 'luna', 'trimestrul', 'semestrul', 'perioada',
            'regiunea', 'macroregiunea', 'judetul', 'municipiul',
            'grupa', 'grupe', 'categoria'
        }
        
        self.common_suffixes = {
            'ani', 'luni', 'zile', 'persoane', 'locuitori',
            'procente', '%', 'euro', 'lei'
        }
        
    def validate_column_data(
        self, 
        column_name: str, 
        column_data: pd.Series, 
        index: int, 
        **context
    ) -> List[ValidationResult]:
        results = []
        
        # Only process string/object columns
        if column_data.dtype not in ['object'] and not pd.api.types.is_string_dtype(column_data):
            return results
        
        non_null_data = column_data.dropna().astype(str)
        if non_null_data.empty:
            return results
        
        # Normalize data for comparison
        normalized_data = non_null_data.str.lower().str.strip()
        unique_values = list(normalized_data.unique())
        
        if len(unique_values) < 2:
            return results  # Need at least 2 values to detect patterns
        
        detected_flags = []
        pattern_info = {}
        
        # Check for common prefix patterns
        prefix_patterns = {}
        for value in unique_values:
            words = value.split()
            if len(words) >= 2:
                first_word = words[0]
                if first_word in self.common_prefixes:
                    if first_word not in prefix_patterns:
                        prefix_patterns[first_word] = []
                    prefix_patterns[first_word].append(value)
        
        # Check for common suffix patterns
        suffix_patterns = {}
        for value in unique_values:
            words = value.split()
            if len(words) >= 2:
                last_word = words[-1]
                if last_word in self.common_suffixes:
                    if last_word not in suffix_patterns:
                        suffix_patterns[last_word] = []
                    suffix_patterns[last_word].append(value)
        
        # Check for custom prefix patterns (same starting word in multiple values)
        word_counts = {}
        for value in unique_values:
            words = value.split()
            if len(words) >= 2:
                first_word = words[0]
                word_counts[first_word] = word_counts.get(first_word, 0) + 1
        
        custom_prefixes = {word: count for word, count in word_counts.items() 
                          if count >= max(2, len(unique_values) * 0.3)}  # At least 30% or 2 values
        
        # Check for custom suffix patterns
        suffix_counts = {}
        for value in unique_values:
            words = value.split()
            if len(words) >= 2:
                last_word = words[-1]
                suffix_counts[last_word] = suffix_counts.get(last_word, 0) + 1
        
        custom_suffixes = {word: count for word, count in suffix_counts.items() 
                          if count >= max(2, len(unique_values) * 0.3)}
        
        # Report findings
        if prefix_patterns:
            detected_flags.append('d-prefix')
            pattern_info['common_prefixes'] = prefix_patterns
        
        if suffix_patterns:
            detected_flags.append('d-suffix')
            pattern_info['common_suffixes'] = suffix_patterns
        
        if custom_prefixes:
            detected_flags.append('d-prefix-pattern')
            pattern_info['custom_prefixes'] = custom_prefixes
        
        if custom_suffixes:
            detected_flags.append('d-suffix-pattern')
            pattern_info['custom_suffixes'] = custom_suffixes
        
        # Calculate coverage if patterns found
        if detected_flags:
            pattern_count = 0
            for value in normalized_data:
                words = value.split()
                if len(words) >= 2:
                    first_word, last_word = words[0], words[-1]
                    if (first_word in self.common_prefixes or 
                        last_word in self.common_suffixes or
                        first_word in custom_prefixes or
                        last_word in custom_suffixes):
                        pattern_count += 1
            
            coverage = pattern_count / len(normalized_data) if normalized_data.size > 0 else 0
            
            results.append(ValidationResult(
                rule_id=self.rule_id,
                severity=ValidationSeverity.INFO,
                message=f"Prefix/suffix patterns detected: {', '.join(detected_flags)}",
                context={
                    "check_type": "prefix_suffix_patterns",
                    "validation_flags": detected_flags,
                    "pattern_info": pattern_info,
                    "coverage": round(coverage, 3),
                    "total_values": len(normalized_data),
                    "unique_values": len(unique_values)
                },
                column_name=column_name
            ))
        
        return results


class ColumnConsistencyRule(ColumnNameValidationRule, ColumnDataValidationRule):
    """
    Checks for consistency between column names and their data content.
    Flags columns where the name suggests one type but data indicates another.
    """
    
    def __init__(self):
        super().__init__(
            rule_id="column_consistency",
            description="Detects inconsistencies between column names and data content"
        )
        
        # Expected patterns based on column name indicators
        self.name_data_expectations = {
            'temporal': ['d-time', 'd-time-ani', 'd-time-luni', 'd-time-trimestre'],
            'geographic': ['d-geo', 'd-geo-judete', 'd-geo-localitati', 'd-geo-regiune', 'd-geo-macroregiune'],
            'gender': ['d-gender', 'd-gender-exclusive'],
            'age': ['d-grupe-varsta', 'd-varste'],
            'residence': ['d-mediu-geo', 'd-mediu-geo-exclusive']
        }
        
    def validate_column_name(self, column_name: str, index: int, **context) -> List[ValidationResult]:
        # This rule needs both name and data context, so return empty here
        return []
    
    def validate_column_data(
        self, 
        column_name: str, 
        column_data: pd.Series, 
        index: int, 
        **context
    ) -> List[ValidationResult]:
        # This rule needs both name and data context, so return empty here  
        return []
    
    def validate_consistency(
        self, 
        column_name: str, 
        column_data: pd.Series, 
        name_flags: List[str], 
        data_flags: List[str],
        index: int
    ) -> List[ValidationResult]:
        """
        Check consistency between column name flags and data flags.
        """
        results = []
        inconsistencies = []
        
        # Check if name suggests temporal but data doesn't match
        name_temporal = any(flag.startswith('n-time') for flag in name_flags)
        data_temporal = any(flag.startswith('d-time') for flag in data_flags)
        
        if name_temporal and not data_temporal:
            inconsistencies.append("Column name suggests temporal data but content doesn't match")
        elif not name_temporal and data_temporal:
            inconsistencies.append("Column data is temporal but name doesn't suggest it")
        
        # Check if name suggests geographic but data doesn't match
        name_geo = any(flag.startswith('n-geo') for flag in name_flags)
        data_geo = any(flag.startswith('d-geo') for flag in data_flags)
        
        if name_geo and not data_geo:
            inconsistencies.append("Column name suggests geographic data but content doesn't match")
        elif not name_geo and data_geo:
            inconsistencies.append("Column data is geographic but name doesn't suggest it")
        
        # Check for multiple indicators in name vs actual content
        name_multiple = any(flag == 'n-multiple' for flag in name_flags)
        data_mixed_patterns = len([f for f in data_flags if f.startswith('d-')]) > 2
        
        if name_multiple and not data_mixed_patterns:
            inconsistencies.append("Column name suggests multiple indicators but data seems uniform")
        
        # Check for gender consistency  
        name_suggests_gender = 'sexe' in column_name.lower() or 'gen' in column_name.lower()
        data_has_gender = any(flag.startswith('d-gender') for flag in data_flags)
        
        if name_suggests_gender and not data_has_gender:
            inconsistencies.append("Column name suggests gender data but content doesn't match")
        
        # Check for age consistency
        name_suggests_age = any(word in column_name.lower() for word in ['varst', 'ani', 'grupe'])
        data_has_age = any(flag in ['d-grupe-varsta', 'd-varste'] for flag in data_flags)
        
        if name_suggests_age and not data_has_age:
            inconsistencies.append("Column name suggests age data but content doesn't match")
        
        # If inconsistencies found, report them
        if inconsistencies:
            results.append(ValidationResult(
                rule_id=self.rule_id,
                severity=ValidationSeverity.WARNING,
                message=f"Consistency issues detected ({len(inconsistencies)} issues)",
                context={
                    "check_type": "name_data_consistency",
                    "validation_flags": ["inconsistent"],
                    "inconsistencies": inconsistencies,
                    "name_flags": name_flags,
                    "data_flags": data_flags
                },
                column_name=column_name,
                suggested_fix="Review column naming or data content for consistency"
            ))
        
        return results


if __name__ == "__main__":
    # Test the INS validation rules
    import pandas as pd
    from validation_rules import DataValidator
    
    print("🧪 Testing INS Validation Rules")
    
    # Test 1: Good INS structure
    good_data = pd.DataFrame({
        "Ani": ["2020", "2021", "2022"],
        "Regiune": ["Nord", "Sud", "Centru"],
        "UM: Persoane": ["Numar", "Numar", "Numar"],
        "Valoare": [1000, 1100, 1200]
    })
    
    validator = DataValidator()
    validator.add_rule(INSFileStructureRule())
    validator.add_rule(ColumnNameMultipleIndicatorRule())
    validator.add_rule(ColumnNameGeographicRule())
    validator.add_rule(ColumnNameTemporalRule())
    
    results = validator.validate_dataframe_summary(good_data, "good_structure.csv")
    print(f"✅ Good structure - Errors: {results['validation_summary']['error']}, Warnings: {results['validation_summary']['warning']}")
    
    # Test 2: Column names with multiple indicators
    multiple_data = pd.DataFrame({
        "Ani|Perioade": ["2020", "2021", "2022"],
        "Regiune, Judet": ["Nord", "Sud", "Centru"], 
        "Indicatori'Multiple": ["A", "B", "C"],
        "UM: Persoane": ["Numar", "Numar", "Numar"],
        "Valoare": [1000, 1100, 1200]
    })
    
    results = validator.validate_dataframe_summary(multiple_data, "multiple_indicators.csv")
    print(f"\n🔍 Multiple indicators test - Info: {results['validation_summary']['info']}")
    
    for result in results['detailed_results']:
        if result['rule_id'] == 'column_name_multiple_indicator':
            flags = result.get('context', {}).get('validation_flags', [])
            print(f"   Column '{result['column_name']}': {flags}")
    
    # Test 3: Geographic and temporal columns
    geo_time_data = pd.DataFrame({
        "Ani si Perioade": ["2020", "2021", "2022"],
        "Judete si Regiuni": ["Bihor", "Cluj", "Dolj"],
        "Macroregiuni si Localitati": ["Nord", "Sud", "Vest"],
        "Trimestre si Luni": ["T1", "T2", "T3"],
        "UM: Persoane": ["Numar", "Numar", "Numar"],
        "Valoare": [1000, 1100, 1200]
    })
    
    results = validator.validate_dataframe_summary(geo_time_data, "geo_time_test.csv")
    print(f"\n🗺️  Geographic/Temporal test - Info: {results['validation_summary']['info']}")
    
    for result in results['detailed_results']:
        if result['rule_id'] in ['column_name_geographic', 'column_name_temporal']:
            flags = result.get('context', {}).get('validation_flags', [])
            print(f"   {result['rule_id']}: '{result['column_name']}' -> {flags}")
    
    # Test 4: Bad structure (from before)
    bad_data = pd.DataFrame({
        "Regiune": ["Nord", "Sud", "Centru"],
        "SomeOtherColumn": ["A", "B", "C"],
        "NotValoare": ["X", "Y", "Z"]
    })
    
    results = validator.validate_dataframe_summary(bad_data, "bad_structure.csv")
    print(f"\n⚠️  Bad structure - Errors: {results['validation_summary']['error']}, Warnings: {results['validation_summary']['warning']}")
    
    for result in results['detailed_results']:
        if result['rule_id'] == 'ins_file_structure':
            print(f"   Structure issues: {result.get('context', {}).get('structure_flags', [])}")
