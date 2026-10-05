"""Synthetic pipeline environment for the FIX-03 phase 2a tests.

A scratch data tree (TEMPO_PIPELINE_DATA_DIR) holding a tiny DuckDB whose DDL mirrors
the real data/corpus/metadata.duckdb (FKs, the indexes that make UPDATEs fail on
referenced rows, lagging sequences), metadata JSON and CSV fixtures. The real stage
scripts run as subprocesses against it. Nothing here touches the real corpus.
"""
import contextlib
import importlib.util
import io
import json
import os
import runpy
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import duckdb

ROOT = Path(__file__).resolve().parent.parent

DDL = """
CREATE TABLE contexts(context_code VARCHAR PRIMARY KEY, parent_code VARCHAR, level INTEGER,
                      context_name VARCHAR, created_at TIMESTAMP DEFAULT current_timestamp,
                      context_name_en VARCHAR);
CREATE TABLE matrices(matrix_code VARCHAR PRIMARY KEY, matrix_name VARCHAR NOT NULL,
  context_code VARCHAR, ancestor_codes VARCHAR[], ancestor_path VARCHAR, periodicitati VARCHAR[],
  definitie VARCHAR, metodologie VARCHAR, ultima_actualizare DATE, observatii VARCHAR,
  persoane_responsabile VARCHAR, intrerupere_last_period VARCHAR, continuare_serie VARCHAR,
  nom_jud BOOLEAN, nom_loc BOOLEAN, mat_max_dim INTEGER, mat_um_spec BOOLEAN, mat_siruta BOOLEAN,
  mat_caen1 BOOLEAN, mat_caen2 BOOLEAN, mat_reg_j BOOLEAN, mat_charge INTEGER, mat_views INTEGER,
  mat_downloads INTEGER, mat_active BOOLEAN, mat_time INTEGER, row_count BIGINT,
  file_size_bytes BIGINT, parquet_path VARCHAR, created_at TIMESTAMP DEFAULT current_timestamp,
  is_split BOOLEAN DEFAULT false, parent_matrix_code VARCHAR, is_canonical BOOLEAN DEFAULT true,
  matrix_name_en VARCHAR, definitie_en VARCHAR,
  FOREIGN KEY (context_code) REFERENCES contexts(context_code));
CREATE INDEX idx_matrices_context ON matrices(context_code);
CREATE INDEX idx_matrices_active ON matrices(mat_active);
CREATE INDEX idx_matrices_dims ON matrices(mat_max_dim);
CREATE TABLE dimensions(dimension_id INTEGER PRIMARY KEY, matrix_code VARCHAR NOT NULL,
  dim_code INTEGER NOT NULL, dim_label VARCHAR NOT NULL, dim_column_name VARCHAR NOT NULL,
  option_count INTEGER, FOREIGN KEY (matrix_code) REFERENCES matrices(matrix_code),
  UNIQUE(matrix_code, dim_code));
CREATE INDEX idx_dimensions_matrix ON dimensions(matrix_code);
CREATE INDEX idx_dimensions_label ON dimensions(dim_label);
CREATE INDEX idx_dimensions_column ON dimensions(dim_column_name);
CREATE TABLE dimension_options(option_id INTEGER PRIMARY KEY, dimension_id INTEGER NOT NULL,
  nom_item_id INTEGER NOT NULL, option_label VARCHAR NOT NULL, option_offset INTEGER,
  parent_id INTEGER, FOREIGN KEY (dimension_id) REFERENCES dimensions(dimension_id),
  UNIQUE(dimension_id, nom_item_id));
CREATE INDEX idx_options_dimension ON dimension_options(dimension_id);
CREATE INDEX idx_options_nom_item ON dimension_options(nom_item_id);
CREATE INDEX idx_options_label ON dimension_options(option_label);
CREATE TABLE dataset_splits(parent_matrix_code VARCHAR, sub_matrix_code VARCHAR,
  split_pattern VARCHAR, split_dimension VARCHAR, split_value VARCHAR, parquet_path VARCHAR,
  row_count BIGINT, suffix_label VARCHAR, display_name VARCHAR, split_dimensions VARCHAR);
CREATE SEQUENCE seq_dimension_id START 1;
CREATE SEQUENCE seq_option_id START 1;
INSERT INTO contexts (context_code, context_name) VALUES ('1', 'Ctx');
"""

# nom_item_ids shared across matrices, like the real nomenclature
Y2020, Y2021, Y2022 = 100, 101, 102


def opt(nid, label, offset=0, parent=None):
    return {"nomItemId": nid, "label": label, "offset": offset, "parentId": parent}


def meta(code, periods, indicators, ums=((300, "Numar"), (301, "Procente")), name=None):
    """Metadata JSON of a 3-dimension matrix: indicator / UM (multi_um split) / period."""
    return {
        "matrixName": name or f"Matrix {code}",
        "ancestors": [{"code": "1", "name": "Ctx"}],
        "periodicitati": ["Anuala"],
        "definitie": "d", "metodologie": "m", "observatii": "o",
        "ultimaActualizare": "01-02-2026",
        "details": {"nomJud": 0, "nomLoc": 0, "matMaxDim": 3, "matActive": 1, "matTime": 3},
        "dimensionsMap": [
            {"label": "Indicatori", "options": [opt(n, l, i) for i, (n, l) in enumerate(indicators)]},
            {"label": "UM: Unitati de masura", "options": [opt(n, l, i) for i, (n, l) in enumerate(ums)]},
            {"label": "Perioade", "options": [opt(n, l, i) for i, (n, l) in enumerate(periods)]},
        ],
    }


class Env:
    def __init__(self, root: Path):
        self.data = root / "data"
        for d in ("2-metas/ro", "4-datasets/ro", "corpus/parquet", "logs", "1-indexes/ro"):
            (self.data / d).mkdir(parents=True, exist_ok=True)
        self.db = self.data / "corpus" / "metadata.duckdb"
        con = duckdb.connect(str(self.db))
        con.execute(DDL)
        con.close()
        self.parquet = self.data / "corpus" / "parquet"

    # -- fixtures
    def write_meta(self, code, **kw):
        (self.data / "2-metas" / "ro" / f"{code}.json").write_text(
            json.dumps(meta(code, **kw)), encoding="utf-8")

    def write_csv(self, code, rows):
        lines = ["Indicatori,UM,Perioade,Valoare"] + [",".join(str(c) for c in r) for r in rows]
        (self.data / "4-datasets" / "ro" / f"{code}.csv").write_text("\n".join(lines) + "\n",
                                                                     encoding="utf-8")

    # -- running real scripts
    def env(self):
        e = dict(os.environ)
        e["TEMPO_PIPELINE_DATA_DIR"] = str(self.data)
        e["TEMPO_LANG"] = "ro"
        return e

    def run(self, script, *args, check=True, subprocess_mode=False):
        """Run a real stage script against the scratch tree.

        In-process by default (a fresh duckdb_config bound to the scratch tree is
        swapped into sys.modules, the script runs via runpy as __main__): same code
        path as the CLI without a Python start-up per stage. subprocess_mode=True runs
        the actual command line (TEMPO_PIPELINE_DATA_DIR)."""
        if subprocess_mode:
            r = subprocess.run([sys.executable, str(ROOT / script), *args], cwd=ROOT,
                               env=self.env(), capture_output=True, text=True)
            rc, out, err = r.returncode, r.stdout, r.stderr
        else:
            rc, out, err = self._run_inproc(script, args)
        if check and rc != 0:
            raise AssertionError(f"{script} {args} exit {rc}\n{out[-2500:]}\n{err[-2500:]}")
        return SimpleNamespace(returncode=rc, stdout=out, stderr=err)

    def _run_inproc(self, script, args):
        saved_env = {k: os.environ.get(k) for k in ("TEMPO_PIPELINE_DATA_DIR", "TEMPO_LANG")}
        os.environ.update(self.env())
        spec = importlib.util.spec_from_file_location("duckdb_config", ROOT / "duckdb_config.py")
        cfg = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cfg)
        saved_cfg, saved_argv = sys.modules.get("duckdb_config"), sys.argv
        sys.modules["duckdb_config"] = cfg
        sys.argv = [script, *args]
        out, err = io.StringIO(), io.StringIO()
        rc = 0
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                try:
                    runpy.run_path(str(ROOT / script), run_name="__main__")
                except SystemExit as e:
                    rc = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
                except Exception:
                    import traceback
                    traceback.print_exc()
                    rc = 1
        finally:
            sys.argv = saved_argv
            if saved_cfg is not None:
                sys.modules["duckdb_config"] = saved_cfg
            else:
                sys.modules.pop("duckdb_config", None)
            for k, v in saved_env.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        return rc, out.getvalue(), err.getvalue()

    def load_module(self, script):
        """Load a stage script as a module bound to the scratch tree (for monkeypatching
        its functions). Its module globals (DB_FILE, PARQUET_V3_DIR, ...) point into
        the scratch tree; sys.modules is left as it was."""
        saved_env = {k: os.environ.get(k) for k in ("TEMPO_PIPELINE_DATA_DIR", "TEMPO_LANG")}
        os.environ.update(self.env())
        spec = importlib.util.spec_from_file_location("duckdb_config", ROOT / "duckdb_config.py")
        cfg = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cfg)
        saved_cfg = sys.modules.get("duckdb_config")
        sys.modules["duckdb_config"] = cfg
        try:
            spec = importlib.util.spec_from_file_location("stage_" + script.replace("-", "_").replace(".py", ""),
                                                          ROOT / script)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
        finally:
            if saved_cfg is not None:
                sys.modules["duckdb_config"] = saved_cfg
            else:
                sys.modules.pop("duckdb_config", None)
            for k, v in saved_env.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        return mod

    def refresh(self, code, split=True):
        """The orchestrator's per-matrix order, against the fixture tree."""
        self.run("10-import-metadata.py", "--matrix", code)
        self.run("10-classify-dimensions.py", "--matrix", code)
        self.run("11-build-sdmx-codes.py", "--matrix", code)
        self.run("9-csv-to-parquet.py", "--matrix", code, "--force")
        if split:
            self.run("12-split-datasets.py", "--matrix", code)
        self.run("10-import-metadata.py", "--matrix", code, "--stats-only")

    def canonicalize_dims(self, *codes):
        """Rewrite dimensions.dim_column_name to the SDMX name, as the (untracked)
        historical process did for most of the real corpus. Same ids, autocommit steps
        (DuckDB rejects an in-place UPDATE of that indexed column)."""
        con = duckdb.connect(str(self.db))
        try:
            for code in codes:
                dims = con.execute("SELECT * FROM dimensions WHERE matrix_code = ?", [code]).fetchall()
                opts = con.execute("SELECT * FROM dimension_options WHERE dimension_id IN "
                                   "(SELECT dimension_id FROM dimensions WHERE matrix_code = ?)",
                                   [code]).fetchall()
                cmap = dict(con.execute("SELECT old_column_name, sdmx_column_name FROM sdmx_column_map "
                                        "WHERE matrix_code = ?", [code]).fetchall())
                con.execute("DELETE FROM dimension_options WHERE dimension_id IN "
                            "(SELECT dimension_id FROM dimensions WHERE matrix_code = ?)", [code])
                con.execute("DELETE FROM dimensions WHERE matrix_code = ?", [code])
                con.executemany("INSERT INTO dimensions VALUES (?, ?, ?, ?, ?, ?)",
                                [(d[0], d[1], d[2], d[3], cmap.get(d[4], d[4]), d[5]) for d in dims])
                con.executemany("INSERT INTO dimension_options VALUES (?, ?, ?, ?, ?, ?)", opts)
        finally:
            con.close()

    # -- inspection (fresh read-only connection each time)
    def q(self, sql, params=()):
        con = duckdb.connect(str(self.db), read_only=True)
        try:
            return con.execute(sql, list(params)).fetchall()
        finally:
            con.close()

    def pq(self, code, sql="SELECT * FROM read_parquet('{p}')"):
        con = duckdb.connect()
        try:
            return con.execute(sql.format(p=self.parquet / f"{code}.parquet")).fetchall()
        finally:
            con.close()
