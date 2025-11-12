#!/usr/bin/env python3
"""
Build dataset metadata file with file sizes and row counts.
Scans data/4-datasets/ro/ and generates ui/data/dataset-metadata.json
"""

import os
import json
from pathlib import Path
from typing import Dict, List
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def get_file_size_mb(file_path: str) -> float:
    """Get file size in MB."""
    size_bytes = os.path.getsize(file_path)
    return round(size_bytes / (1024 * 1024), 2)

def count_csv_rows(file_path: str) -> int:
    """Count data rows in CSV file (excluding header)."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            # Count non-empty lines, excluding header
            data_rows = len([line for line in lines[1:] if line.strip()])
            return data_rows
    except Exception as e:
        logger.error(f"Error counting rows in {file_path}: {e}")
        return -1

def extract_ancestor_path(meta_json: Dict) -> str:
    """
    Extract ancestor path from metadata JSON.

    Args:
        meta_json: Metadata dictionary

    Returns:
        Formatted ancestor path string
    """
    import re

    if not meta_json.get('ancestors'):
        return ""

    ancestors = meta_json['ancestors']
    if not isinstance(ancestors, list) or len(ancestors) == 0:
        return ""

    # Extract text from ancestor objects, stripping HTML tags
    path_parts = []
    for ancestor in ancestors:
        if isinstance(ancestor, str):
            clean_name = ancestor
        elif isinstance(ancestor, dict) and ancestor.get('name'):
            clean_name = ancestor['name']
        else:
            continue

        # Strip HTML tags
        clean_name = re.sub(r'<[^>]+>', '', clean_name)
        # Remove extra whitespace and newlines
        clean_name = re.sub(r'\s+', ' ', clean_name)
        # Remove semicolons at end
        clean_name = clean_name.strip().rstrip(';').strip()

        if clean_name and clean_name.lower() != 'home':
            path_parts.append(clean_name)

    return ' → '.join(path_parts)

def build_dataset_metadata(datasets_dir: str = "data/4-datasets/ro",
                           metas_dir: str = "data/2-metas/ro") -> List[Dict]:
    """
    Build metadata for all CSV datasets.

    Args:
        datasets_dir: Directory containing CSV files
        metas_dir: Directory containing metadata JSON files

    Returns:
        List of dictionaries with dataset metadata
    """
    metadata = []
    datasets_path = Path(datasets_dir)
    metas_path = Path(metas_dir)

    if not datasets_path.exists():
        logger.error(f"Datasets directory not found: {datasets_dir}")
        return metadata

    csv_files = sorted(datasets_path.glob("*.csv"))
    total_files = len(csv_files)

    logger.info(f"Found {total_files} CSV files in {datasets_dir}")

    for idx, csv_file in enumerate(csv_files, 1):
        matrix_code = csv_file.stem

        logger.info(f"[{idx}/{total_files}] Processing {matrix_code}...")

        try:
            file_size_mb = get_file_size_mb(str(csv_file))
            row_count = count_csv_rows(str(csv_file))

            # Load metadata JSON to get ancestor path
            ancestor_path = ""
            meta_file = metas_path / f"{matrix_code}.json"
            if meta_file.exists():
                try:
                    with open(meta_file, 'r', encoding='utf-8') as f:
                        meta_json = json.load(f)
                        ancestor_path = extract_ancestor_path(meta_json)
                except Exception as e:
                    logger.warning(f"  Could not load metadata for {matrix_code}: {e}")

            metadata.append({
                "matrixCode": matrix_code,
                "fileSizeMB": file_size_mb,
                "rowCount": row_count,
                "filePath": f"data/4-datasets/ro/{csv_file.name}",
                "ancestorPath": ancestor_path
            })

            if ancestor_path:
                logger.info(f"  Size: {file_size_mb} MB, Rows: {row_count:,}, Path: {ancestor_path[:80]}...")
            else:
                logger.info(f"  Size: {file_size_mb} MB, Rows: {row_count:,}")

        except Exception as e:
            logger.error(f"Error processing {matrix_code}: {e}")
            continue

    return metadata

def main():
    """Main execution."""
    logger.info("Building dataset metadata...")

    # Build metadata
    metadata = build_dataset_metadata()

    if not metadata:
        logger.error("No metadata generated")
        return

    # Sort by file size descending
    metadata.sort(key=lambda x: x["fileSizeMB"], reverse=True)

    # Calculate statistics
    total_size = sum(item["fileSizeMB"] for item in metadata)
    total_rows = sum(item["rowCount"] for item in metadata if item["rowCount"] > 0)
    avg_size = total_size / len(metadata) if metadata else 0

    logger.info(f"\n=== Statistics ===")
    logger.info(f"Total datasets: {len(metadata)}")
    logger.info(f"Total size: {total_size:.2f} MB")
    logger.info(f"Total rows: {total_rows:,}")
    logger.info(f"Average size: {avg_size:.2f} MB")
    logger.info(f"Largest dataset: {metadata[0]['matrixCode']} ({metadata[0]['fileSizeMB']} MB)")
    logger.info(f"Smallest dataset: {metadata[-1]['matrixCode']} ({metadata[-1]['fileSizeMB']} MB)")

    # Count datasets > 5MB
    large_datasets = [d for d in metadata if d["fileSizeMB"] > 5]
    logger.info(f"Datasets > 5 MB: {len(large_datasets)}")

    # Save to JSON
    output_dir = Path("ui/data")
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / "dataset-metadata.json"

    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump({
            "metadata": metadata,
            "stats": {
                "totalDatasets": len(metadata),
                "totalSizeMB": round(total_size, 2),
                "totalRows": total_rows,
                "averageSizeMB": round(avg_size, 2),
                "datasetsOver5MB": len(large_datasets)
            },
            "generated": "2025-11-12"
        }, f, ensure_ascii=False, indent=2)

    logger.info(f"\nMetadata saved to {output_file}")

if __name__ == "__main__":
    main()
