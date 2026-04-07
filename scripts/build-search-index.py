#!/usr/bin/env python
"""Build a DuckDB FTS search index for dataset discovery.

Creates a sidecar `data/corpus/search.duckdb` with full-text search over:
  - Matrix names (RO + EN)
  - Dataset tags (92k bilingual tags from context, matrix_name, indicator sources)
  - Dataset definitions

The sidecar avoids write-lock conflicts with the main metadata.duckdb.
Read-only at runtime; rebuild when metadata changes.

Usage:
    python scripts/build-search-index.py [--debug]
"""
import argparse
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.config import CORPUS_DIR, DB_PATH

SEARCH_DB_PATH = CORPUS_DIR / "search.duckdb"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("build-search-index")


def build_index(debug: bool = False):
    import duckdb

    if debug:
        log.setLevel(logging.DEBUG)

    t0 = time.time()

    # Remove existing sidecar
    if SEARCH_DB_PATH.exists():
        SEARCH_DB_PATH.unlink()
        log.info("Removed existing %s", SEARCH_DB_PATH)

    # Open main metadata DB read-only
    src = duckdb.connect(str(DB_PATH), read_only=True)

    # Create sidecar DB
    dst = duckdb.connect(str(SEARCH_DB_PATH))
    dst.execute("INSTALL fts; LOAD fts;")

    # ---------------------------------------------------------------------------
    # 1. Build search_docs table — one row per dataset, all searchable text merged
    # ---------------------------------------------------------------------------
    log.info("Building search_docs table from metadata.duckdb ...")

    # Fetch matrix data
    matrices = src.execute("""
        SELECT matrix_code, matrix_name, matrix_name_en, definitie
        FROM matrices
        WHERE is_canonical = TRUE
    """).fetchall()

    # Fetch tags grouped by matrix_code
    tags_raw = src.execute("""
        SELECT matrix_code,
               STRING_AGG(COALESCE(tag_ro, ''), ' ') AS tags_ro,
               STRING_AGG(COALESCE(tag_en, ''), ' ') AS tags_en
        FROM dataset_tags
        GROUP BY matrix_code
    """).fetchall()
    tags_map = {r[0]: (r[1], r[2]) for r in tags_raw}

    # Fetch context paths
    contexts_raw = src.execute("""
        SELECT m.matrix_code,
               STRING_AGG(c.context_name, ' > ') AS context_path,
               STRING_AGG(COALESCE(c.context_name_en, c.context_name), ' > ') AS context_path_en
        FROM matrices m,
             UNNEST(m.ancestor_codes) AS t(ac)
        JOIN contexts c ON t.ac::VARCHAR = c.context_code
        WHERE m.is_canonical = TRUE
        GROUP BY m.matrix_code
    """).fetchall()
    context_map = {r[0]: (r[1], r[2]) for r in contexts_raw}

    src.close()

    # Create search_docs table
    dst.execute("""
        CREATE TABLE search_docs (
            matrix_code VARCHAR PRIMARY KEY,
            name_ro VARCHAR,
            name_en VARCHAR,
            definitie VARCHAR,
            tags_ro VARCHAR,
            tags_en VARCHAR,
            context_ro VARCHAR,
            context_en VARCHAR,
            search_text VARCHAR
        )
    """)

    # Insert rows with merged search text
    insert_sql = """
        INSERT INTO search_docs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """

    count = 0
    for code, name_ro, name_en, definitie in matrices:
        tags_ro, tags_en = tags_map.get(code, ("", ""))
        ctx_ro, ctx_en = context_map.get(code, ("", ""))

        # Merge all searchable text into one field for FTS
        search_text = " ".join(filter(None, [
            name_ro, name_en, definitie, tags_ro, tags_en, ctx_ro, ctx_en, code
        ]))

        dst.execute(insert_sql, [
            code, name_ro, name_en, definitie,
            tags_ro, tags_en, ctx_ro, ctx_en, search_text
        ])
        count += 1

    log.info("Inserted %d documents", count)

    # ---------------------------------------------------------------------------
    # 2. Create FTS index on search_text
    # ---------------------------------------------------------------------------
    log.info("Creating FTS index ...")
    dst.execute("""
        PRAGMA create_fts_index(
            'search_docs', 'matrix_code',
            'search_text', 'name_ro', 'name_en',
            stemmer = 'none',
            stopwords = 'none',
            ignore = '(\\.|[^a-zA-Z0-9ăâîșțĂÂÎȘȚ\\s])+',
            lower = 1,
            overwrite = 1
        )
    """)

    # ---------------------------------------------------------------------------
    # 3. Verify
    # ---------------------------------------------------------------------------
    test_queries = ["somaj", "population", "GDP", "populatie judete", "agriculture"]
    log.info("Verification:")
    for q in test_queries:
        rows = dst.execute("""
            SELECT sd.matrix_code, sd.name_ro, fts_main_search_docs.match_bm25(sd.matrix_code, ?) AS score
            FROM search_docs sd
            WHERE score IS NOT NULL
            ORDER BY score
            LIMIT 3
        """, [q]).fetchall()
        if rows:
            top = rows[0]
            log.info("  '%s' → %s (score %.2f) + %d more", q, top[0], top[2], len(rows) - 1)
        else:
            log.info("  '%s' → no results", q)

    dst.close()

    elapsed = time.time() - t0
    size_mb = SEARCH_DB_PATH.stat().st_size / 1024 / 1024
    log.info("Done in %.1fs — %s (%.1f MB)", elapsed, SEARCH_DB_PATH, size_mb)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build FTS search index")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()
    build_index(debug=args.debug)
