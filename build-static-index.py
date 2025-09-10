#!/usr/bin/env python3
"""
Build script to generate static data index for client-side explorer

Creates:
- ui/data/datasets-index.json - Master index with all dataset metadata
- ui/data/flags-index.json - Flag counts for the sidebar
- ui/data/datasets/ - Individual dataset JSON files (symlinked)
- ui/data/csv/ - CSV files (symlinked for preview)
"""

import os
import json
import logging
from pathlib import Path
from collections import Counter
from typing import Dict, Any, List

# Configure paths
REPO_ROOT = Path(__file__).resolve().parent
COMBINED_DIR = REPO_ROOT / 'data' / 'profiling' / 'combined'
META_DIR = REPO_ROOT / 'data' / '2-metas' / 'ro'
CSV_DIR = REPO_ROOT / 'data' / '4-datasets' / 'ro'
UI_DATA_DIR = REPO_ROOT / 'ui' / 'data'

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("build-static")


def load_dataset(path: Path) -> Dict[str, Any]:
    """Load a dataset JSON file"""
    with path.open('r', encoding='utf-8') as f:
        return json.load(f)


def get_csv_size_info(csv_path: str) -> Dict[str, Any]:
    """Get CSV file size and determine if truncation is needed"""
    if not os.path.exists(csv_path):
        return {'file_size_mb': 0, 'should_truncate': False, 'max_rows': None}
    
    file_size = os.path.getsize(csv_path)
    file_size_mb = round(file_size / (1024 * 1024), 2)
    should_truncate = file_size > 4 * 1024 * 1024  # 4MB
    max_rows = 400 if should_truncate else None
    
    return {
        'file_size_mb': file_size_mb,
        'should_truncate': should_truncate,
        'max_rows': max_rows
    }


def build_datasets_index() -> List[Dict[str, Any]]:
    """Build the master datasets index"""
    items = []
    
    for json_path in sorted(COMBINED_DIR.glob('*.json')):
        try:
            data = load_dataset(json_path)
            ds_id = json_path.stem
            source_csv = data.get('source_csv')
            file_checks = data.get('file_checks', {})
            vsummary = file_checks.get('validation_summary', {})

            # Load matrix name from metadata
            matrix_name = None
            meta_file = META_DIR / f'{ds_id}.json'
            if meta_file.exists():
                try:
                    with meta_file.open('r', encoding='utf-8') as f:
                        meta_data = json.load(f)
                        matrix_name = meta_data.get('matrixName')
                except Exception as e:
                    logger.warning("Failed to load metadata for %s: %s", ds_id, e)

            # Aggregate flags across columns
            flags = set()
            for col in data.get('columns', []):
                for fl in col.get('validation_flags', []) or []:
                    flags.add(fl)

            # Get CSV size info
            csv_info = get_csv_size_info(source_csv) if source_csv else {}

            items.append({
                'id': ds_id,
                'name': os.path.basename(source_csv) if source_csv else ds_id,
                'matrix_name': matrix_name,
                'source_csv': source_csv,
                'um_label': file_checks.get('um_label'),
                'validation_summary': vsummary,
                'flags': sorted(flags),
                'columns_count': len(data.get('columns', [])),
                'csv_info': csv_info
            })
        except Exception as e:
            logger.warning("Failed to process %s: %s", json_path.name, e)
    
    return items


def build_flags_index(datasets: List[Dict[str, Any]]) -> Dict[str, int]:
    """Build flag counts index"""
    counter = Counter()
    for dataset in datasets:
        for flag in dataset.get('flags', []):
            counter[flag] += 1
    return dict(sorted(counter.items()))


def setup_symlinks():
    """Setup symlinks for datasets and CSV files"""
    ui_datasets_dir = UI_DATA_DIR / 'datasets'
    ui_csv_dir = UI_DATA_DIR / 'csv'
    
    # Remove existing directories
    if ui_datasets_dir.exists():
        os.system(f'rm -rf "{ui_datasets_dir}"')
    if ui_csv_dir.exists():
        os.system(f'rm -rf "{ui_csv_dir}"')
    
    # Create directories
    ui_datasets_dir.mkdir(parents=True, exist_ok=True)
    ui_csv_dir.mkdir(parents=True, exist_ok=True)
    
    # Symlink dataset JSON files
    for json_file in COMBINED_DIR.glob('*.json'):
        target = ui_datasets_dir / json_file.name
        os.symlink(json_file.resolve(), target)
        logger.info(f"Linked dataset: {json_file.name}")
    
    # Symlink CSV files
    csv_count = 0
    for csv_file in CSV_DIR.glob('*.csv'):
        target = ui_csv_dir / csv_file.name
        os.symlink(csv_file.resolve(), target)
        csv_count += 1
    
    logger.info(f"Linked {csv_count} CSV files")


def main():
    """Main build process"""
    logger.info("Building static data index...")
    
    # Ensure UI data directory exists
    UI_DATA_DIR.mkdir(parents=True, exist_ok=True)
    
    # Build datasets index
    logger.info("Building datasets index...")
    datasets = build_datasets_index()
    logger.info(f"Found {len(datasets)} datasets")
    
    # Build flags index
    logger.info("Building flags index...")
    flags = build_flags_index(datasets)
    logger.info(f"Found {len(flags)} unique flags")
    
    # Write datasets index
    datasets_index_file = UI_DATA_DIR / 'datasets-index.json'
    with datasets_index_file.open('w', encoding='utf-8') as f:
        json.dump(datasets, f, indent=2, ensure_ascii=False)
    logger.info(f"Wrote datasets index: {datasets_index_file}")
    
    # Write flags index
    flags_index_file = UI_DATA_DIR / 'flags-index.json'
    with flags_index_file.open('w', encoding='utf-8') as f:
        json.dump({'counts': flags}, f, indent=2, ensure_ascii=False)
    logger.info(f"Wrote flags index: {flags_index_file}")
    
    # Setup symlinks
    logger.info("Setting up symlinks...")
    setup_symlinks()
    
    logger.info("Static build complete!")
    logger.info(f"Total size of datasets index: {datasets_index_file.stat().st_size // 1024}KB")


if __name__ == '__main__':
    main()
