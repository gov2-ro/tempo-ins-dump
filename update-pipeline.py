#!/usr/bin/env python3
"""
Incremental dataset update orchestrator.

Reads the INS TEMPO news page (data/insse_news.csv) to get updated matrix codes,
then runs the full pipeline for only those matrices.

Usage:
    python update-pipeline.py                          # process all news entries
    python update-pipeline.py --since 06.04.2026       # only entries from this date
    python update-pipeline.py --matrix TMI1163         # specific matrix, bypass news
    python update-pipeline.py --matrix A,B --dry-run   # preview without running
    python update-pipeline.py --refetch-news --since 06.04.2026  # re-fetch news first
    python update-pipeline.py --fetch-context          # also refresh context + matrices index
"""

import argparse
import json
import logging
import os
import random
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import duckdb
import pandas as pd
import requests

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).parent
NEWS_CSV = BASE_DIR / "data" / "insse_news.csv"
NEWS_URL = "http://statistici.insse.ro:8077/tempo-ins/news/"
META_BASE_URL = "http://statistici.insse.ro:8077/tempo-ins/matrix/"
LOG_DIR = BASE_DIR / "data" / "logs"
LAST_RUN_FILE = LOG_DIR / "last-pipeline-run.txt"

META_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "http://statistici.insse.ro:8077/tempo-online/",
    "X-Requested-With": "XMLHttpRequest",
    "Connection": "keep-alive",
}

NEWS_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "http://statistici.insse.ro:8077/tempo-online/",
    "Connection": "keep-alive",
}

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def sync_ultima_actualizare(codes: list[str], lang: str, dry_run: bool = False) -> int:
    """Update matrices.ultima_actualizare in DuckDB from freshly fetched metadata JSONs."""
    meta_dir = BASE_DIR / "data" / "2-metas" / lang
    db_path = BASE_DIR / "data" / "corpus" / "metadata.duckdb"

    if dry_run:
        log.info(f"[DRY-RUN] sync_ultima_actualizare for {len(codes)} matrices")
        return 0

    updated = 0
    conn = duckdb.connect(str(db_path))
    try:
        for code in codes:
            json_path = meta_dir / f"{code}.json"
            if not json_path.exists():
                continue
            try:
                meta = json.loads(json_path.read_text(encoding="utf-8"))
                raw = meta.get("ultimaActualizare", "")
                if not raw:
                    continue
                date = datetime.strptime(raw.strip(), "%d-%m-%Y").date()
                conn.execute(
                    "UPDATE matrices SET ultima_actualizare = ? WHERE matrix_code = ?",
                    [date, code]
                )
                updated += 1
            except Exception as e:
                log.warning(f"  {code}: could not sync date — {e}")
    finally:
        conn.close()

    log.info(f"Synced ultima_actualizare for {updated}/{len(codes)} matrices")
    return updated


def run(cmd: list[str], dry_run: bool = False, label: str = "") -> bool:
    """Run a subprocess. Returns True on success."""
    display = " ".join(cmd)
    if dry_run:
        log.info(f"[DRY-RUN] {label or display}")
        return True
    log.info(f"Running: {display}")
    result = subprocess.run(cmd, cwd=BASE_DIR)
    if result.returncode != 0:
        log.error(f"FAILED (exit {result.returncode}): {display}")
        return False
    return True


def python(script: str, args: list[str], dry_run: bool = False) -> bool:
    return run([sys.executable, script] + args, dry_run=dry_run, label=f"{script} {' '.join(args)}")


def read_last_run() -> str | None:
    """Return the date of the last successful run in DD.MM.YYYY format, or None."""
    if LAST_RUN_FILE.exists():
        return LAST_RUN_FILE.read_text().strip()
    return None


def write_last_run() -> None:
    """Record today as the last successful run date."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    LAST_RUN_FILE.write_text(datetime.now().strftime("%d.%m.%Y"))


def fetch_news() -> None:
    log.info(f"Fetching news from {NEWS_URL}...")
    try:
        resp = requests.get(NEWS_URL, headers=NEWS_HEADERS, timeout=20)
        resp.raise_for_status()
        tables = pd.read_html(resp.text, flavor="bs4")
        if not tables:
            log.error("No tables found in news page")
            return
        df = tables[0]
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        df.to_csv(NEWS_CSV, index=False, encoding="utf-8-sig")
        log.info(f"Saved {len(df)} rows to {NEWS_CSV}")
    except Exception as e:
        log.error(f"Failed to fetch news: {e}")


def parse_news(since: str | None) -> list[str]:
    """Read news CSV and return list of matrix codes, optionally filtered by date."""
    if not NEWS_CSV.exists():
        log.error(f"News CSV not found: {NEWS_CSV}. Run with --refetch-news first.")
        sys.exit(1)

    df = pd.read_csv(NEWS_CSV, encoding="utf-8-sig", skiprows=1,
                     names=["Activitatea", "Data", "Domeniu", "Cod matrice",
                             "Denumire matrice", "Perioada", "Date", "Metadate", "Nomenclatoare"])

    # Drop header row if it leaked in
    df = df[df["Cod matrice"] != "Cod matrice"]
    df = df.dropna(subset=["Cod matrice"])

    if since:
        try:
            since_dt = datetime.strptime(since, "%d.%m.%Y")
            df["_date"] = pd.to_datetime(df["Data"], format="%d.%m.%Y", errors="coerce")
            df = df[df["_date"] >= since_dt]
            log.info(f"Filtered to {len(df)} entries since {since}")
        except ValueError:
            log.error(f"Invalid --since date format: {since}. Use DD.MM.YYYY")
            sys.exit(1)

    codes = df["Cod matrice"].str.strip().unique().tolist()
    log.info(f"Found {len(codes)} unique matrix codes in news")
    return codes


def fetch_meta(code: str, lang: str, force: bool) -> bool:
    """Fetch metadata for a single matrix directly from the API."""
    output_dir = BASE_DIR / "data" / "2-metas" / lang
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{code}.json"

    if not force and output_path.exists():
        log.debug(f"Meta exists, skipping: {code}")
        return True

    url = f"{META_BASE_URL}{code}?lang={lang}"
    try:
        resp = requests.get(url, headers=META_HEADERS, timeout=30)
        resp.raise_for_status()
        output_path.write_text(resp.text, encoding="utf-8")
        time.sleep(random.uniform(0.4, 1.2))
        return True
    except Exception as e:
        log.error(f"Meta fetch failed for {code}: {e}")
        return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Incremental INS TEMPO dataset update pipeline."
    )
    parser.add_argument("--fetch-context", action="store_true",
                        help="Also run scripts 1+2 (context + matrices index) first")
    parser.add_argument("--since", metavar="DD.MM.YYYY",
                        help="Only process matrices updated on/after this date")
    parser.add_argument("--matrix", metavar="CODE[,CODE,...]",
                        help="Bypass news, process specific matrix codes (comma-separated)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print steps without executing")
    parser.add_argument("--force", action="store_true",
                        help="Pass --force to downstream scripts")
    parser.add_argument("--force-meta", action="store_true",
                        help="Re-fetch metadata JSONs even if they already exist (without re-downloading CSVs/parquets — useful only for syncing dates, not actual data updates)")
    parser.add_argument("--lang", default="ro", choices=["ro", "en"],
                        help="Language (default: ro)")
    parser.add_argument("--no-split", action="store_true",
                        help="Skip 12-split-datasets.py")
    parser.add_argument("--no-view-profiles", action="store_true",
                        help="Skip generate_view_profiles.py")
    parser.add_argument("--skip-duckdb", action="store_true",
                        help="Skip scripts 4 + 10 (meta-index rebuild + DuckDB import)")
    parser.add_argument("--refetch-news", action="store_true",
                        help="Re-fetch news from INS before processing")
    parser.add_argument("--all", action="store_true",
                        help="Process all news entries, ignoring last run date")
    args = parser.parse_args()

    lang = args.lang
    force_flag = ["--force"] if args.force else []

    # ---- Setup log file ----
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    log_file = LOG_DIR / f"update-pipeline-{ts}.log"
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logging.getLogger().addHandler(file_handler)
    log.info(f"Logging to {log_file}")

    # ---- 1. Optionally re-fetch news ----
    if args.refetch_news:
        fetch_news()

    # ---- 2. Resolve matrix codes ----
    if args.matrix:
        matrix_codes = [c.strip() for c in args.matrix.split(",") if c.strip()]
        log.info(f"Using provided matrix codes: {matrix_codes}")
    else:
        since = args.since
        if not since and not args.all:
            since = read_last_run()
            if since:
                log.info(f"Auto-applying --since {since} (from last run)")
            else:
                log.info("No last run recorded — processing all news entries (use --all to suppress this warning)")
        matrix_codes = parse_news(since)

    if not matrix_codes:
        log.info("No matrices to process. Done.")
        return

    # ---- 3. Optional context + index refresh ----
    if args.fetch_context:
        log.info("=== Fetching context + matrices index ===")
        python("1-fetch-context.py", ["--lang", lang], dry_run=args.dry_run)
        python("2-fetch-matrices.py", ["--lang", lang], dry_run=args.dry_run)

    # ---- 4. Per-matrix pipeline ----
    succeeded = []
    failed = []  # list of (code, step)

    log.info(f"=== Processing {len(matrix_codes)} matrices ===")
    for i, code in enumerate(matrix_codes, 1):
        log.info(f"[{i}/{len(matrix_codes)}] {code}")
        matrix_ok = True

        # a. Fetch metadata
        if args.dry_run:
            log.info(f"[DRY-RUN] fetch_meta({code})")
        else:
            if not fetch_meta(code, lang, force=args.force or args.force_meta):
                log.warning(f"{code}: meta fetch failed, continuing anyway")

        # b. Fetch CSV
        if not python("6-fetch-csv.py", ["--matrix", code, "--lang", lang] + force_flag, dry_run=args.dry_run):
            failed.append((code, "6-fetch-csv"))
            matrix_ok = False

        # c. Compact data
        # if matrix_ok:
        #     if not python("7-data-compactor.py", ["--matrix", code, "--lang", lang], dry_run=args.dry_run):
        #         failed.append((code, "7-compact"))
        #         matrix_ok = False

        # d. CSV → parquet-v2
        if matrix_ok:
            if not python("9-csv-to-parquet.py", ["--matrix", code] + force_flag, dry_run=args.dry_run):
                failed.append((code, "9-csv-to-parquet"))
                matrix_ok = False

        # e. parquet-v2 → SDMX parquet
        if matrix_ok:
            if not python("12-parquet-to-sdmx.py", ["--matrix", code] + force_flag, dry_run=args.dry_run):
                failed.append((code, "12-parquet-to-sdmx"))
                matrix_ok = False

        # f. Split datasets
        if matrix_ok and not args.no_split:
            if not python("12-split-datasets.py", ["--matrix", code], dry_run=args.dry_run):
                failed.append((code, "12-split"))
                matrix_ok = False

        # g. View profiles
        if matrix_ok and not args.no_view_profiles:
            if not python("generate_view_profiles.py", ["--matrix", code], dry_run=args.dry_run):
                log.warning(f"{code}: view profile generation failed (non-fatal)")

        if matrix_ok:
            succeeded.append(code)

    # ---- 5. Full DuckDB rebuild ----
    if not args.skip_duckdb:
        log.info("=== Rebuilding meta index + DuckDB ===")
        python("4-build-meta-index.py", ["--lang", lang], dry_run=args.dry_run)
        python("10-import-metadata.py", [], dry_run=args.dry_run)  # may fail (lang schema issue — see backlog)
        sync_ultima_actualizare(succeeded, lang, dry_run=args.dry_run)

    # ---- 6. Summary ----
    log.info("=" * 50)
    log.info(f"Done. Processed: {len(matrix_codes)}  |  OK: {len(succeeded)}  |  Failed: {len(failed)}")
    if failed:
        log.warning("Failed matrices:")
        for code, step in failed:
            log.warning(f"  {code} (step: {step})")
    else:
        log.info("All matrices processed successfully.")

    # Record last run date so next run auto-applies --since
    if not args.dry_run and not args.matrix:
        write_last_run()
        log.info(f"Last run date saved ({datetime.now().strftime('%d.%m.%Y')})")

    log.info(f"Log written to {log_file}")


if __name__ == "__main__":
    main()
