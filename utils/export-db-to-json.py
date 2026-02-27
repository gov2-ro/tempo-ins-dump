#!/usr/bin/env python3
"""
Export the SQLite dimension index database to JSON format for web consumption.
"""

import json
import sqlite3
import sys
from pathlib import Path

DB_PATH = "/Users/pax/devbox/gov2/tempo-ins-dump/data/dimension_index.db"
OUTPUT_PATH = "/Users/pax/devbox/gov2/tempo-ins-dump/ui/data/dimension_index.json"

def export_database_to_json():
    """Export the SQLite database to JSON format."""
    if not Path(DB_PATH).exists():
        print(f"Database not found: {DB_PATH}")
        return False
    
    # Ensure output directory exists
    Path(OUTPUT_PATH).parent.mkdir(parents=True, exist_ok=True)
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Export dimensions
    cursor.execute('''
        SELECT id, label, dim_code, file_id, matrix_name
        FROM dimensions
        ORDER BY file_id, dim_code
    ''')
    
    dimensions = []
    for row in cursor.fetchall():
        dimensions.append({
            'id': row[0],
            'label': row[1],
            'dim_code': row[2],
            'file_id': row[3],
            'matrix_name': row[4]
        })
    
    # Export options
    cursor.execute('''
        SELECT id, label, nom_item_id, offset_value, parent_id, dimension_id, file_id
        FROM options
        ORDER BY dimension_id, offset_value
    ''')
    
    options = []
    for row in cursor.fetchall():
        options.append({
            'id': row[0],
            'label': row[1],
            'nom_item_id': row[2],
            'offset_value': row[3],
            'parent_id': row[4],
            'dimension_id': row[5],
            'file_id': row[6]
        })
    
    # Create export data
    export_data = {
        'dimensions': dimensions,
        'options': options,
        'export_timestamp': None,
        'stats': {
            'total_dimensions': len(dimensions),
            'total_options': len(options),
            'total_files': len(set(d['file_id'] for d in dimensions))
        }
    }
    
    # Add timestamp
    from datetime import datetime
    export_data['export_timestamp'] = datetime.now().isoformat()
    
    # Write to JSON file
    with open(OUTPUT_PATH, 'w', encoding='utf-8') as f:
        json.dump(export_data, f, indent=2, ensure_ascii=False)
    
    conn.close()
    
    print(f"Database exported to: {OUTPUT_PATH}")
    print(f"Exported {len(dimensions)} dimensions and {len(options)} options")
    return True

if __name__ == "__main__":
    success = export_database_to_json()
    if not success:
        sys.exit(1)
