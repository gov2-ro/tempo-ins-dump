#!/usr/bin/env python3
"""
Script to build a searchable index of dimensions and their options from metadata files.
Analyzes all JSON files in the metas directory and creates a database index.
"""

# Configuration
metas_dir = "data-old/2-metas/ro"
db_path = "data/dimension_index.db"
report_path = "data/dimension_analysis_report.md"

import json
import os
import sqlite3
from pathlib import Path
from typing import Dict, List, Set
import sys

def setup_database(db_path: str) -> sqlite3.Connection:
    """Create and setup the SQLite database with required tables."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Create dimensions table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS dimensions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            label TEXT NOT NULL,
            dim_code INTEGER,
            file_id TEXT NOT NULL,
            matrix_name TEXT,
            UNIQUE(label, dim_code, file_id)
        )
    ''')
    
    # Create options table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS options (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            label TEXT NOT NULL,
            nom_item_id INTEGER,
            offset_value INTEGER,
            parent_id INTEGER,
            dimension_id INTEGER,
            file_id TEXT NOT NULL,
            FOREIGN KEY (dimension_id) REFERENCES dimensions (id),
            UNIQUE(label, nom_item_id, dimension_id, file_id)
        )
    ''')
    
    # Create indexes for faster searching
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_dimensions_label ON dimensions(label)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_dimensions_file ON dimensions(file_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_options_label ON options(label)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_options_file ON options(file_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_options_dimension ON options(dimension_id)')
    
    conn.commit()
    return conn

def extract_file_id_from_path(file_path: str) -> str:
    """Extract file ID from file path (e.g., meta-ZDP1321.json -> ZDP1321)."""
    filename = os.path.basename(file_path)
    if filename.startswith('meta-') and filename.endswith('.json'):
        return filename[5:-5]  # Remove 'meta-' prefix and '.json' suffix
    return filename

def process_metadata_file(file_path: str, conn: sqlite3.Connection) -> Dict:
    """Process a single metadata file and extract dimension information."""
    cursor = conn.cursor()
    file_id = extract_file_id_from_path(file_path)
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        matrix_name = data.get('matrixName', '')
        dimensions_map = data.get('dimensionsMap', [])
        
        stats = {
            'file_id': file_id,
            'matrix_name': matrix_name,
            'dimensions_count': len(dimensions_map),
            'total_options': 0,
            'dimensions': []
        }
        
        for dimension in dimensions_map:
            dim_label = dimension.get('label', '')
            dim_code = dimension.get('dimCode')
            options = dimension.get('options', [])
            
            # Insert dimension
            try:
                cursor.execute('''
                    INSERT OR IGNORE INTO dimensions (label, dim_code, file_id, matrix_name)
                    VALUES (?, ?, ?, ?)
                ''', (dim_label, dim_code, file_id, matrix_name))
                
                # Get dimension ID
                cursor.execute('''
                    SELECT id FROM dimensions 
                    WHERE label = ? AND dim_code = ? AND file_id = ?
                ''', (dim_label, dim_code, file_id))
                
                dimension_id = cursor.fetchone()[0]
                
                dim_stats = {
                    'label': dim_label,
                    'dim_code': dim_code,
                    'options_count': len(options),
                    'options': []
                }
                
                # Insert options
                for option in options:
                    opt_label = option.get('label', '')
                    nom_item_id = option.get('nomItemId')
                    offset_value = option.get('offset')
                    parent_id = option.get('parentId')
                    
                    try:
                        cursor.execute('''
                            INSERT OR IGNORE INTO options 
                            (label, nom_item_id, offset_value, parent_id, dimension_id, file_id)
                            VALUES (?, ?, ?, ?, ?, ?)
                        ''', (opt_label, nom_item_id, offset_value, parent_id, dimension_id, file_id))
                        
                        dim_stats['options'].append(opt_label)
                        
                    except sqlite3.Error as e:
                        print(f"Error inserting option '{opt_label}' in file {file_id}: {e}")
                
                stats['dimensions'].append(dim_stats)
                stats['total_options'] += len(options)
                
            except sqlite3.Error as e:
                print(f"Error inserting dimension '{dim_label}' in file {file_id}: {e}")
        
        conn.commit()
        return stats
        
    except json.JSONDecodeError as e:
        print(f"Error parsing JSON in {file_path}: {e}")
        return None
    except FileNotFoundError:
        print(f"File not found: {file_path}")
        return None
    except Exception as e:
        print(f"Unexpected error processing {file_path}: {e}")
        return None

def analyze_directory(metas_dir: str, db_path: str) -> List[Dict]:
    """Analyze all metadata files in the directory."""
    if not os.path.exists(metas_dir):
        print(f"Directory not found: {metas_dir}")
        return []
    
    # Setup database
    conn = setup_database(db_path)
    
    # Clear existing data
    cursor = conn.cursor()
    cursor.execute('DELETE FROM options')
    cursor.execute('DELETE FROM dimensions')
    conn.commit()
    
    all_stats = []
    json_files = [f for f in os.listdir(metas_dir) if f.endswith('.json')]
    
    print(f"Found {len(json_files)} JSON files to process...")
    
    for filename in sorted(json_files):
        file_path = os.path.join(metas_dir, filename)
        print(f"Processing: {filename}")
        
        stats = process_metadata_file(file_path, conn)
        if stats:
            all_stats.append(stats)
            print(f"  - {stats['dimensions_count']} dimensions, {stats['total_options']} total options")
        else:
            print(f"  - Failed to process")
    
    conn.close()
    return all_stats

def create_summary_report(stats_list: List[Dict], output_path: str):
    """Create a summary report of the analysis."""
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write("# Dimension Index Analysis Summary\n\n")
        
        total_files = len(stats_list)
        total_dimensions = sum(s['dimensions_count'] for s in stats_list)
        total_options = sum(s['total_options'] for s in stats_list)
        
        f.write(f"**Total Files Processed:** {total_files}\n")
        f.write(f"**Total Dimensions:** {total_dimensions}\n")
        f.write(f"**Total Options:** {total_options}\n\n")
        
        f.write("## Files Processed:\n\n")
        for stats in stats_list:
            f.write(f"### {stats['file_id']}\n")
            f.write(f"**Matrix:** {stats['matrix_name']}\n")
            f.write(f"**Dimensions:** {stats['dimensions_count']}\n")
            f.write(f"**Total Options:** {stats['total_options']}\n\n")
            
            for dim in stats['dimensions']:
                f.write(f"- **{dim['label']}** (Code: {dim['dim_code']}) - {dim['options_count']} options\n")
                for opt in dim['options'][:5]:  # Show first 5 options
                    f.write(f"  - {opt}\n")
                if len(dim['options']) > 5:
                    f.write(f"  - ... and {len(dim['options']) - 5} more\n")
            f.write("\n")

def search_dimensions(db_path: str, search_term: str = None):
    """Search for dimensions and options in the database."""
    if not os.path.exists(db_path):
        print(f"Database not found: {db_path}")
        return
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    if search_term:
        print(f"\nSearching for: '{search_term}'\n")
        
        # Search dimensions
        cursor.execute('''
            SELECT DISTINCT label, dim_code, file_id, matrix_name
            FROM dimensions 
            WHERE label LIKE ?
            ORDER BY label, file_id
        ''', (f'%{search_term}%',))
        
        dim_results = cursor.fetchall()
        if dim_results:
            print("=== DIMENSIONS ===")
            for label, dim_code, file_id, matrix_name in dim_results:
                print(f"'{label}' (Code: {dim_code}) in {file_id}")
                print(f"  Matrix: {matrix_name}")
        
        # Search options
        cursor.execute('''
            SELECT DISTINCT o.label, d.label, o.file_id, d.matrix_name
            FROM options o
            JOIN dimensions d ON o.dimension_id = d.id
            WHERE o.label LIKE ?
            ORDER BY o.label, o.file_id
        ''', (f'%{search_term}%',))
        
        opt_results = cursor.fetchall()
        if opt_results:
            print("\n=== OPTIONS ===")
            for opt_label, dim_label, file_id, matrix_name in opt_results:
                print(f"'{opt_label}' in dimension '{dim_label}' ({file_id})")
                print(f"  Matrix: {matrix_name}")
        
        if not dim_results and not opt_results:
            print("No results found.")
    else:
        # Show summary statistics
        cursor.execute('SELECT COUNT(*) FROM dimensions')
        dim_count = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM options')
        opt_count = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(DISTINCT file_id) FROM dimensions')
        file_count = cursor.fetchone()[0]
        
        print(f"\n=== DATABASE SUMMARY ===")
        print(f"Files indexed: {file_count}")
        print(f"Total dimensions: {dim_count}")
        print(f"Total options: {opt_count}")
        
        # Show most common dimension labels
        cursor.execute('''
            SELECT label, COUNT(*) as count
            FROM dimensions
            GROUP BY label
            ORDER BY count DESC
            LIMIT 10
        ''')
        
        common_dims = cursor.fetchall()
        print(f"\n=== MOST COMMON DIMENSION LABELS ===")
        for label, count in common_dims:
            print(f"'{label}': {count} files")
    
    conn.close()

def main():
    """Main function."""
    
    
    # Ensure data directory exists
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    
    if len(sys.argv) > 1 and sys.argv[1] == "search":
        # Search mode
        search_term = sys.argv[2] if len(sys.argv) > 2 else None
        search_dimensions(db_path, search_term)
    else:
        # Analysis mode
        print("Starting dimension analysis...")
        
        stats_list = analyze_directory(metas_dir, db_path)
        
        if stats_list:
            print(f"\nAnalysis complete! Processed {len(stats_list)} files.")
            print(f"Database created: {db_path}")
            
            # Create summary report
            create_summary_report(stats_list, report_path)
            print(f"Summary report created: {report_path}")
            
            # Show quick summary
            search_dimensions(db_path)
            
            print(f"\nTo search the index, run:")
            print(f"python {sys.argv[0]} search 'your_search_term'")
            print(f"python {sys.argv[0]} search  # for general stats")
        else:
            print("No files were successfully processed.")

if __name__ == "__main__":
    main()
