#!/usr/bin/env python3
"""
Incremental dataset update orchestrator.

Reads the INS TEMPO news page (data/insse_news.csv) to get updated matrix codes,
then runs the pipeline for only those matrices. Every matrix processed here was
either named explicitly (--matrix), flagged by INS as changed (news feed) or owed
from a previous failed run (retry set), so by default it is force-refreshed.

Stage order per changed matrix (FIX-03 phase 2a; each return code is checked and a
failure stops that matrix, later matrices still run)
    meta fetch -> 6-fetch-csv -> 10-import-metadata --matrix -> 10-classify-dimensions
    --matrix -> 11-build-sdmx-codes --matrix -> 9-csv-to-parquet -> 12-split-datasets
    --matrix (children replaced as an atomic set) -> 10-import-metadata --stats-only
    -> [13-dimension-structure, generate_view_profiles: parent + children] -> validate
    Run level afterwards: 4-build-meta-index, date sync, then (--global-profiles only)
    11-coverage-profiler, detect_trends, profile-values, search index. Without that
    flag the touched matrices are recorded under "stale" in the state file.
    The DB refresh runs before conversion because stage 9 resolves labels and column
    names through the DB maps.

Success semantics (FIX-03 phase 1)
    Required stages: metadata fetch, 6-fetch-csv, 10-import-metadata, 10-classify-
    dimensions, 11-build-sdmx-codes, 9-csv-to-parquet, 12-split (unless --no-split),
    the stats refresh, validation, and the run-level 4-build-meta-index / date sync.
    Any required failure => exit 1, matrix goes to the persisted
    retry set, the watermark is NOT advanced. Optional stages (13-dimension-
    structure, generate_view_profiles, --global-profiles) are recorded and printed but
    do not block (--strict makes them exit 1). An empty dataset at source (6-fetch-csv
    exit 3) is recorded as "empty": not a failure, not retried. Exit 2 = usage/unsafe
    mode. Nothing is deleted on failure; earlier artifacts stay in place.

State: data/logs/update-pipeline-state.json (--state-file): watermark, retry set,
per-matrix/per-stage outcome + reason + source update date. The watermark is the
newest feed date of a fully successful feed run (never wall-clock today); it is
inclusive, so the latest day is re-fetched next time (several updates may share
one date). Retry matrices are merged into every feed/--all run.

Modes
    (default)        feed entries since the watermark (all, if none) + retry set
    --since D        feed entries dated >= D + retry set; never lowers the watermark
    --all            whole feed + retry set
    --matrix A,B     exactly these codes; retry set and watermark untouched by the
                     selection (their own state/retry entries are updated)
    --skip-existing, --no-split, --skip-duckdb   partial runs: never advance watermark
    --global-profiles  also rebuild coverage/trends/value profiles/search index (optional)
    --dry-run        no subprocess, fetch, DB, log, state or watermark writes
    --lang           only 'ro'; 'en' is rejected (would clobber canonical output)

Usage:
    python update-pipeline.py                          # feed since watermark + retries
    python update-pipeline.py --since 06.04.2026       # only entries from this date
    python update-pipeline.py --matrix TMI1163         # specific matrix, bypass news
    python update-pipeline.py --matrix A,B --dry-run   # preview without running
    python update-pipeline.py --refetch-news --since 06.04.2026  # re-fetch news first
    python update-pipeline.py --fetch-context          # also refresh context + matrices index
    python update-pipeline.py --skip-existing          # resume/debug: skip matrices already fetched
"""

import argparse
import json
import logging
import os
import random
import re
import subprocess
import sys
import time
from datetime import date, datetime
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
LAST_RUN_FILE = LOG_DIR / "last-pipeline-run.txt"   # legacy mirror of the watermark
STATE_FILE = LOG_DIR / "update-pipeline-state.json"  # outcomes, retry set, watermark

# INS matrix codes are short alphanumeric tokens (e.g. INT113D, PPI1035).
# The news page occasionally emits a summary/footer row (e.g. "113 Matrice" —
# Romanian for "113 matrices") in the "Cod matrice" cell instead of a real code;
# that garbage then permanently corrupts data/2-metas via fetch_meta(). Filter it out.
MATRIX_CODE_RE = re.compile(r"^[A-Z0-9]{4,10}$")

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
                synced = datetime.strptime(raw.strip(), "%d-%m-%Y").date()
                conn.execute(
                    "UPDATE matrices SET ultima_actualizare = ? WHERE matrix_code = ?",
                    [synced, code]
                )
                updated += 1
            except Exception as e:
                log.warning(f"  {code}: could not sync date — {e}")
    finally:
        conn.close()

    log.info(f"Synced ultima_actualizare for {updated}/{len(codes)} matrices")

    # Propagate dates (and text metadata) from parents to split children
    if updated > 0:
        propagate_split_metadata(db_path, dry_run=False)

    return updated


def propagate_split_metadata(db_path, dry_run: bool = False) -> int:
    """Copy ultima_actualizare, definitie, metodologie, observatii from parent to split children."""
    if dry_run:
        log.info("[DRY-RUN] propagate_split_metadata skipped")
        return 0

    conn = duckdb.connect(str(db_path))
    try:
        conn.execute("""
            UPDATE matrices
            SET ultima_actualizare = (
                SELECT parent.ultima_actualizare
                FROM dataset_splits ds
                JOIN matrices parent ON ds.parent_matrix_code = parent.matrix_code
                WHERE ds.sub_matrix_code = matrices.matrix_code
                  AND parent.ultima_actualizare IS NOT NULL
                LIMIT 1
            )
            WHERE matrix_code IN (SELECT sub_matrix_code FROM dataset_splits)
            AND ultima_actualizare IS NULL
        """)
        conn.execute("""
            UPDATE matrices
            SET definitie = sub.definitie,
                metodologie = sub.metodologie,
                observatii = sub.observatii
            FROM (
                SELECT ds.sub_matrix_code, parent.definitie, parent.metodologie, parent.observatii
                FROM dataset_splits ds
                JOIN matrices parent ON ds.parent_matrix_code = parent.matrix_code
            ) sub
            WHERE matrices.matrix_code = sub.sub_matrix_code
            AND matrices.definitie IS NULL
        """)
        r = conn.execute(
            "SELECT COUNT(*) FROM matrices WHERE is_canonical = TRUE AND ultima_actualizare >= '2026-01-01'"
        ).fetchone()
        log.info(f"Split metadata propagated — canonical 2026 datasets: {r[0]}")
        return r[0]
    except Exception as e:
        log.warning(f"propagate_split_metadata error: {e}")
        return 0
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Outcome / retry state (FIX-03)
# ---------------------------------------------------------------------------
DATE_FMT = "%d.%m.%Y"
STATE_VERSION = 1
EXIT_OK, EXIT_FAILED, EXIT_USAGE = 0, 1, 2
EXIT_CSV_EMPTY = 3  # 6-fetch-csv.py: INS returned a header-only CSV (not retryable)

# Per-matrix stage keys, in run order (FIX-03 phase 2a). Required failures -> matrix
# recorded as failed, retried next run, exit != 0, watermark frozen; later stages are
# skipped. Optional failures are recorded + printed but do not block.
#
#   meta -> 6-fetch-csv -> 10-import-metadata -> 10-classify-dimensions
#        -> 11-build-sdmx-codes -> 9-csv-to-parquet -> 12-split -> 10-import-stats
#        -> [13-dimension-structure, generate_view_profiles for parent + children]
#        -> validate
#
# Import/classify/codes come BEFORE conversion because stage 9 resolves every label and
# column name through the DB (dimension options, sdmx_codes, sdmx_column_map); a
# refreshed dataset converted against stale maps would keep stale labels.
STAGE_META = "meta"
STAGE_CSV = "6-fetch-csv"
STAGE_IMPORT = "10-import-metadata"
STAGE_CLASSIFY = "10-classify-dimensions"
STAGE_CODES = "11-build-sdmx-codes"
STAGE_CONVERT = "9-csv-to-parquet"
STAGE_SPLIT = "12-split"
STAGE_STATS = "10-import-stats"
STAGE_DIMS = "13-dimension-structure"
STAGE_VIEWS = "generate_view_profiles"
STAGE_VALIDATE = "validate"
OPTIONAL_STAGES = {STAGE_DIMS, STAGE_VIEWS}
# DB-refresh stages that --skip-duckdb leaves out (partial run).
DB_STAGES = (STAGE_IMPORT, STAGE_CLASSIFY, STAGE_CODES)
# Run-level (batch) stages, all required.
BATCH_INDEX = "4-build-meta-index"
BATCH_SYNC = "sync-ultima-actualizare"
# Run-level optional stages (--global-profiles): scripts that rebuild whole tables and
# have no per-matrix mode. Without the flag the touched matrices are recorded as stale.
GLOBAL_PROFILE_STAGES = (
    ("coverage", "11-coverage-profiler.py", []),
    ("trends", "detect_trends.py", []),
    ("value_profiles", "scripts/profile-values.py", []),
    ("search_index", "scripts/build-search-index.py", []),
)


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def parse_date(raw) -> date | None:
    try:
        return datetime.strptime(str(raw).strip(), DATE_FMT).date()
    except (ValueError, TypeError):
        return None


def fmt_date(d: date) -> str:
    return d.strftime(DATE_FMT)


class PipelineState:
    """Small JSON checkpoint: watermark, retry set, per-matrix/per-stage outcomes.

    Layout (version 1)::

        {"version": 1,
         "watermark": "DD.MM.YYYY" | null,     # max feed date of fully handled runs
         "retry": {CODE: {"stage", "reason", "source_update", "attempts",
                          "first_failed", "last_failed"}},
         "matrices": {CODE: {"source_update", "outcome", "updated_at",
                             "stages": {STAGE: {"outcome", "reason", "at"}}}},
         "stale": {"coverage"|"trends"|"value_profiles"|"search_index": [CODE, ...]},
         "last_run": {"started", "finished", "exit_code", "processed", "failed", ...}}

    Stage outcomes: ok | failed | empty | skipped. Writes are atomic (tmp + rename).
    """

    def __init__(self, path: Path):
        self.path = Path(path)
        self.data = {"version": STATE_VERSION, "watermark": None,
                     "retry": {}, "matrices": {}, "last_run": {}}
        if self.path.exists():
            try:
                loaded = json.loads(self.path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as e:
                # Never silently reset: that would drop the retry set.
                raise RuntimeError(f"Corrupt pipeline state {self.path}: {e}") from e
            self.data.update(loaded)

    @property
    def watermark(self) -> str | None:
        return self.data.get("watermark")

    @property
    def retry(self) -> dict:
        return self.data["retry"]

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(self.data, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(tmp, self.path)

    def record_matrix(self, code: str, outcome: str, stages: dict, source_update: str | None) -> None:
        self.data["matrices"][code] = {
            "source_update": source_update, "outcome": outcome,
            "updated_at": now_iso(), "stages": stages,
        }

    def add_retry(self, code: str, stage: str, reason: str, source_update: str | None) -> None:
        prev = self.retry.get(code, {})
        self.retry[code] = {
            "stage": stage, "reason": reason,
            "source_update": source_update or prev.get("source_update"),
            "attempts": int(prev.get("attempts", 0)) + 1,
            "first_failed": prev.get("first_failed", now_iso()),
            "last_failed": now_iso(),
        }

    def clear_retry(self, code: str) -> None:
        self.retry.pop(code, None)


# ---------------------------------------------------------------------------
# Language safety
# ---------------------------------------------------------------------------
def enforce_language(lang: str) -> None:
    """Refuse unsafe language modes (exit 2).

    Processing stages (9/11/12/13/profiles) write *shared canonical* outputs
    (data/corpus/parquet, metadata.duckdb) and take their inputs from TEMPO_LANG
    paths that this orchestrator cannot point at --lang. Running them over an
    English fetch would either convert stale Romanian CSVs or overwrite Romanian
    canonical data. English enrichment-only ingestion is not implemented, so it is
    rejected rather than half-supported (FIX-03 item 6).
    """
    env_lang = os.environ.get("TEMPO_LANG")
    if lang != "ro" or env_lang not in (None, "", "ro"):
        log.error("Only Romanian ('ro') is supported by update-pipeline.py. "
                  f"Got --lang={lang!r}, TEMPO_LANG={env_lang!r}. English label ingestion "
                  "must not overwrite canonical Romanian output and has no enrichment-only "
                  "mode yet; use the per-language fetch scripts (1-6 --lang en) directly.")
        raise SystemExit(EXIT_USAGE)


def child_env() -> dict:
    """Explicit language at every subprocess boundary."""
    env = dict(os.environ)
    env["TEMPO_LANG"] = "ro"
    return env


# ---------------------------------------------------------------------------
# Subprocess helpers
# ---------------------------------------------------------------------------
def run_cmd(cmd: list[str], dry_run: bool = False, label: str = "") -> int:
    """Run a subprocess and return its exit code (0 in dry-run)."""
    display = " ".join(cmd)
    if dry_run:
        log.info(f"[DRY-RUN] {label or display}")
        return 0
    log.info(f"Running: {display}")
    result = subprocess.run(cmd, cwd=BASE_DIR, env=child_env())
    if result.returncode != 0:
        log.error(f"FAILED (exit {result.returncode}): {display}")
    return result.returncode


def run(cmd: list[str], dry_run: bool = False, label: str = "") -> bool:
    """Run a subprocess. Returns True on success."""
    return run_cmd(cmd, dry_run=dry_run, label=label) == 0


def python_rc(script: str, args: list[str], dry_run: bool = False) -> int:
    return run_cmd([sys.executable, script] + args, dry_run=dry_run,
                   label=f"{script} {' '.join(args)}")


def python(script: str, args: list[str], dry_run: bool = False) -> bool:
    return python_rc(script, args, dry_run=dry_run) == 0


def read_last_run() -> str | None:
    """Legacy watermark file (DD.MM.YYYY); the state file takes precedence."""
    if LAST_RUN_FILE.exists():
        return LAST_RUN_FILE.read_text().strip() or None
    return None


def write_last_run(day: str) -> None:
    """Record the watermark (a feed date, never wall-clock today) for legacy readers."""
    LAST_RUN_FILE.parent.mkdir(parents=True, exist_ok=True)
    LAST_RUN_FILE.write_text(day)


def fetch_news() -> bool:
    log.info(f"Fetching news from {NEWS_URL}...")
    try:
        resp = requests.get(NEWS_URL, headers=NEWS_HEADERS, timeout=20)
        resp.raise_for_status()
        tables = pd.read_html(resp.text, flavor="bs4")
        if not tables:
            log.error("No tables found in news page")
            return False
        df = tables[0]
        NEWS_CSV.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(NEWS_CSV, index=False, encoding="utf-8-sig")
        log.info(f"Saved {len(df)} rows to {NEWS_CSV}")
        return True
    except Exception as e:
        log.error(f"Failed to fetch news: {e}")
        return False


def parse_news(since: str | None) -> dict[str, str | None]:
    """Read the news CSV -> {matrix code: latest feed date (DD.MM.YYYY) or None}.

    A matrix with several updates in the window maps to its newest date.
    `since` is inclusive.
    """
    if not NEWS_CSV.exists():
        log.error(f"News CSV not found: {NEWS_CSV}. Run with --refetch-news first.")
        sys.exit(EXIT_USAGE)

    df = pd.read_csv(NEWS_CSV, encoding="utf-8-sig", skiprows=1,
                     names=["Activitatea", "Data", "Domeniu", "Cod matrice",
                            "Denumire matrice", "Perioada", "Date", "Metadate", "Nomenclatoare"])

    # Drop header row if it leaked in
    df = df[df["Cod matrice"] != "Cod matrice"]
    df = df.dropna(subset=["Cod matrice"])
    df["_date"] = pd.to_datetime(df["Data"], format=DATE_FMT, errors="coerce")

    if since:
        since_dt = parse_date(since)
        if since_dt is None:
            log.error(f"Invalid --since date format: {since}. Use DD.MM.YYYY")
            sys.exit(EXIT_USAGE)
        df = df[df["_date"] >= pd.Timestamp(since_dt)]
        log.info(f"Filtered to {len(df)} entries since {since}")

    df = df.assign(_code=df["Cod matrice"].astype(str).str.strip())
    result: dict[str, str | None] = {}
    skipped = []
    for code, grp in df.groupby("_code", sort=False):
        if not MATRIX_CODE_RE.match(code):
            skipped.append(code)
            continue
        latest = grp["_date"].max()
        result[code] = None if pd.isna(latest) else latest.strftime(DATE_FMT)
    if skipped:
        log.warning(f"Skipped {len(skipped)} non-matrix-code rows from news: {skipped}")
    log.info(f"Found {len(result)} unique matrix codes in news")
    return result


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
        json.loads(resp.text)  # validate before writing — a bad code can 200 with an empty/non-JSON body
        output_path.write_text(resp.text, encoding="utf-8")
        time.sleep(random.uniform(0.4, 1.2))
        return True
    except Exception as e:
        log.error(f"Meta fetch failed for {code}: {e}")
        return False


# ---------------------------------------------------------------------------
# Per-matrix pipeline
# ---------------------------------------------------------------------------
def _stage(stages: dict, name: str, outcome: str, reason: str | None = None) -> None:
    stages[name] = {"outcome": outcome, "reason": reason, "at": now_iso()}


def corpus_db_path() -> Path:
    return BASE_DIR / "data" / "corpus" / "metadata.duckdb"


CHILDREN_SEEN: dict[str, list[str]] = {}   # parent -> children profiled this run


def fetch_children(code: str) -> list[str]:
    """Registered split children of a parent (read-only DB lookup; [] when unavailable)."""
    db = corpus_db_path()
    if not db.exists():
        return []
    conn = duckdb.connect(str(db), read_only=True)
    try:
        return [r[0] for r in conn.execute(
            "SELECT sub_matrix_code FROM dataset_splits WHERE parent_matrix_code = ? "
            "ORDER BY sub_matrix_code", [code]).fetchall()]
    except Exception as e:
        log.warning(f"{code}: could not read children ({e})")
        return []
    finally:
        conn.close()


def validate_matrix(code: str, children: list[str], check_split: bool = True) -> str | None:
    """Final required check before a matrix is checkpointed. None when consistent, else
    the reason. Parent: parquet readable and non-empty, DB row_count equals the file,
    dimensions registered. Children (when splitting ran): registered in dataset_splits
    and matrices, file present with the registered row count."""
    db = corpus_db_path()
    pq_dir = BASE_DIR / "data" / "corpus" / "parquet"
    conn = duckdb.connect(str(db), read_only=True)
    try:
        def rows_of(path: Path):
            return conn.execute(f"SELECT COUNT(*) FROM read_parquet('{path}')").fetchone()[0]

        parent_pq = pq_dir / f"{code}.parquet"
        if not parent_pq.exists():
            return f"parent parquet missing: {parent_pq.name}"
        try:
            n = rows_of(parent_pq)
        except Exception as e:
            return f"parent parquet unreadable: {e}"
        if n <= 0:
            return "parent parquet has no rows"
        m = conn.execute("SELECT row_count FROM matrices WHERE matrix_code = ?", [code]).fetchone()
        if m is None:
            return "parent not registered in matrices"
        if m[0] != n:
            return f"matrices.row_count {m[0]} != parquet rows {n}"
        if conn.execute("SELECT COUNT(*) FROM dimensions WHERE matrix_code = ?",
                        [code]).fetchone()[0] == 0:
            return "parent has no dimensions"
        if check_split:
            reg = conn.execute(
                "SELECT sub_matrix_code, row_count, parquet_path FROM dataset_splits "
                "WHERE parent_matrix_code = ?", [code]).fetchall()
            if sorted(r[0] for r in reg) != sorted(children):
                return "dataset_splits does not match the child set"
            for sub, cnt, path in reg:
                f = Path(path) if path else pq_dir / f"{sub}.parquet"
                if not f.exists():
                    return f"child parquet missing: {sub}"
                try:
                    got = rows_of(f)
                except Exception as e:
                    return f"child parquet unreadable: {sub}: {e}"
                if got != cnt:
                    return f"child {sub} rows {got} != registered {cnt}"
                if not conn.execute(
                        "SELECT 1 FROM matrices WHERE matrix_code = ? AND is_split", [sub]).fetchone():
                    return f"child {sub} not registered in matrices"
    finally:
        conn.close()
    return None


def process_matrix(code: str, args, lang: str) -> tuple[str, dict, tuple[str, str] | None]:
    """Run all per-matrix stages in dependency order (see the stage list above).

    Returns (outcome, stages, first_required_failure); outcome: ok | ok_degraded
    (optional stage failed) | empty | failed. Every prerequisite's return code is
    checked and a failure stops the matrix right there. Nothing is ever deleted
    here: on failure earlier artifacts stay in place.
    """
    dry = args.dry_run
    force_flag = [] if args.skip_existing else ["--force"]
    meta_force = args.force_meta or not args.skip_existing
    stages: dict = {}
    ok_or_dry = ("skipped", "dry-run") if dry else ("ok", None)

    def required(key: str, script: str, script_args: list[str]) -> tuple[str, str] | None:
        rc = python_rc(script, script_args, dry_run=dry)
        if rc != 0:
            reason = f"{script} exit {rc}"
            _stage(stages, key, "failed", reason)
            return key, reason
        _stage(stages, key, *ok_or_dry)
        return None

    def fail(f):
        return "failed", stages, f

    # 1. metadata (required)
    if dry:
        log.info(f"[DRY-RUN] fetch_meta({code})")
        _stage(stages, STAGE_META, "skipped", "dry-run")
    elif fetch_meta(code, lang, force=meta_force):
        _stage(stages, STAGE_META, "ok")
    else:
        _stage(stages, STAGE_META, "failed", "metadata fetch failed")
        return fail((STAGE_META, "metadata fetch failed"))

    # 2. CSV (required; exit 3 = INS answered with no data rows)
    rc = python_rc("6-fetch-csv.py", ["--matrix", code, "--lang", lang] + force_flag, dry_run=dry)
    if rc == EXIT_CSV_EMPTY:
        _stage(stages, STAGE_CSV, "empty", "INS returned no data rows")
        log.warning(f"{code}: empty dataset at source; import/convert/split/profile skipped")
        return "empty", stages, None
    if rc != 0:
        reason = f"6-fetch-csv exit {rc}"
        _stage(stages, STAGE_CSV, "failed", reason)
        return fail((STAGE_CSV, reason))
    _stage(stages, STAGE_CSV, *ok_or_dry)

    # 3-5. DB refresh for this matrix only: reconcile metadata/options, classify them,
    # rebuild its code maps (required; --skip-duckdb leaves them out: partial run)
    for key, script, script_args in (
        (STAGE_IMPORT, "10-import-metadata.py", ["--matrix", code]),
        (STAGE_CLASSIFY, "10-classify-dimensions.py", ["--matrix", code]),
        (STAGE_CODES, "11-build-sdmx-codes.py", ["--matrix", code]),
    ):
        if args.skip_duckdb:
            _stage(stages, key, "skipped", "--skip-duckdb")
            continue
        f = required(key, script, script_args)
        if f:
            return fail(f)

    # 6. CSV -> canonical SDMX parquet against the refreshed maps (required)
    f = required(STAGE_CONVERT, "9-csv-to-parquet.py", ["--matrix", code] + force_flag)
    if f:
        return fail(f)

    # 7. split + register children as one set (required when enabled)
    if not args.no_split:
        f = required(STAGE_SPLIT, "12-split-datasets.py", ["--matrix", code])
        if f:
            return fail(f)
    else:
        _stage(stages, STAGE_SPLIT, "skipped", "--no-split")

    # 8. row_count/size/path of the new parquet (the import above saw the old file)
    if args.skip_duckdb:
        _stage(stages, STAGE_STATS, "skipped", "--skip-duckdb")
    else:
        f = required(STAGE_STATS, "10-import-metadata.py", ["--matrix", code, "--stats-only"])
        if f:
            return fail(f)

    # 9. optional profiling of the parent and its children: visible, never blocking
    children = [] if (dry or args.no_split) else fetch_children(code)
    CHILDREN_SEEN[code] = children
    targets = [code] + children
    degraded = False
    for key, disabled, flag in ((STAGE_DIMS, args.no_dim_structure, "--no-dim-structure"),
                                (STAGE_VIEWS, args.no_view_profiles, "--no-view-profiles")):
        if disabled:
            _stage(stages, key, "skipped", flag)
            continue
        if key == STAGE_DIMS:
            runs = [("13-dimension-structure.py", ["--matrix", ",".join(targets)])]
        else:
            runs = [("generate_view_profiles.py", ["--matrix", t]) for t in targets]
        bad = []
        for script, script_args in runs:
            rc = python_rc(script, script_args, dry_run=dry)
            if rc != 0:
                bad.append(f"{script} {' '.join(script_args)} exit {rc}")
        if bad:
            _stage(stages, key, "failed", "; ".join(bad))
            log.warning(f"{code}: {key} failed (optional; derived features for this matrix "
                        "are not verified)")
            degraded = True
        else:
            _stage(stages, key, *ok_or_dry)

    # 10. validate the artifacts (required) before the matrix may be checkpointed
    if dry:
        _stage(stages, STAGE_VALIDATE, "skipped", "dry-run")
    elif args.skip_duckdb:
        _stage(stages, STAGE_VALIDATE, "skipped", "--skip-duckdb")
    else:
        try:
            reason = validate_matrix(code, children, check_split=not args.no_split)
        except Exception as e:  # unreadable DB etc. is a validation failure, not a crash
            reason = f"validation error: {e}"
        if reason:
            log.error(f"{code}: validation failed: {reason}")
            _stage(stages, STAGE_VALIDATE, "failed", reason)
            return fail((STAGE_VALIDATE, reason))
        _stage(stages, STAGE_VALIDATE, "ok")

    return ("ok_degraded" if degraded else "ok"), stages, None


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Incremental INS TEMPO dataset update pipeline.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--fetch-context", action="store_true",
                        help="Also run scripts 1+2 (context + matrices index) first; failure aborts the run")
    parser.add_argument("--since", metavar="DD.MM.YYYY",
                        help="Only feed entries dated on/after this (inclusive). Overrides the stored watermark; never lowers it")
    parser.add_argument("--matrix", metavar="CODE[,CODE,...]",
                        help="Bypass the feed and retry set; process exactly these codes. Updates per-matrix state "
                             "and retry entries for them but never moves the watermark")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print the plan only: no subprocess, fetch, DB write, state/log file or watermark change")
    parser.add_argument("--skip-existing", action="store_true",
                        help="Resume/debug mode: skip a matrix's fetch/convert steps if local files already exist. "
                             "Results are not verified fresh, so this never advances the watermark")
    parser.add_argument("--force-meta", action="store_true",
                        help="With --skip-existing, still re-fetch metadata JSONs even though CSV/parquet steps are skipped")
    parser.add_argument("--lang", default="ro",
                        help="Only 'ro' is supported; 'en' is rejected (no enrichment-only mode, would clobber canonical data)")
    parser.add_argument("--no-split", action="store_true", help="Skip 12-split-datasets.py (partial run: no watermark advance)")
    parser.add_argument("--no-view-profiles", action="store_true", help="Skip generate_view_profiles.py")
    parser.add_argument("--no-dim-structure", action="store_true", help="Skip 13-dimension-structure.py")
    parser.add_argument("--skip-duckdb", action="store_true",
                        help="Skip the DB refresh stages (4 meta index, 10 import/classify, 11 code maps, "
                             "stats refresh, validation); partial run: no watermark advance")
    parser.add_argument("--global-profiles", action="store_true",
                        help="After the run, rebuild the whole-corpus profiles that have no per-matrix mode "
                             "(11-coverage-profiler, detect_trends, profile-values, search index). Optional "
                             "stages. Without it the touched matrices are recorded as stale in the state file")
    parser.add_argument("--refetch-news", action="store_true", help="Re-fetch news from INS before processing")
    parser.add_argument("--all", action="store_true",
                        help="Process every feed entry, ignoring the watermark (retries are merged too)")
    parser.add_argument("--strict", action="store_true",
                        help="Also exit nonzero when an optional (profiling) stage failed")
    parser.add_argument("--state-file", metavar="PATH", default=None,
                        help=f"Checkpoint JSON (default: {STATE_FILE})")
    parser.add_argument("--propagate-splits", action="store_true",
                        help="Propagate parent metadata (ultima_actualizare, definitie, etc.) to split children, then exit")
    return parser


def run_pipeline(argv: list[str] | None = None) -> int:
    """Run the orchestrator. Returns the process exit code (0 ok, 1 required failure, 2 usage)."""
    args = build_parser().parse_args(argv)
    lang = args.lang
    enforce_language(lang)
    if args.matrix and (args.since or args.all):
        log.error("--matrix cannot be combined with --since/--all")
        return EXIT_USAGE
    if args.since and parse_date(args.since) is None:
        log.error(f"Invalid --since date format: {args.since}. Use DD.MM.YYYY")
        return EXIT_USAGE
    if args.since and args.all:
        log.error("--since and --all are mutually exclusive")
        return EXIT_USAGE

    dry = args.dry_run
    started = now_iso()
    CHILDREN_SEEN.clear()
    handler = None
    if not dry:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        log_file = LOG_DIR / f"update-pipeline-{datetime.now().strftime('%Y%m%d-%H%M%S')}.log"
        handler = logging.FileHandler(log_file, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
        logging.getLogger().addHandler(handler)
        log.info(f"Logging to {log_file}")

    try:
        return _run_pipeline(args, lang, started, dry)
    finally:
        if handler is not None:
            logging.getLogger().removeHandler(handler)
            handler.close()


def _run_pipeline(args, lang: str, started: str, dry: bool) -> int:
    state_path = Path(args.state_file) if args.state_file else STATE_FILE
    try:
        state = PipelineState(state_path)
    except RuntimeError as e:
        log.error(str(e))
        return EXIT_FAILED

    # ---- 0. Standalone propagate-splits shortcut ----
    if args.propagate_splits:
        propagate_split_metadata(BASE_DIR / "data" / "corpus" / "metadata.duckdb", dry_run=dry)
        return EXIT_OK

    # ---- 1. Optionally re-fetch news ----
    if args.refetch_news:
        if dry:
            log.info("[DRY-RUN] fetch_news()")
        elif not fetch_news():
            log.error("News refresh failed; aborting (watermark and retry set untouched)")
            return EXIT_FAILED

    # ---- 2. Resolve work list: {code: feed date} ----
    feed_dates: dict[str, str | None] = {}
    if args.matrix:
        work = {c.strip(): None for c in args.matrix.split(",") if c.strip()}
        log.info(f"Using provided matrix codes: {list(work)}")
    else:
        since = args.since
        if not since and not args.all:
            since = state.watermark or read_last_run()
            if since:
                log.info(f"Auto-applying --since {since} (stored watermark)")
            else:
                log.info("No watermark recorded — processing all news entries")
        feed_dates = parse_news(since)
        work = dict(feed_dates)
        merged = [c for c in state.retry if c not in work]
        for c in merged:
            work[c] = state.retry[c].get("source_update")
        if merged:
            log.info(f"Merged {len(merged)} retry matrices from previous failed runs: {merged}")

    if not work:
        log.info("No matrices to process. Done.")
        return EXIT_OK

    # ---- 3. Optional context + index refresh (prerequisite: abort on failure) ----
    if args.fetch_context:
        log.info("=== Fetching context + matrices index ===")
        for script in ("1-fetch-context.py", "2-fetch-matrices.py"):
            if python_rc(script, ["--lang", lang], dry_run=dry) != 0:
                log.error(f"{script} failed; aborting before touching any matrix "
                          "(watermark and retry set untouched)")
                return EXIT_FAILED

    # ---- 4. Per-matrix pipeline ----
    results: dict[str, str] = {}
    failures: list[tuple[str, str, str]] = []   # required: (code, stage, reason)
    degraded: list[tuple[str, str, str]] = []   # optional stage failures
    empties: list[str] = []
    log.info(f"=== Processing {len(work)} matrices ===")
    for i, (code, src_date) in enumerate(work.items(), 1):
        log.info(f"[{i}/{len(work)}] {code}")
        outcome, stages, fail = process_matrix(code, args, lang)
        results[code] = outcome
        if dry:
            continue
        state.record_matrix(code, outcome, stages, src_date)
        if fail:
            failures.append((code, fail[0], fail[1]))
            state.add_retry(code, fail[0], fail[1], src_date)
        for key, st in stages.items():
            if st["outcome"] == "failed" and key in OPTIONAL_STAGES:
                degraded.append((code, key, st["reason"]))
        if outcome == "empty":
            empties.append(code)
        state.save()  # crash-safe: retry entries are durable before the next matrix

    handled = [c for c, o in results.items() if o in ("ok", "ok_degraded", "empty")]

    # ---- 5. Batch stage: meta index + date sync (required) ----
    # The per-matrix DB refresh (import/classify/code maps/stats) already ran inside
    # process_matrix, ahead of conversion.
    batch_failures: list[tuple[str, str]] = []
    if not args.skip_duckdb:
        log.info("=== Rebuilding meta index ===")
        rc = python_rc("4-build-meta-index.py", ["--lang", lang], dry_run=dry)
        if rc != 0:
            batch_failures.append((BATCH_INDEX, f"4-build-meta-index.py exit {rc}"))
        else:
            try:
                sync_ultima_actualizare(handled, lang, dry_run=dry)
            except Exception as e:
                log.error(f"sync_ultima_actualizare failed: {e}")
                batch_failures.append((BATCH_SYNC, str(e)))
    else:
        log.info("--skip-duckdb: DB refresh stages skipped (partial run)")

    if batch_failures and not dry:
        # The index/sync are global: every matrix handled this run lacks them.
        key, reason = batch_failures[0]
        for code in handled:
            failures.append((code, key, reason))
            state.add_retry(code, key, reason, work.get(code))
            rec = state.data["matrices"][code]
            rec["outcome"] = "failed"
            rec["stages"][key] = {"outcome": "failed", "reason": reason, "at": now_iso()}
    elif batch_failures:
        failures.extend(("(batch)", k, r) for k, r in batch_failures)

    # ---- 5b. Whole-corpus profiles with no per-matrix mode (optional) ----
    if not dry:
        touched = sorted({c for c in handled if results.get(c) in ("ok", "ok_degraded")}
                         | {k for c in handled for k in CHILDREN_SEEN.get(c, [])})
        stale = state.data.setdefault("stale", {})
        for key, _, _ in GLOBAL_PROFILE_STAGES:
            stale[key] = sorted(set(stale.get(key, [])) | set(touched))
        if args.global_profiles:
            log.info("=== Whole-corpus profiles (optional) ===")
            for key, script, script_args in GLOBAL_PROFILE_STAGES:
                rc = python_rc(script, script_args)
                if rc != 0:
                    degraded.append(("(batch)", key, f"{script} exit {rc}"))
                else:
                    stale[key] = []
        state.save()

    required_failed = bool(failures)

    # ---- 6. Retry bookkeeping + watermark ----
    advanced = False
    partial = args.skip_existing or args.no_split or args.skip_duckdb
    if not dry and not batch_failures:
        for code in handled:  # fully handled: no longer owed a retry
            state.clear_retry(code)
    if not dry and not required_failed:
        feed_max = [d for d in (parse_date(v) for v in feed_dates.values()) if d]
        old = parse_date(state.watermark or read_last_run())
        if feed_max and not args.matrix and not partial:
            new_wm = fmt_date(max(feed_max + ([old] if old else [])))
            advanced = new_wm != state.watermark
            state.data["watermark"] = new_wm
            write_last_run(new_wm)
        elif partial and not args.matrix:
            log.warning("Partial run (--skip-existing/--no-split/--skip-duckdb): watermark not advanced")

    exit_code = EXIT_FAILED if required_failed else EXIT_OK
    if degraded and args.strict and exit_code == EXIT_OK:
        exit_code = EXIT_FAILED

    failed_codes = sorted({c for c, _, _ in failures})
    if not dry:
        state.data["last_run"] = {
            "started": started, "finished": now_iso(), "exit_code": exit_code,
            "processed": len(work), "failed": failed_codes, "empty": empties,
            "optional_failed": sorted({c for c, _, _ in degraded}),
            "watermark": state.watermark,
        }
        state.save()

    # ---- 7. Summary ----
    log.info("=" * 50)
    log.info(f"Done{' (dry-run)' if dry else ''}. Processed: {len(work)}  |  "
             f"Handled: {len(handled)}  |  Failed: {len(failed_codes)}")
    for code, stage, reason in failures:
        log.error(f"  FAILED {code} (stage: {stage}) — {reason}")
    for code, stage, reason in degraded:
        log.warning(f"  OPTIONAL FAILED {code} (stage: {stage}) — {reason}")
    for code in empties:
        log.warning(f"  EMPTY {code}: no data rows at source")
    for key, codes in sorted(state.data.get("stale", {}).items()):
        if codes and not dry:
            log.warning(f"  STALE {key}: {len(codes)} matrices need a whole-corpus refresh "
                        f"(rerun with --global-profiles)")
    if required_failed:
        log.error(f"Watermark NOT advanced (stays {state.watermark}); failures kept in the "
                  f"retry set at {state_path}")
    elif not dry:
        log.info(f"Watermark: {state.watermark}" + (" (advanced)" if advanced else " (unchanged)"))
        if not degraded:
            log.info("All matrices processed successfully.")
    return exit_code


def main():
    sys.exit(run_pipeline())


if __name__ == "__main__":
    main()
