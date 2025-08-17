#!/usr/bin/env python3
"""
Helper script for querying the dimension index database with various useful queries.
"""

import sqlite3
import sys
from tabulate import tabulate

DB_PATH = "/Users/pax/devbox/gov2/tempo-ins-dump/data/dimension_index.db"

def query_database(query, params=None):
    """Execute a query and return results."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    if params:
        cursor.execute(query, params)
    else:
        cursor.execute(query)
    
    results = cursor.fetchall()
    conn.close()
    return results

def show_file_summary():
    """Show summary of each file processed."""
    query = """
    SELECT 
        d.file_id,
        d.matrix_name,
        COUNT(DISTINCT d.id) as dimension_count,
        COUNT(o.id) as option_count
    FROM dimensions d
    LEFT JOIN options o ON d.id = o.dimension_id
    GROUP BY d.file_id, d.matrix_name
    ORDER BY d.file_id
    """
    
    results = query_database(query)
    headers = ["File ID", "Matrix Name", "Dimensions", "Options"]
    print("=== FILE SUMMARY ===")
    print(tabulate(results, headers=headers, tablefmt="grid"))

def show_dimension_usage():
    """Show how often each dimension label appears across files."""
    query = """
    SELECT 
        label,
        COUNT(*) as file_count,
        GROUP_CONCAT(file_id, ', ') as files
    FROM dimensions
    GROUP BY label
    ORDER BY file_count DESC, label
    """
    
    results = query_database(query)
    headers = ["Dimension Label", "File Count", "Files"]
    print("\n=== DIMENSION USAGE ===")
    print(tabulate(results, headers=headers, tablefmt="grid"))

def search_options_by_pattern(pattern):
    """Search for options matching a pattern."""
    query = """
    SELECT 
        o.label as option_label,
        d.label as dimension_label,
        o.file_id,
        d.matrix_name
    FROM options o
    JOIN dimensions d ON o.dimension_id = d.id
    WHERE o.label LIKE ?
    ORDER BY o.label, o.file_id
    """
    
    results = query_database(query, (f'%{pattern}%',))
    headers = ["Option", "Dimension", "File ID", "Matrix"]
    print(f"\n=== OPTIONS MATCHING '{pattern}' ===")
    print(tabulate(results, headers=headers, tablefmt="grid"))

def show_file_dimensions(file_id):
    """Show all dimensions and their options for a specific file."""
    query = """
    SELECT 
        d.label as dimension_label,
        d.dim_code,
        GROUP_CONCAT(o.label, ' | ') as options
    FROM dimensions d
    LEFT JOIN options o ON d.id = o.dimension_id
    WHERE d.file_id = ?
    GROUP BY d.id, d.label, d.dim_code
    ORDER BY d.dim_code
    """
    
    results = query_database(query, (file_id,))
    if not results:
        print(f"No data found for file: {file_id}")
        return
    
    # Get matrix name
    matrix_query = "SELECT DISTINCT matrix_name FROM dimensions WHERE file_id = ?"
    matrix_result = query_database(matrix_query, (file_id,))
    matrix_name = matrix_result[0][0] if matrix_result else "Unknown"
    
    headers = ["Dimension", "Code", "Options"]
    print(f"\n=== FILE: {file_id} ===")
    print(f"Matrix: {matrix_name}")
    print(tabulate(results, headers=headers, tablefmt="grid"))

def show_dimension_details(dimension_label):
    """Show details for a specific dimension label."""
    query = """
    SELECT 
        d.file_id,
        d.dim_code,
        d.matrix_name,
        COUNT(o.id) as option_count
    FROM dimensions d
    LEFT JOIN options o ON d.id = o.dimension_id
    WHERE d.label = ?
    GROUP BY d.id
    ORDER BY d.file_id
    """
    
    results = query_database(query, (dimension_label,))
    if not results:
        print(f"No dimension found with label: {dimension_label}")
        return
    
    headers = ["File ID", "Dim Code", "Matrix Name", "Options"]
    print(f"\n=== DIMENSION: '{dimension_label}' ===")
    print(tabulate(results, headers=headers, tablefmt="grid"))
    
    # Show unique options for this dimension
    options_query = """
    SELECT DISTINCT o.label
    FROM options o
    JOIN dimensions d ON o.dimension_id = d.id
    WHERE d.label = ?
    ORDER BY o.label
    """
    
    option_results = query_database(options_query, (dimension_label,))
    if option_results:
        print(f"\nUnique options for '{dimension_label}':")
        for (option,) in option_results:
            print(f"  - {option}")

def main():
    """Main function with command-line interface."""
    if len(sys.argv) < 2:
        print("Usage:")
        print(f"  {sys.argv[0]} summary           # Show file summary")
        print(f"  {sys.argv[0]} usage             # Show dimension usage")
        print(f"  {sys.argv[0]} search <pattern>  # Search options")
        print(f"  {sys.argv[0]} file <file_id>    # Show file details")
        print(f"  {sys.argv[0]} dim <label>       # Show dimension details")
        return
    
    command = sys.argv[1].lower()
    
    try:
        if command == "summary":
            show_file_summary()
        elif command == "usage":
            show_dimension_usage()
        elif command == "search" and len(sys.argv) > 2:
            search_options_by_pattern(sys.argv[2])
        elif command == "file" and len(sys.argv) > 2:
            show_file_dimensions(sys.argv[2])
        elif command == "dim" and len(sys.argv) > 2:
            show_dimension_details(sys.argv[2])
        else:
            print("Invalid command or missing parameter.")
            main()
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()
