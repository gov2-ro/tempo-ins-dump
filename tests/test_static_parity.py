"""Static engine parity on synthetic corpora (CI) and on the real copy (corpus).

Builds the static data layer with scripts/build-static.py, records
data_query.run_query answers with scripts/gen-parity-cases.py and replays them
through the browser engine (tools/static-engine/parity.mjs, Node). Any
difference in errors, decisions, columns, rows, ordering or flags fails.
Skipped when Node is not installed.
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node not installed")


def _run(cmd, env=None):
    r = subprocess.run(cmd, cwd=ROOT, env={**os.environ, **(env or {})},
                       capture_output=True, text=True, timeout=1800)
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-3000:]
    return r.stdout


def _parity(data_dir: Path, out: Path, codes=None, per_dataset=30):
    env = {"TEMPO_DATA_DIR": str(data_dir)}
    sel = ["--codes", ",".join(codes)] if codes else []
    _run([sys.executable, "scripts/build-static.py", "--out", str(out / "static"), "--no-record", *sel], env)
    _run([sys.executable, "scripts/gen-parity-cases.py", "--out", str(out / "cases.jsonl"),
          "--per-dataset", str(per_dataset), *sel], env)
    res = _run([NODE, "--max-old-space-size=4096", "tools/static-engine/parity.mjs",
                "--build", str(out / "static"), "--cases", str(out / "cases.jsonl")])
    summary = json.loads(res.strip().splitlines()[-1])
    assert summary["fail"] == 0 and summary["cases"] > 0, res
    return summary


def test_parity_on_synthetic_corpus(tmp_path):
    from fix02b_corpus import build_corpus
    from test_pa01_grain_guard import _add_dataset
    corpus = build_corpus(tmp_path / "data")
    _add_dataset(corpus, "DUPX", [("A", "2023", 10.0), ("A", "2023", 11.0), ("B", "2023", 5.0)])
    _add_dataset(corpus, "EQX", [("A", "2023", 10.0), ("A", "2023", 10.0), ("B", "2023", 5.0)])
    # a recorded dimension the file does not carry (ART124A on the corpus)
    _add_dataset(corpus, "STALEX", [("A", "2023", 10.0), ("B", "2023", 5.0)])
    import duckdb
    db = duckdb.connect(str(corpus / "metadata.duckdb"))
    db.execute("UPDATE dimensions SET dim_column_name = 'categorie_nom_id' "
               "WHERE matrix_code = 'STALEX' AND dim_column_name = 'CATEGORY'")
    db.close()
    s = _parity(tmp_path / "data", tmp_path / "out",
                ["POPX", "ADDX", "RATEX", "INCX", "DUPX", "EQX", "STALEX"], per_dataset=60)
    assert s["ok"] == s["cases"]
    cases = [json.loads(l) for l in (tmp_path / "out" / "cases.jsonl").read_text().splitlines()]
    stale = [c["response"]["aggregation"] for c in cases
             if c["code"] == "STALEX" and "response" in c]
    assert stale and all(a["reason"] == "schema_mismatch" for a in stale)


def test_partitioned_layout_matches_whole_file(tmp_path):
    """The same synthetic dataset forced into partitions gives identical answers."""
    from fix02b_corpus import build_corpus
    corpus = build_corpus(tmp_path / "data")
    env = {"TEMPO_DATA_DIR": str(tmp_path / "data")}
    out = tmp_path / "out"
    _run([sys.executable, "scripts/build-static.py", "--out", str(out / "static"),
          "--codes", "RATEX,POPX", "--partition-rows", "1", "--no-record"], env)
    assert (out / "static" / "data" / "RATEX.index.json").exists()
    _run([sys.executable, "scripts/gen-parity-cases.py", "--out", str(out / "cases.jsonl"),
          "--codes", "RATEX,POPX", "--per-dataset", "40"], env)
    res = _run([NODE, "tools/static-engine/parity.mjs", "--build", str(out / "static"),
                "--cases", str(out / "cases.jsonl")])
    assert json.loads(res.strip().splitlines()[-1])["fail"] == 0
    # with a 1-byte budget every partitioned read is refused, never answered wrongly
    _run([sys.executable, "scripts/build-static.py", "--out", str(out / "tiny"),
          "--codes", "RATEX,POPX", "--partition-rows", "1", "--max-query-bytes", "1",
          "--no-record"], env)
    res = _run([NODE, "tools/static-engine/parity.mjs", "--build", str(out / "tiny"),
                "--cases", str(out / "cases.jsonl")])
    s = json.loads(res.strip().splitlines()[-1])
    assert s["fail"] == 0 and s["browser_budget_refusals"] > 0


@pytest.mark.corpus
def test_parity_on_real_sample(tmp_path):
    data_dir = Path(os.environ.get("TEMPO_DATA_DIR", ROOT / "data"))
    codes = ["POP105A_judete_grupe", "FOM106F", "SOM103A_judete", "TUR105D_judete",
             "TUR105E_judet", "FOM106E_judete"]
    _parity(data_dir, tmp_path, codes, per_dataset=25)


def _api_parity(data_dir: Path, out: Path, codes: list[str], n=40):
    env = {"TEMPO_DATA_DIR": str(data_dir)}
    sel = ["--codes", ",".join(codes)]
    _run([sys.executable, "scripts/build-static.py", "--out", str(out / "static"), *sel], env)
    _run([sys.executable, "scripts/gen-api-cases.py", "--out", str(out / "api.jsonl"),
          "--n", str(n), *sel], env)
    res = _run([NODE, "--max-old-space-size=4096", "tools/static-engine/api-parity.mjs",
                "--build", str(out / "static"), "--cases", str(out / "api.jsonl")])
    summary = json.loads(res.strip().splitlines()[-1])
    assert summary["fail"] == 0 and summary["cases"] > 0, res
    return summary


def _catalog_corpus(tmp_path):
    """The synthetic corpus plus the catalog columns and a generation id that
    a full static build (with recorded API answers) needs."""
    import duckdb
    from fix02b_corpus import build_corpus
    corpus = build_corpus(tmp_path / "data")
    db = duckdb.connect(str(corpus / "metadata.duckdb"))     # the catalog's columns
    for ddl in ("matrices ADD COLUMN is_canonical BOOLEAN DEFAULT TRUE",
                "matrices ADD COLUMN mat_max_dim INTEGER DEFAULT 3",
                "matrices ADD COLUMN is_split BOOLEAN DEFAULT FALSE",
                "matrix_profiles ADD COLUMN has_time BOOLEAN DEFAULT TRUE",
                "matrix_profiles ADD COLUMN has_geo BOOLEAN DEFAULT TRUE",
                "matrix_profiles ADD COLUMN time_granularity VARCHAR DEFAULT 'annual'",
                "matrix_profiles ADD COLUMN has_gender BOOLEAN DEFAULT FALSE",
                "matrix_profiles ADD COLUMN has_age BOOLEAN",
                "matrix_profiles ADD COLUMN has_residence BOOLEAN DEFAULT FALSE"):
        db.execute("ALTER TABLE " + ddl.replace("ADD COLUMN", "ADD COLUMN IF NOT EXISTS"))
    db.close()
    from test_pa01_grain_guard import _manifest
    _manifest(corpus)                     # a generation id, as a real build has
    return corpus


def test_static_api_matches_server_on_synthetic_corpus(tmp_path):
    """Catalog, search, options, downloads, evidence and recipes answered by the
    static site (engine/static-api.js) equal the FastAPI answers."""
    corpus = _catalog_corpus(tmp_path)
    s = _api_parity(tmp_path / "data", tmp_path / "out", ["POPX", "ADDX", "RATEX", "INCX"])
    assert s["ok"] == s["cases"] - s.get("browser_budget_refusals", 0)
    site = tmp_path / "out" / "static"
    assert "static" in (site / "js" / "config.js").read_text()
    assert (site / "rec" / "catalog.json.gz").exists() and (site / "search" / "concepts.json.gz").exists()
    page = (site / "dataset" / "POPX" / "index.html").read_text()
    assert "/api/" not in page and "/sdmx/" not in page and (site / "dataset" / "POPX" / "en.html").exists()

    # the static release gate: everything but the recipes (no recipe sources here)
    from importlib import util
    spec = util.spec_from_file_location("rc", ROOT / "scripts" / "release-check.py")
    rc = util.module_from_spec(spec)
    spec.loader.exec_module(rc)
    rep = rc.Report()
    rc.check_static(site, rep, corpus, tmp_path / "out" / "api.jsonl")
    assert [f for f in rep.failures if not f.startswith("recipe ")] == [], rep.failures
    (site / "rec" / "catalog.json.gz").write_bytes(b"tampered")
    rep = rc.Report()
    rc.check_static(site, rep)
    assert any("static-manifest.json" in f for f in rep.failures)


@pytest.mark.corpus
def test_static_api_matches_server_on_real_sample(tmp_path):
    data_dir = Path(os.environ.get("TEMPO_DATA_DIR", ROOT / "data"))
    _api_parity(data_dir, tmp_path, ["POP105A_judete_grupe", "FOM106E_judete", "FOM104F_judete",
                                     "SOM103A_judete", "SOM101E", "TUR105D_judete", "ART124A"], n=80)


def test_large_datasets_default_tiles_are_answered_without_loading(tmp_path):
    """Partitioned datasets get the server's answers to their default tile
    queries at build time: with a 1-byte budget those still answer, exactly."""
    _catalog_corpus(tmp_path)
    env = {"TEMPO_DATA_DIR": str(tmp_path / "data")}
    out = tmp_path / "out"
    _run([sys.executable, "scripts/build-static.py", "--out", str(out / "static"), "--codes", "POPX,RATEX",
          "--partition-rows", "1", "--max-query-bytes", "1"], env)
    build = json.loads((out / "static" / "build.json").read_text())
    assert set(build["recorded_queries"]) == {"POPX", "RATEX"} and all(build["recorded_queries"].values())
    _run([sys.executable, "scripts/gen-api-cases.py", "--out", str(out / "all.jsonl"), "--n", "5",
          "--codes", "POPX,RATEX"], env)
    tiles = [l for l in (out / "all.jsonl").read_text().splitlines()
             if '"/data"' not in l and json.loads(l)["path"].endswith("/data")
             and json.loads(l)["params"].get("limit") == 50000]
    (out / "tiles.jsonl").write_text("\n".join(tiles) + "\n")
    res = _run([NODE, "tools/static-engine/api-parity.mjs", "--build", str(out / "static"),
                "--cases", str(out / "tiles.jsonl")])
    s = json.loads(res.strip().splitlines()[-1])
    assert s["cases"] > 0 and s["ok"] == s["cases"] and not s.get("browser_budget_refusals"), res


def test_bar_views_preserve_queries_and_stacking_permissions():
    """Presentation must not infer additivity or discard a dense series silently."""
    _run([NODE, '-e', r'''
const fs = require('fs'), vm = require('vm'), assert = require('assert');
vm.runInThisContext(fs.readFileSync('app/static/js/utils.js', 'utf8'));
const dimensions = [{dim_column_name:'TIME_PERIOD',dim_type:'time'}];
const data = {group_by:['TIME_PERIOD','RATE'],filters:{SEX:['Total']}};
const dense = {id:'dense',chart_type:'heatmap',roles:{x_axis:'TIME_PERIOD',series:'RATE'},data};
const grouped = {...dense,id:'rates',views:['lines','heatmap'],default_view:'lines'};
const additive = {...dense,id:'counts',views:['lines','stacked','heatmap'],default_view:'stacked'};
const reverse = {...dense,id:'reverse',roles:{x_axis:'RATE',series:'TIME_PERIOD'}};
const category = {...dense,id:'category',roles:{x_axis:'COUNTY',series:'RATE'},views:['bars','heatmap']};
const source = {charts:[dense,grouped,additive,reverse,category]};
const result = preferBarViews(source,dimensions);
assert.equal(result.charts[0].default_view,'bars');
assert.equal(result.charts[0].views.join(','),'bars,heatmap');
assert.equal(result.charts[1].default_view,'grouped');
assert(!result.charts[1].views.includes('stacked'));
assert.equal(result.charts[2].default_view,'stacked');
assert.equal(result.charts[3].roles.x_axis,'TIME_PERIOD');
assert.strictEqual(result.charts[4],category);
for (const c of result.charts) assert.strictEqual(c.data,data);
assert.equal(source.charts[0].views,undefined);
assert.equal(source.charts[1].default_view,'lines');
'''])


def test_grouped_time_bars_keep_missing_periods_and_do_not_sum_rates():
    _run([NODE, '-e', r'''
const fs = require('fs'), vm = require('vm'), assert = require('assert');
vm.runInThisContext(fs.readFileSync('app/static/js/utils.js', 'utf8'));
vm.runInThisContext(fs.readFileSync('app/static/js/chart-factory.js', 'utf8'));
let option;
global.echarts = {init: () => ({setOption: o => {option=o;}})};
const data = {columns:['TIME_PERIOD','RATE','OBS_VALUE'],column_labels:{},
 rows:[['2020','A',7],['2022','A',9],['2020','B',2],['2021','B',3]]};
const cfg = {primary_chart:'bar_vertical',time_dim:'TIME_PERIOD',series_dim:'RATE'};
createTimeSeriesChart({},cfg,data,{},'bar');
assert.deepEqual(option.xAxis.data,['2020','2021','2022']);
assert.deepEqual(option.series.map(s => s.data),[[7,null,9],[2,3,null]]);
assert(option.series.every(s => s.type === 'bar' && !s.stack));
const params = [{value:7,seriesName:'A',marker:'',axisValue:'2020'},
                {value:2,seriesName:'B',marker:'',axisValue:'2020'}];
assert(!option.tooltip.formatter(params).includes('∑'));
assert(option.xAxis.axisLabel.showMinLabel && option.xAxis.axisLabel.showMaxLabel);
'''])


def test_theme_teasers_pin_observed_cells_and_validate_dated_insights():
    _run([NODE, '-e', r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert');
vm.runInThisContext(fs.readFileSync('app/static/js/theme-overviews.js','utf8'));
const meta={chart_config:{time_dim:'TIME_PERIOD'},dimensions:[
 {dim_column_name:'CATEGORY',dim_label:'Category',dim_type:'indicator',options:[{sdmx_value:'never occurred',label:'Never occurred'},{sdmx_value:'GDP',label:'GDP'}]},
 {dim_column_name:'UNIT_MEASURE',dim_type:'unit',options:[{sdmx_value:'Number',label:'Number'},{sdmx_value:'Thousands',label:'Thousands'}]},
 {dim_column_name:'REF_AREA',dim_label:'County',dim_type:'geo',options:[{sdmx_value:'Cluj',label:'Cluj'}]},
 {dim_column_name:'TIME_PERIOD',dim_type:'time',options:[]}]};
const sample={columns:['UNIT_MEASURE','TIME_PERIOD','CATEGORY','REF_AREA','OBS_VALUE'],
 rows:[['Thousands','2024','GDP','Cluj',7.5]],column_labels:{}};
const pins=ThemeOverviews.seriesPins(meta,sample);
assert.deepEqual(pins.filters,{UNIT_MEASURE:['Thousands'],CATEGORY:['GDP'],REF_AREA:['Cluj']});
assert.equal(pins.unit,'Thousands');
assert(!('TIME_PERIOD' in pins.filters));
assert(ThemeOverviews.seriesPins(meta,{...sample,columns:['UNIT_MEASURE','TIME_PERIOD','CATEGORY','OBS_VALUE'],rows:[['Thousands','2024','GDP',7.5]]})===null);
const insight={kpis:[{key:'latest',value:0,unit:'%',sparkline:[2,1,0],sparkline_periods:['2020','2022','2025'],
 provenance:{filters:{CATEGORY:['Gross value added'],SEX:['Total']}}}]};
assert.equal(ThemeOverviews.fromInsight('X',insight,'Title').value,0);
assert.deepEqual(ThemeOverviews.fromInsight('X',insight,'Title').context,['Gross value added']);
insight.kpis[0].sparkline_periods=['2020','2021'];
assert.equal(ThemeOverviews.fromInsight('X',insight,'Title'),null);
insight.kpis[0].sparkline_periods=['Under 10 hours','10–20 hours','20+ hours'];
assert.equal(ThemeOverviews.fromInsight('X',insight,'Title'),null);
assert.equal(ThemeOverviews.fromInsight('X',{kpis:[{key:'latest',value:2}]},'Title'),null);
for(const theme of ['general','labour','economy','demography','tourism','health','education','agriculture','industry'])
 for(const lang of ['ro','en']) {
  assert.equal((ThemeOverviews.questions(theme,lang).match(/href=/g)||[]).length,6);
  assert.equal((ThemeOverviews.questions(theme,lang,'Subtheme').match(/href=/g)||[]).length,6);
 }
'''])


def test_gdp_teasers_query_gdp_and_refuse_duplicate_periods():
    _run([NODE, '-e', r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert');
vm.runInThisContext(fs.readFileSync('app/static/js/theme-overviews.js','utf8'));
let calls=0;
global.API={fetch:async()=>{throw Error('Do not reuse the generic GVA headline');},
 getDataset:async code=>({dimensions:[
  {dim_column_name:'CATEGORY',dim_type:'indicator',options:[{sdmx_value:'GVA',label:'Gross value added'},{sdmx_value:'PRODUS INTERN BRUT',label:'GDP'}]},
  {dim_column_name:'UNIT_MEASURE',dim_type:'unit',options:[{sdmx_value:'Millions',label:'Millions'}]},
  {dim_column_name:'TIME_PERIOD',dim_type:'time',options:[]}],chart_config:{time_dim:'TIME_PERIOD'}}),
 getDatasetData:async(code,filters,limit,config)=>{
  calls++;
  assert.deepEqual(filters.CATEGORY,['PRODUS INTERN BRUT']);
  assert.deepEqual(filters.UNIT_MEASURE,['Millions']);
  assert.deepEqual(config.groupBy,['TIME_PERIOD']);
  return {columns:['TIME_PERIOD','OBS_VALUE'],column_labels:code==='CON104P'
   ? {TIME_PERIOD:{'9000':'Anul 2023','8000':'Anul 2024','10000':'Anul 2025'}} : {}, rows:code==='CON104R'
   ? [['2023',1],['2024',2],['2024',999]] : code==='CON104P'
   ? [['9000',1],['8000',2],['10000',3]] : [['2023',1],['2024',2],['2025',3]]};
 }};
ThemeOverviews.theme({theme:'economy',indicators:[{code:'BASE'}]},'en').then(cards=>{
 assert.equal(calls,3);
 assert.deepEqual(cards.map(c=>c.code),['BASE','CON104P','CON104Q']);
 assert.equal(cards[1].value,3);
 assert.deepEqual(cards[1].sparkline_periods,['2023','2024','2025']);
 assert.deepEqual(cards[1].filters.CATEGORY,['PRODUS INTERN BRUT']);
}).catch(e=>{console.error(e);process.exitCode=1;});
'''])
