#!/usr/bin/env python3
"""
Enhanced Navigator Index Builder

Creates optimized indexes for the new dataset navigator:
1. Enhanced metadata SQLite DB for server-side filtering
2. Static navigation indexes (JSON) for client-side performance
3. Search index with pre-processed terms
"""

import json
import sqlite3
import csv
import os
import re
from pathlib import Path
from datetime import datetime
from collections import defaultdict, Counter
import argparse

DATA_DIR = Path("data")
METAS_DIR = DATA_DIR / "2-metas" / "ro"
INDEXES_DIR = DATA_DIR / "1-indexes" / "ro" 
UI_DATA_DIR = Path("ui") / "data"

def setup_enhanced_db():
    """Create enhanced metadata database with optimized schema"""
    db_path = UI_DATA_DIR / "enhanced_navigator.db"
    UI_DATA_DIR.mkdir(exist_ok=True)
    
    if db_path.exists():
        db_path.unlink()
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Enhanced datasets table with all filterable metadata
    cursor.execute('''
        CREATE TABLE datasets (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            context_code TEXT,
            category_path TEXT,
            theme_code TEXT,
            description TEXT,
            periodicity TEXT,
            last_update TEXT,
            update_year INTEGER,
            data_sources TEXT,
            methodology_available BOOLEAN,
            dimensions_count INTEGER,
            dimensions_list TEXT,
            geographic_level TEXT,
            um_label TEXT,
            um_classification TEXT,
            quality_score REAL,
            has_recent_data BOOLEAN,
            time_span_start INTEGER,
            time_span_end INTEGER,
            keywords TEXT,
            search_text TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Navigation tree table for fast category lookups
    cursor.execute('''
        CREATE TABLE navigation_tree (
            code TEXT PRIMARY KEY,
            name TEXT,
            parent_code TEXT,
            level INTEGER,
            path TEXT,
            dataset_count INTEGER,
            children_codes TEXT
        )
    ''')
    
    # Faceted filters table for dynamic filter building
    cursor.execute('''
        CREATE TABLE filter_values (
            category TEXT,
            value TEXT,
            count INTEGER,
            PRIMARY KEY (category, value)
        )
    ''')
    
    # Create indexes for performance
    cursor.execute('CREATE INDEX idx_datasets_theme ON datasets(theme_code)')
    cursor.execute('CREATE INDEX idx_datasets_context ON datasets(context_code)')
    cursor.execute('CREATE INDEX idx_datasets_update ON datasets(update_year)')
    cursor.execute('CREATE INDEX idx_datasets_quality ON datasets(quality_score)')
    cursor.execute('CREATE INDEX idx_datasets_search ON datasets(search_text)')
    cursor.execute('CREATE INDEX idx_nav_parent ON navigation_tree(parent_code)')
    
    return conn

def load_matrices_data():
    """Load and parse matrices.csv"""
    matrices_path = INDEXES_DIR / "matrices.csv"
    datasets = {}
    
    with open(matrices_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get('code'):
                datasets[row['code']] = {
                    'title': row.get('name', ''),
                    'context_code': row.get('comment', ''),  # Check if this maps correctly
                    'filename': row.get('code', '')
                }
    
    return datasets

def load_context_tree():
    """Load and process context hierarchy"""
    context_path = INDEXES_DIR / "context.json"
    with open(context_path, 'r', encoding='utf-8') as f:
        contexts = json.load(f)
    
    # Build tree structure and paths
    context_map = {}
    tree_structure = {}
    
    for item in contexts:
        context = item['context']
        code = context['code']
        context_map[code] = {
            'name': context['name'],
            'parent_code': item.get('parentCode', ''),
            'level': item.get('level', 0),
            'path': '',
            'children': []
        }
    
    # Build parent-child relationships and paths
    for code, info in context_map.items():
        parent_code = info['parent_code']
        if parent_code and parent_code in context_map:
            context_map[parent_code]['children'].append(code)
            # Build breadcrumb path
            path_parts = []
            current = code
            while current and current in context_map:
                path_parts.insert(0, context_map[current]['name'])
                current = context_map[current]['parent_code']
            info['path'] = ' > '.join(path_parts)
    
    return context_map

def extract_keywords(text):
    """Extract meaningful keywords from text"""
    if not text:
        return []
    
    # Clean and tokenize
    text = re.sub(r'[^\w\s]', ' ', text.lower())
    words = text.split()
    
    # Filter meaningful words (length > 3, not common words)
    stopwords = {'pentru', 'prin', 'dupa', 'sunt', 'este', 'unei', 'unor', 'toate', 'alte', 'care', 'acestea'}
    keywords = [w for w in words if len(w) > 3 and w not in stopwords]
    
    return list(set(keywords))

def calculate_quality_score(meta, dimensions_count):
    """Calculate a quality score based on metadata completeness"""
    score = 0.0
    
    # Base score for having metadata
    if meta.get('definitie'): score += 0.3
    if meta.get('metodologie'): score += 0.2
    if meta.get('surseDeDate'): score += 0.2
    if meta.get('ultimaActualizare'): score += 0.1
    if dimensions_count > 0: score += 0.2
    
    return min(score, 1.0)

def determine_geographic_level(dimensions):
    """Determine geographic granularity from dimensions"""
    geo_indicators = {
        'national': ['total', 'romania'],
        'regional': ['regiuni', 'macroregiuni'],
        'county': ['judete', 'judet'],
        'local': ['localita', 'comuna', 'orase']
    }
    
    dimensions_text = ' '.join(dimensions).lower()
    
    for level, indicators in geo_indicators.items():
        if any(indicator in dimensions_text for indicator in indicators):
            return level
    
    return 'unknown'

def extract_time_span(meta):
    """Extract time span from metadata"""
    start_year, end_year = None, None
    
    dimensions = meta.get('dimensionsMap', [])
    for dim in dimensions:
        if 'perioade' in dim.get('label', '').lower():
            options = dim.get('options', [])
            years = []
            for opt in options:
                label = opt.get('label', '')
                # Extract years from labels like "Anul 2020"
                year_match = re.search(r'(\d{4})', label)
                if year_match:
                    years.append(int(year_match.group(1)))
            
            if years:
                start_year = min(years)
                end_year = max(years)
            break
    
    return start_year, end_year

def process_datasets(conn, matrices_data, context_map):
    """Process all datasets and build enhanced metadata"""
    cursor = conn.cursor()
    
    processed_count = 0
    filter_counts = defaultdict(Counter)
    
    for filename in os.listdir(METAS_DIR):
        if not filename.endswith('.json'):
            continue
            
        dataset_id = filename[:-5]  # Remove .json
        meta_path = METAS_DIR / filename
        
        try:
            with open(meta_path, 'r', encoding='utf-8') as f:
                meta = json.load(f)
            
            # Get basic info
            title = matrices_data.get(dataset_id, {}).get('title', '') or meta.get('matrixName', '')
            context_code = ''
            
            # Extract context code from ancestors
            ancestors = meta.get('ancestors', [])
            if ancestors:
                context_code = ancestors[-1].get('code', '')
            
            # Build category path
            category_path = ' > '.join([a.get('name', '') for a in ancestors if a.get('name')])
            
            # Determine theme (top-level category)
            theme_code = ancestors[1].get('code', '') if len(ancestors) > 1 else ''
            
            # Process dimensions
            dimensions = meta.get('dimensionsMap', [])
            dimensions_list = [d.get('label', '') for d in dimensions if d.get('label')]
            dimensions_count = len(dimensions_list)
            
            # Extract time span
            start_year, end_year = extract_time_span(meta)
            
            # Determine geographic level
            geo_level = determine_geographic_level(dimensions_list)
            
            # Extract keywords
            search_text_parts = [
                title,
                meta.get('definitie', ''),
                ' '.join(dimensions_list),
                category_path
            ]
            search_text = ' '.join(filter(None, search_text_parts))
            keywords = extract_keywords(search_text)
            
            # Calculate quality score
            quality_score = calculate_quality_score(meta, dimensions_count)
            
            # Parse update date
            update_date = meta.get('ultimaActualizare', '')
            update_year = None
            if update_date:
                try:
                    # Try to parse date format like "03-10-2019"
                    parts = update_date.split('-')
                    if len(parts) >= 3:
                        update_year = int(parts[-1])
                except:
                    pass
            
            # Check if has recent data (within last 5 years)
            current_year = datetime.now().year
            has_recent_data = end_year and end_year >= (current_year - 5)
            
            # Data sources
            sources = meta.get('surseDeDate', [])
            sources_text = ', '.join([s.get('nume', '') for s in sources])
            
            # Insert dataset
            cursor.execute('''
                INSERT INTO datasets (
                    id, title, context_code, category_path, theme_code, description,
                    periodicity, last_update, update_year, data_sources, methodology_available,
                    dimensions_count, dimensions_list, geographic_level, quality_score,
                    has_recent_data, time_span_start, time_span_end, keywords, search_text
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                dataset_id, title, context_code, category_path, theme_code,
                meta.get('definitie', ''), 
                meta.get('periodicitati', [''])[0] if meta.get('periodicitati') else '',
                update_date, update_year, sources_text,
                bool(meta.get('metodologie')), dimensions_count,
                ', '.join(dimensions_list), geo_level, quality_score,
                has_recent_data, start_year, end_year,
                ', '.join(keywords), search_text
            ))
            
            # Collect filter counts
            filter_counts['periodicity'][meta.get('periodicitati', [''])[0] if meta.get('periodicitati') else 'Unknown'] += 1
            filter_counts['geographic_level'][geo_level] += 1
            filter_counts['theme'][theme_code] += 1
            filter_counts['has_methodology'][bool(meta.get('metodologie'))] += 1
            filter_counts['has_recent_data'][has_recent_data] += 1
            
            processed_count += 1
            if processed_count % 100 == 0:
                print(f"Processed {processed_count} datasets...")
                
        except Exception as e:
            print(f"Error processing {filename}: {e}")
            continue
    
    # Insert filter values
    for category, values in filter_counts.items():
        for value, count in values.items():
            cursor.execute('INSERT INTO filter_values (category, value, count) VALUES (?, ?, ?)',
                          (category, str(value), count))
    
    conn.commit()
    print(f"Processed {processed_count} datasets total")
    return processed_count

def build_navigation_tree(conn, context_map):
    """Build navigation tree in database"""
    cursor = conn.cursor()
    
    # Count datasets per category
    cursor.execute('SELECT context_code, COUNT(*) FROM datasets GROUP BY context_code')
    dataset_counts = dict(cursor.fetchall())
    
    # Insert navigation nodes
    for code, info in context_map.items():
        children_codes = ','.join(info['children']) if info['children'] else ''
        dataset_count = dataset_counts.get(code, 0)
        
        cursor.execute('''
            INSERT INTO navigation_tree (code, name, parent_code, level, path, dataset_count, children_codes)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (code, info['name'], info['parent_code'], info['level'], 
              info['path'], dataset_count, children_codes))
    
    conn.commit()

def create_static_indexes(conn):
    """Create static JSON indexes for client-side performance"""
    cursor = conn.cursor()
    
    # Navigation tree for instant loading
    cursor.execute('''
        SELECT code, name, parent_code, level, path, dataset_count, children_codes
        FROM navigation_tree ORDER BY level, name
    ''')
    
    nav_tree = []
    for row in cursor.fetchall():
        nav_tree.append({
            'code': row[0],
            'name': row[1],
            'parent_code': row[2],
            'level': row[3],
            'path': row[4],
            'dataset_count': row[5],
            'children_codes': row[6].split(',') if row[6] else []
        })
    
    # Filter options for faceted search
    cursor.execute('SELECT category, value, count FROM filter_values')
    filter_options = {}
    for category, value, count in cursor.fetchall():
        if category not in filter_options:
            filter_options[category] = []
        filter_options[category].append({'value': value, 'count': count})
    
    # Basic dataset stats
    cursor.execute('SELECT COUNT(*) FROM datasets')
    total_datasets = cursor.fetchone()[0]
    
    cursor.execute('SELECT COUNT(*) FROM navigation_tree WHERE level = 1')
    total_themes = cursor.fetchone()[0]
    
    # Search suggestions (top keywords)
    cursor.execute('SELECT keywords FROM datasets WHERE keywords != ""')
    all_keywords = []
    for (keywords_str,) in cursor.fetchall():
        all_keywords.extend(keywords_str.split(', '))
    
    keyword_counts = Counter(all_keywords)
    search_suggestions = [word for word, count in keyword_counts.most_common(100)]
    
    # Create static indexes
    static_data = {
        'navigation_tree': nav_tree,
        'filter_options': filter_options,
        'search_suggestions': search_suggestions,
        'stats': {
            'total_datasets': total_datasets,
            'total_themes': total_themes,
            'last_updated': datetime.now().isoformat()
        }
    }
    
    # Save to JSON file
    with open(UI_DATA_DIR / "navigation_index.json", 'w', encoding='utf-8') as f:
        json.dump(static_data, f, ensure_ascii=False, indent=2)
    
    print(f"Created static navigation index with {len(nav_tree)} navigation nodes")
    print(f"Created {len(search_suggestions)} search suggestions")

def main():
    parser = argparse.ArgumentParser(description='Build enhanced navigator indexes')
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose output')
    args = parser.parse_args()
    
    print("Building enhanced navigator indexes...")
    
    # Load base data
    print("Loading matrices and context data...")
    matrices_data = load_matrices_data()
    context_map = load_context_tree()
    
    # Setup database
    print("Setting up enhanced database...")
    conn = setup_enhanced_db()
    
    # Process datasets
    print("Processing datasets...")
    dataset_count = process_datasets(conn, matrices_data, context_map)
    
    # Build navigation tree
    print("Building navigation tree...")
    build_navigation_tree(conn, context_map)
    
    # Create static indexes
    print("Creating static indexes...")
    create_static_indexes(conn)
    
    conn.close()
    
    print(f"\n✅ Enhanced navigator indexes built successfully!")
    print(f"📊 Processed {dataset_count} datasets")
    print(f"📁 Database: ui/data/enhanced_navigator.db")
    print(f"📄 Static index: ui/data/navigation_index.json")

if __name__ == "__main__":
    main()