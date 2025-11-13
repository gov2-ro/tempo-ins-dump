"""
File Consistency Checker for Romanian INS Data Pipeline

This script validates data consistency across the Romanian National Institute 
of Statistics (INS) data processing pipeline by checking file alignment between 
three key sources:

1. Matrix index (`data/1-indexes/ro/matrices.csv`) - Contains all available matrix codes
2. Metadata files (`data/2-metas/ro/`) - JSON files with matrix definitions  
3. Dataset files (`data/4-datasets/ro/`) - CSV files with actual data

The script identifies:
- Missing metadata files (codes in index but no JSON file)
- Missing dataset files (codes in index but no CSV file)
- Orphaned metadata files (JSON files without corresponding index entry)
- Orphaned dataset files (CSV files without corresponding index entry)
- Summary statistics and completion percentages

This helps ensure data pipeline integrity and identifies gaps in the 
data collection/processing workflow.

usage: check-files.py [-h] [--index-file INDEX_FILE] [--meta-dir META_DIR] [--dataset-dir DATASET_DIR] [--output OUTPUT] [--csv-output CSV_OUTPUT] [--summary-csv SUMMARY_CSV] [--output-dir OUTPUT_DIR] [--lang LANG]

Check file consistency across INS data pipeline (index, metadata, datasets)

options:
  -h, --help            show this help message and exit
  --index-file INDEX_FILE
                        Path to the matrices index CSV file
  --meta-dir META_DIR   Directory containing metadata JSON files
  --dataset-dir DATASET_DIR
                        Directory containing dataset CSV files
  --output OUTPUT       Save detailed text report to specified file
  --csv-output CSV_OUTPUT
                        Save detailed differences to CSV file (matrix_code, category, description, priority)
  --summary-csv SUMMARY_CSV
                        Save summary statistics to CSV file
  --output-dir OUTPUT_DIR
                        Directory to save all output files (generates default filenames)
  --lang LANG           Language code (ro/en) - updates default paths

"""

import os
import pathlib
import argparse
import csv
from typing import Set, Dict, List, Tuple

# Try to import pandas, fall back to csv module if not available
try:
    import pandas as pd
    HAS_PANDAS = True
except ImportError:
    print("Warning: pandas not available, using basic CSV reading")
    HAS_PANDAS = False

def load_matrix_codes_from_index(index_file: str) -> Set[str]:
    """
    Load matrix codes from the index CSV file.
    
    Args:
        index_file: Path to the matrices index CSV file
        
    Returns:
        Set of matrix codes from the index
    """
    try:
        if HAS_PANDAS:
            # Use pandas if available
            df = pd.read_csv(index_file)
            if 'code' not in df.columns:
                raise ValueError(f"Index file {index_file} does not contain 'code' column")
            
            codes = set(df['code'].dropna().astype(str))
        else:
            # Fall back to basic CSV reading
            codes = set()
            with open(index_file, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                if 'code' not in reader.fieldnames:
                    raise ValueError(f"Index file {index_file} does not contain 'code' column")
                
                for row in reader:
                    if row['code'] and row['code'].strip():
                        codes.add(row['code'].strip())
        
        print(f"Loaded {len(codes)} matrix codes from index")
        return codes
        
    except Exception as e:
        print(f"Error reading index file {index_file}: {e}")
        raise

def scan_directory_files(directory: str, extension: str) -> Set[str]:
    """
    Scan a directory for files with specified extension and extract codes.
    
    Args:
        directory: Directory path to scan
        extension: File extension to look for (e.g., '.json', '.csv')
        
    Returns:
        Set of codes extracted from filenames (without extension)
    """
    try:
        path = pathlib.Path(directory)
        if not path.exists():
            print(f"Warning: Directory {directory} does not exist")
            return set()
        
        files = list(path.glob(f'*{extension}'))
        codes = {file.stem for file in files}
        print(f"Found {len(codes)} {extension} files in {directory}")
        return codes
        
    except Exception as e:
        print(f"Error scanning directory {directory}: {e}")
        return set()

def analyze_differences(index_codes: Set[str], meta_codes: Set[str], dataset_codes: Set[str]) -> Dict[str, Set[str]]:
    """
    Analyze differences between the three sets of codes.
    
    Args:
        index_codes: Codes from the index file
        meta_codes: Codes from metadata JSON files  
        dataset_codes: Codes from dataset CSV files
        
    Returns:
        Dictionary with different categories of mismatches
    """
    results = {
        # Missing files (in index but not in directories)
        'missing_meta': index_codes - meta_codes,
        'missing_datasets': index_codes - dataset_codes,
        
        # Orphaned files (in directories but not in index)
        'orphaned_meta': meta_codes - index_codes,
        'orphaned_datasets': dataset_codes - index_codes,
        
        # Files with metadata but no datasets
        'meta_without_dataset': meta_codes - dataset_codes,
        
        # Files with datasets but no metadata  
        'dataset_without_meta': dataset_codes - meta_codes,
        
        # Complete sets (for analysis)
        'complete_pipeline': index_codes & meta_codes & dataset_codes,
        'has_meta': index_codes & meta_codes,
        'has_dataset': index_codes & dataset_codes,
    }
    
    return results

def print_analysis_report(analysis: Dict[str, Set[str]], index_codes: Set[str]) -> None:
    """
    Print a comprehensive analysis report.
    
    Args:
        analysis: Results from analyze_differences
        index_codes: Original set of index codes for percentage calculations
    """
    total_codes = len(index_codes)
    
    print("\n" + "="*80)
    print("FILE CONSISTENCY ANALYSIS REPORT")
    print("="*80)
    
    # Summary statistics
    print(f"\nSUMMARY STATISTICS:")
    print(f"Total matrix codes in index: {total_codes}")
    print(f"Complete pipeline (index + meta + dataset): {len(analysis['complete_pipeline'])} ({len(analysis['complete_pipeline'])/total_codes*100:.1f}%)")
    print(f"Has metadata files: {len(analysis['has_meta'])} ({len(analysis['has_meta'])/total_codes*100:.1f}%)")
    print(f"Has dataset files: {len(analysis['has_dataset'])} ({len(analysis['has_dataset'])/total_codes*100:.1f}%)")
    
    # Missing files (errors - should be addressed)
    print(f"\n🚨 MISSING FILES (Priority: HIGH):")
    print(f"Missing metadata files: {len(analysis['missing_meta'])} codes")
    if analysis['missing_meta']:
        print(f"   First 10: {', '.join(sorted(list(analysis['missing_meta']))[:10])}")
        if len(analysis['missing_meta']) > 10:
            print(f"   ... and {len(analysis['missing_meta'])-10} more")
    
    print(f"Missing dataset files: {len(analysis['missing_datasets'])} codes")
    if analysis['missing_datasets']:
        print(f"   First 10: {', '.join(sorted(list(analysis['missing_datasets']))[:10])}")
        if len(analysis['missing_datasets']) > 10:
            print(f"   ... and {len(analysis['missing_datasets'])-10} more")
    
    # Pipeline inconsistencies  
    print(f"\n⚠️  PIPELINE INCONSISTENCIES (Priority: MEDIUM):")
    print(f"Have metadata but no dataset: {len(analysis['meta_without_dataset'])} codes")
    if analysis['meta_without_dataset']:
        print(f"   Sample: {', '.join(sorted(list(analysis['meta_without_dataset']))[:5])}")
    
    print(f"Have dataset but no metadata: {len(analysis['dataset_without_meta'])} codes") 
    if analysis['dataset_without_meta']:
        print(f"   Sample: {', '.join(sorted(list(analysis['dataset_without_meta']))[:5])}")
    
    # Orphaned files (cleanup candidates)
    print(f"\n🧹 ORPHANED FILES (Priority: LOW - cleanup candidates):")
    print(f"Orphaned metadata files: {len(analysis['orphaned_meta'])} codes")
    if analysis['orphaned_meta']:
        print(f"   Sample: {', '.join(sorted(list(analysis['orphaned_meta']))[:5])}")
        
    print(f"Orphaned dataset files: {len(analysis['orphaned_datasets'])} codes")
    if analysis['orphaned_datasets']:
        print(f"   Sample: {', '.join(sorted(list(analysis['orphaned_datasets']))[:5])}")

def save_detailed_report(analysis: Dict[str, Set[str]], output_file: str) -> None:
    """
    Save detailed lists to a file for further analysis.
    
    Args:
        analysis: Results from analyze_differences
        output_file: Path to output file
    """
    try:
        with open(output_file, 'w') as f:
            f.write("DETAILED FILE CONSISTENCY REPORT\n")
            f.write("="*50 + "\n\n")
            
            for category, codes in analysis.items():
                if not codes:  # Skip empty sets
                    continue
                    
                f.write(f"\n{category.upper().replace('_', ' ')} ({len(codes)} codes):\n")
                f.write("-" * 40 + "\n")
                
                # Sort codes for consistent output
                for code in sorted(codes):
                    f.write(f"{code}\n")
                    
        print(f"\n📝 Detailed report saved to: {output_file}")
        
    except Exception as e:
        print(f"Error saving detailed report: {e}")

def save_csv_report(analysis: Dict[str, Set[str]], output_file: str) -> None:
    """
    Save analysis results to a CSV file for easy inspection and filtering.
    
    Args:
        analysis: Results from analyze_differences
        output_file: Path to output CSV file
    """
    try:
        with open(output_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            
            # Write header
            writer.writerow(['matrix_code', 'category', 'description', 'priority'])
            
            # Define category mappings with descriptions and priorities
            categories = {
                'missing_meta': ('Missing Metadata File', 'HIGH', 'Matrix code exists in index but no corresponding JSON file found'),
                'missing_datasets': ('Missing Dataset File', 'HIGH', 'Matrix code exists in index but no corresponding CSV file found'), 
                'meta_without_dataset': ('Has Metadata, No Dataset', 'MEDIUM', 'JSON file exists but no corresponding CSV dataset'),
                'dataset_without_meta': ('Has Dataset, No Metadata', 'MEDIUM', 'CSV dataset exists but no corresponding JSON metadata'),
                'orphaned_meta': ('Orphaned Metadata File', 'LOW', 'JSON file exists but matrix code not in index'),
                'orphaned_datasets': ('Orphaned Dataset File', 'LOW', 'CSV file exists but matrix code not in index'),
                'complete_pipeline': ('Complete Pipeline', 'INFO', 'Matrix has index entry, metadata, and dataset'),
                'has_meta': ('Has Metadata', 'INFO', 'Matrix has index entry and metadata file'),
                'has_dataset': ('Has Dataset', 'INFO', 'Matrix has index entry and dataset file'),
            }
            
            # Write data rows
            for category, codes in analysis.items():
                if codes and category in categories:
                    desc_short, priority, desc_long = categories[category]
                    for code in sorted(codes):
                        writer.writerow([code, category, desc_short, priority])
        
        print(f"\n📊 CSV report saved to: {output_file}")
        
    except Exception as e:
        print(f"Error saving CSV report: {e}")

def save_summary_csv(analysis: Dict[str, Set[str]], index_codes: Set[str], output_file: str) -> None:
    """
    Save a summary statistics CSV file.
    
    Args:
        analysis: Results from analyze_differences
        index_codes: Original set of index codes for percentage calculations
        output_file: Path to output CSV file
    """
    try:
        total_codes = len(index_codes)
        
        summary_data = [
            ['total_matrix_codes', total_codes, 100.0, 'Total matrix codes in index file'],
            ['complete_pipeline', len(analysis['complete_pipeline']), len(analysis['complete_pipeline'])/total_codes*100, 'Codes with index + metadata + dataset'],
            ['has_metadata', len(analysis['has_meta']), len(analysis['has_meta'])/total_codes*100, 'Codes with index + metadata'],
            ['has_dataset', len(analysis['has_dataset']), len(analysis['has_dataset'])/total_codes*100, 'Codes with index + dataset'],
            ['missing_metadata', len(analysis['missing_meta']), len(analysis['missing_meta'])/total_codes*100, 'Missing metadata files'],
            ['missing_datasets', len(analysis['missing_datasets']), len(analysis['missing_datasets'])/total_codes*100, 'Missing dataset files'],
            ['orphaned_metadata', len(analysis['orphaned_meta']), 0.0, 'Orphaned metadata files (not in index)'],
            ['orphaned_datasets', len(analysis['orphaned_datasets']), 0.0, 'Orphaned dataset files (not in index)'],
            ['meta_no_dataset', len(analysis['meta_without_dataset']), len(analysis['meta_without_dataset'])/total_codes*100, 'Has metadata but no dataset'],
            ['dataset_no_meta', len(analysis['dataset_without_meta']), len(analysis['dataset_without_meta'])/total_codes*100, 'Has dataset but no metadata'],
        ]
        
        with open(output_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['metric', 'count', 'percentage', 'description'])
            writer.writerows(summary_data)
            
        print(f"\n📈 Summary CSV saved to: {output_file}")
        
    except Exception as e:
        print(f"Error saving summary CSV: {e}")

def main():
    """Main function to run the file consistency check."""
    parser = argparse.ArgumentParser(
        description="Check file consistency across INS data pipeline (index, metadata, datasets)"
    )
    parser.add_argument(
        '--index-file', 
        default='data/1-indexes/ro/matrices.csv',
        help='Path to the matrices index CSV file'
    )
    parser.add_argument(
        '--meta-dir',
        default='data/2-metas/ro',
        help='Directory containing metadata JSON files'
    )
    parser.add_argument(
        '--dataset-dir', 
        default='data/4-datasets/ro',
        help='Directory containing dataset CSV files'
    )
    parser.add_argument(
        '--output',
        default='file_consistency_detailed.txt',
        help='Save detailed text report to specified file (default: file_consistency_detailed.txt)'
    )
    parser.add_argument(
        '--csv-output',
        default='file_consistency_differences.csv',
        help='Save detailed differences to CSV file (default: file_consistency_differences.csv)'
    )
    parser.add_argument(
        '--summary-csv',
        default='file_consistency_summary.csv',
        help='Save summary statistics to CSV file (default: file_consistency_summary.csv)'
    )
    parser.add_argument(
        '--output-dir',
        default='data/reports',
        help='Directory to save all output files (default: data/reports/)'
    )
    parser.add_argument(
        '--lang',
        default='ro',
        help='Language code (ro/en) - updates default paths'
    )
    parser.add_argument(
        '--generate-files',
        action='store_true',
        help='Generate output files using default paths (equivalent to --generate-all)'
    )
    parser.add_argument(
        '--generate-all',
        action='store_true', 
        help='Generate all output files (detailed text, CSV differences, summary CSV) in output-dir'
    )
    parser.add_argument(
        '--no-output',
        action='store_true',
        help='Only show console output, do not generate any files'
    )
    
    args = parser.parse_args()
    
    # Update paths if language is specified
    if args.lang != 'ro':
        if args.index_file == 'data/1-indexes/ro/matrices.csv':
            args.index_file = f'data/1-indexes/{args.lang}/matrices.csv'
        if args.meta_dir == 'data/2-metas/ro':
            args.meta_dir = f'data/2-metas/{args.lang}'
        if args.dataset_dir == 'data/4-datasets/ro':
            args.dataset_dir = f'data/4-datasets/{args.lang}'
    
    print(f"Checking file consistency for language: {args.lang}")
    print(f"Index file: {args.index_file}")
    print(f"Metadata directory: {args.meta_dir}")  
    print(f"Dataset directory: {args.dataset_dir}")
    
    try:
        # Load codes from each source
        index_codes = load_matrix_codes_from_index(args.index_file)
        meta_codes = scan_directory_files(args.meta_dir, '.json')
        dataset_codes = scan_directory_files(args.dataset_dir, '.csv')
        
        # Analyze differences
        analysis = analyze_differences(index_codes, meta_codes, dataset_codes)
        
        # Print report
        print_analysis_report(analysis, index_codes)
        
        # Handle output options
        if args.no_output:
            # Skip all file generation
            pass
        elif args.generate_all or args.generate_files:
            # Generate all files in output directory
            os.makedirs(args.output_dir, exist_ok=True)
            base_name = f"file_consistency_{args.lang}"
            
            detailed_report = os.path.join(args.output_dir, f"{base_name}_detailed.txt")
            csv_report = os.path.join(args.output_dir, f"{base_name}_differences.csv") 
            summary_report = os.path.join(args.output_dir, f"{base_name}_summary.csv")
            
            save_detailed_report(analysis, detailed_report)
            save_csv_report(analysis, csv_report)
            save_summary_csv(analysis, index_codes, summary_report)
        else:
            # Check if any custom output paths were specified, otherwise use defaults
            has_custom_paths = any([
                args.output != 'file_consistency_detailed.txt',
                args.csv_output != 'file_consistency_differences.csv', 
                args.summary_csv != 'file_consistency_summary.csv',
                args.output_dir != 'data/reports'
            ])
            
            if has_custom_paths:
                # User specified custom paths, generate individual files
                if args.output != 'file_consistency_detailed.txt':
                    save_detailed_report(analysis, args.output)
                
                if args.csv_output != 'file_consistency_differences.csv':
                    save_csv_report(analysis, args.csv_output)
                    
                if args.summary_csv != 'file_consistency_summary.csv':
                    save_summary_csv(analysis, index_codes, args.summary_csv)
                    
                if args.output_dir != 'data/reports':
                    # Generate all files in custom output directory
                    os.makedirs(args.output_dir, exist_ok=True)
                    base_name = f"file_consistency_{args.lang}"
                    
                    detailed_report = os.path.join(args.output_dir, f"{base_name}_detailed.txt")
                    csv_report = os.path.join(args.output_dir, f"{base_name}_differences.csv") 
                    summary_report = os.path.join(args.output_dir, f"{base_name}_summary.csv")
                    
                    save_detailed_report(analysis, detailed_report)
                    save_csv_report(analysis, csv_report)
                    save_summary_csv(analysis, index_codes, summary_report)
            else:
                # All defaults, generate files in default location for convenience
                os.makedirs(args.output_dir, exist_ok=True)
                
                output_with_lang = f"file_consistency_{args.lang}_detailed.txt"
                csv_with_lang = f"file_consistency_{args.lang}_differences.csv"
                summary_with_lang = f"file_consistency_{args.lang}_summary.csv"
                
                save_detailed_report(analysis, os.path.join(args.output_dir, output_with_lang))
                save_csv_report(analysis, os.path.join(args.output_dir, csv_with_lang))
                save_summary_csv(analysis, index_codes, os.path.join(args.output_dir, summary_with_lang))
        
        # Exit with appropriate code
        missing_files = len(analysis['missing_meta']) + len(analysis['missing_datasets'])
        if missing_files > 0:
            print(f"\n⚠️  Found {missing_files} missing files. Check pipeline integrity.")
            return 1
        else:
            print(f"\n✅ All indexed files have corresponding metadata and datasets.")
            return 0
            
    except Exception as e:
        print(f"Error during analysis: {e}")
        return 1

if __name__ == "__main__":
    exit(main())

