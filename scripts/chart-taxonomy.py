"""Dataset shape taxonomy — classify datasets into chart-relevant clusters.

Groups ~1,958 datasets into 12 natural clusters based on existing metadata
(archetype, dimensions, unit type, trends). Picks 2-3 exemplars per cluster.

Usage:
    python scripts/chart-taxonomy.py               # generate taxonomy + markdown
    python scripts/chart-taxonomy.py --screenshot   # also screenshot exemplars (needs dev server on :8080)
"""
import argparse
import json
import sys
from pathlib import Path

import duckdb

PROJECT_ROOT = Path(__file__).parent.parent
DB_PATH = PROJECT_ROOT / "data" / "corpus" / "metadata.duckdb"
VP_DIR = PROJECT_ROOT / "data" / "corpus" / "view-profiles"
OUT_MD = PROJECT_ROOT / "docs" / "chart-taxonomy.md"
OUT_JSON = PROJECT_ROOT / "data" / "eval" / "chart_taxonomy.json"
SCREENSHOT_DIR = PROJECT_ROOT / "docs" / "chart-taxonomy"

CLUSTERS = [
    {"id": 1,  "name": "Simple Time Series",    "desc": "Single indicator over time, no structural dims"},
    {"id": 2,  "name": "Categorical Time",       "desc": "Time + medium-cardinality categorical dim (6-50 options)"},
    {"id": 3,  "name": "Composition (%)",         "desc": "Percentage unit, parts-of-whole over time"},
    {"id": 4,  "name": "Gender-Split",            "desc": "Binary gender breakdown over time"},
    {"id": 5,  "name": "Age Cohort",              "desc": "Age groups over time (no gender)"},
    {"id": 6,  "name": "Population Pyramid",      "desc": "Age + gender over time"},
    {"id": 7,  "name": "Cartographic",            "desc": "Geographic (county/region) + time, no demographic dims"},
    {"id": 8,  "name": "Geo + Demographic",       "desc": "Geographic + gender/age/residence"},
    {"id": 9,  "name": "Urban/Rural",             "desc": "Residence (urban/rural) splits over time"},
    {"id": 10, "name": "Categorical Snapshot",    "desc": "No time, no geo — pure categorical cross-tabs"},
    {"id": 11, "name": "Geo Snapshot",            "desc": "Geographic, no time dimension"},
    {"id": 12, "name": "Edge Cases",              "desc": "High-dimensional or rare combos"},
]


def load_datasets(conn):
    """Load all datasets with their metadata for classification."""
    rows = conn.execute("""
        SELECT
            mp.matrix_code,
            mp.archetype,
            mp.has_time,
            mp.has_geo,
            mp.has_gender,
            mp.has_age,
            mp.has_residence,
            mp.primary_unit_type,
            mp.dim_count,
            mp.time_granularity,
            COALESCE(dc.fill_rate, 0) AS fill_rate,
            COALESCE(dc.actual_rows, 0) AS actual_rows,
            COALESCE(dt.trend_direction, 'unknown') AS trend_direction,
            COALESCE(dt.has_seasonality, false) AS has_seasonality,
            m.matrix_name,
            m.ultima_actualizare
        FROM matrix_profiles mp
        LEFT JOIN dataset_coverage dc ON mp.matrix_code = dc.matrix_code
        LEFT JOIN dataset_trends dt ON mp.matrix_code = dt.matrix_code
        LEFT JOIN matrices m ON mp.matrix_code = m.matrix_code
    """).fetchdf()
    return rows


def get_max_cat_options(conn):
    """Get max non-time/non-unit dimension option count per dataset.

    Excludes TIME_PERIOD/TIME_PERIOD_2 (some datasets carry a secondary
    time axis), UNIT_MEASURE, and FREQ. Without TIME_PERIOD_2 in the
    exclusion list, datasets like CNF101F (annual + quarterly time
    columns) would be misclassified into cluster 2.
    """
    rows = conn.execute("""
        SELECT matrix_code, MAX(option_count) AS max_cat_options
        FROM dimensions
        WHERE dim_column_name NOT IN ('TIME_PERIOD', 'TIME_PERIOD_2', 'UNIT_MEASURE', 'FREQ')
        GROUP BY matrix_code
    """).fetchall()
    return {r[0]: r[1] for r in rows}


def get_age_options(conn):
    """Map matrix_code → age dim option_count.

    A dim is "age" when the majority of its parsed options have dim_type='age'.
    Used to distinguish small-age datasets (3-5 groups, line-friendly) from
    real cohort analyses (6+ groups, heatmap-friendly).
    """
    rows = conn.execute("""
        WITH dim_age_votes AS (
            SELECT d.matrix_code, d.dim_column_name, d.option_count,
                   SUM(CASE WHEN p.dim_type = 'age' THEN 1 ELSE 0 END) AS age_votes,
                   COUNT(*) AS total_votes
            FROM dimensions d
            JOIN dimension_options o ON o.dimension_id = d.dimension_id
            LEFT JOIN dimension_options_parsed p ON o.nom_item_id = p.nom_item_id
            GROUP BY d.matrix_code, d.dim_column_name, d.option_count
            HAVING age_votes > total_votes / 2
        )
        SELECT matrix_code, MAX(option_count) FROM dim_age_votes GROUP BY matrix_code
    """).fetchall()
    return {r[0]: r[1] for r in rows}


def classify(row, max_cat_opts, age_opts):
    """Assign a dataset to one of the 12 clusters."""
    arch = row["archetype"]
    mc = row["matrix_code"]
    max_opts = max_cat_opts.get(mc, 0) or 0
    age_count = age_opts.get(mc, 0) or 0

    # Snapshots (no time)
    if arch == "categorical":
        return 10
    if arch == "geo_only":
        return 11

    # Demographic clusters (check before geo since some geo datasets also have demographics)
    if row["has_age"] and row["has_gender"] and not row["has_geo"]:
        return 6  # Population Pyramid
    # Age cohort requires meaningfully many age groups (6+). Datasets with
    # age=2-5 are simple-time-series-with-a-few-series — line works fine.
    if row["has_age"] and not row["has_gender"] and not row["has_geo"] and age_count >= 6:
        return 5  # Age Cohort
    if row["has_gender"] and not row["has_age"] and not row["has_geo"]:
        return 4  # Gender-Split

    # Geographic clusters
    if arch == "geo_time" or (row["has_geo"] and row["has_time"]):
        if row["has_gender"] or row["has_age"] or row["has_residence"]:
            return 8  # Geo + Demographic
        return 7  # Pure Cartographic

    # Urban/Rural
    if arch == "time_residence" or (row["has_residence"] and not row["has_geo"]):
        return 9

    # Time series variants
    if arch == "time_series" or row["has_time"]:
        if row["primary_unit_type"] == "percentage":
            return 3  # Composition
        if max_opts >= 6:
            return 2  # Categorical Time
        return 1  # Simple Time Series

    return 12  # Edge Cases


def pick_exemplars(df, cluster_id, n=3):
    """Pick n exemplars from a cluster, preferring good coverage + VP existence."""
    subset = df[df["cluster"] == cluster_id].copy()
    if subset.empty:
        return []

    # Prefer: VP exists, moderate size, good fill rate, recently updated
    vp_codes = {p.stem for p in VP_DIR.glob("*.json")} if VP_DIR.exists() else set()
    subset["has_vp"] = subset["matrix_code"].isin(vp_codes)
    subset["size_ok"] = (subset["actual_rows"] >= 100) & (subset["actual_rows"] <= 50000)

    # Score for ranking
    subset["pick_score"] = (
        subset["has_vp"].astype(int) * 10 +
        subset["size_ok"].astype(int) * 5 +
        subset["fill_rate"] * 3
    )

    top = subset.nlargest(n, "pick_score")
    return top[["matrix_code", "matrix_name", "fill_rate", "actual_rows", "trend_direction"]].to_dict("records")


def generate_markdown(taxonomy, total):
    """Generate docs/chart-taxonomy.md."""
    lines = [
        "# Dataset Shape Taxonomy",
        "",
        f"Auto-generated classification of {total} datasets into 12 chart-relevant clusters.",
        f"Use this to identify chart improvement opportunities per cluster.",
        "",
        "## Summary",
        "",
        "| # | Cluster | Count | % | Primary Chart | Description |",
        "|---|---------|-------|---|---------------|-------------|",
    ]
    for c in taxonomy:
        pct = f"{c['count'] / total * 100:.1f}%" if total else "0%"
        lines.append(f"| {c['id']} | {c['name']} | {c['count']} | {pct} | {c.get('primary_chart', '—')} | {c['desc']} |")

    lines += ["", "## Exemplars per Cluster", ""]

    for c in taxonomy:
        lines.append(f"### {c['id']}. {c['name']} ({c['count']} datasets)")
        lines.append(f"_{c['desc']}_")
        lines.append("")
        if c["exemplars"]:
            lines.append("| Code | Name | Fill Rate | Rows | Trend | Screenshot |")
            lines.append("|------|------|-----------|------|-------|------------|")
            for ex in c["exemplars"]:
                name = (ex["matrix_name"] or "")[:60]
                fr = f"{ex['fill_rate']:.1%}" if ex["fill_rate"] else "—"
                rows = f"{ex['actual_rows']:,}" if ex["actual_rows"] else "—"
                trend = ex.get("trend_direction", "—")
                ss = f"![{ex['matrix_code']}](chart-taxonomy/{ex['matrix_code']}.png)"
                lines.append(f"| `{ex['matrix_code']}` | {name} | {fr} | {rows} | {trend} | {ss} |")
        else:
            lines.append("_No exemplars found._")
        lines.append("")

    lines.append("---")
    lines.append("_Generated by `scripts/chart-taxonomy.py`_")
    return "\n".join(lines)


# Expected primary chart(s) per cluster — used both for documentation and for
# the cluster-correctness baseline. "/"-separated values are alternatives:
# any of them is accepted as a correct primary pick.
#
# Cluster 3 was previously "area_stacked" but audit showed ~92% of percentage
# datasets are rates/indices/shares (not parts-of-whole). Default to line;
# area_stacked stays as a swappable alternate for true compositions.
CLUSTER_CHARTS = {
    1: "line",
    2: "small_multiples / heatmap",
    # Cluster 3 absorbs diverse percentage data (rates, indices, shares,
    # parts-of-whole). Chart depends on dim shape: simple ≤4 categories →
    # line; 6-25 → small_multiples; very high → heatmap. area_stacked is a
    # swappable alternate for true compositions, never auto-primary.
    3: "line / small_multiples / heatmap",
    # Cluster 4/9 absorb high-dim datasets where gender/residence is just one
    # dim among several — small_multiples and horizontal_bar are valid primaries
    # when an extra categorical dim has many options. Line still ideal for
    # simple binary-gender / urban-rural pairs.
    4: "line / small_multiples / horizontal_bar",
    # Cluster 5 absorbs age-cohort datasets, sometimes with extra category
    # dimensions. Pure age × time → heatmap (matrix view); age + 6-25 cat →
    # small_multiples is genuinely cleaner than heatmap of 3 dims; age +
    # high-cardinality cat → horizontal_bar (ranking) is fine snapshot.
    5: "heatmap / grouped_bar / small_multiples / horizontal_bar",
    6: "population_pyramid",
    # Cluster 7 is dominantly choropleth, but high-cardinality category × geo
    # snapshots (e.g. ASS113E with 14 unit measures × 28 counties × single
    # year) are reasonable as horizontal_bar (county ranking) too. Geo + cat
    # 6-25 facet is also legitimately small_multiples (panel per region).
    7: "choropleth / small_multiples / horizontal_bar",
    8: "choropleth / line",
    9: "line / small_multiples / horizontal_bar",
    # Cluster 10 mixes single-cat snapshots (1 product dim) with multi-cat
    # cross-tabs. h_bar fits the long-list ranking case; bar_vertical the small
    # case; grouped_bar the cat × cat case.
    10: "grouped_bar / horizontal_bar / bar_vertical",
    11: "choropleth",
    12: "varies",
}


def _expected_set(cluster_id: int) -> set[str]:
    """Parse CLUSTER_CHARTS[cluster_id] into a set of acceptable primary picks."""
    raw = CLUSTER_CHARTS.get(cluster_id, "")
    return {p.strip() for p in raw.split("/") if p.strip() and p.strip() != "varies"}


def take_screenshots(taxonomy, base_url="http://localhost:8080"):
    """Screenshot each exemplar via Playwright."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("ERROR: playwright not installed. Run: pip install playwright && playwright install chromium")
        return

    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

    all_codes = []
    for c in taxonomy:
        for ex in c["exemplars"]:
            all_codes.append(ex["matrix_code"])

    print(f"\nTaking {len(all_codes)} screenshots...")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})

        for i, code in enumerate(all_codes):
            path = SCREENSHOT_DIR / f"{code}.png"
            if path.exists():
                print(f"  [{i+1}/{len(all_codes)}] {code} — already exists, skipping")
                continue
            try:
                page.goto(f"{base_url}/?code={code}", wait_until="networkidle", timeout=15000)
                page.wait_for_timeout(3500)  # let charts render
                page.screenshot(path=str(path), full_page=False)
                print(f"  [{i+1}/{len(all_codes)}] {code} — OK")
            except Exception as e:
                print(f"  [{i+1}/{len(all_codes)}] {code} — ERROR: {e}")

        browser.close()

    print(f"\nScreenshots saved to {SCREENSHOT_DIR}/")


def main():
    parser = argparse.ArgumentParser(description="Dataset shape taxonomy generator")
    parser.add_argument("--screenshot", action="store_true", help="Also take Playwright screenshots (needs dev server on :8080)")
    args = parser.parse_args()

    if not DB_PATH.exists():
        print(f"ERROR: Database not found at {DB_PATH}")
        sys.exit(1)

    conn = duckdb.connect(str(DB_PATH), read_only=True)

    print("Loading datasets...")
    df = load_datasets(conn)
    max_cat_opts = get_max_cat_options(conn)
    age_opts = get_age_options(conn)

    print(f"Classifying {len(df)} datasets into 12 clusters...")
    df["cluster"] = df.apply(lambda r: classify(r, max_cat_opts, age_opts), axis=1)

    # Build taxonomy
    taxonomy = []
    for c in CLUSTERS:
        cid = c["id"]
        count = int((df["cluster"] == cid).sum())
        exemplars = pick_exemplars(df, cid)
        taxonomy.append({
            **c,
            "count": count,
            "primary_chart": CLUSTER_CHARTS.get(cid, "—"),
            "exemplars": exemplars,
        })

    # Console output
    total = len(df)
    print(f"\n{'#':<3} {'Cluster':<24} {'Count':>6} {'%':>6}  {'Primary Chart':<24} Exemplars")
    print("-" * 100)
    for c in taxonomy:
        pct = f"{c['count']/total*100:.1f}%"
        codes = ", ".join(e["matrix_code"] for e in c["exemplars"])
        print(f"{c['id']:<3} {c['name']:<24} {c['count']:>6} {pct:>6}  {c['primary_chart']:<24} {codes}")
    print(f"\nTotal: {total} datasets")

    # Write markdown
    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    md = generate_markdown(taxonomy, total)
    OUT_MD.write_text(md, encoding="utf-8")
    print(f"\nMarkdown written to {OUT_MD}")

    # Write JSON
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(taxonomy, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"JSON written to {OUT_JSON}")

    # ── Cluster-correctness baseline ────────────────────────────────────────
    # For every dataset: cluster_id, expected primary chart(s), selector's
    # actual primary, and match. This is the ground-truth eval file.
    print("\nBuilding cluster-correctness baseline...")
    sys.path.insert(0, str(PROJECT_ROOT))
    from app.services.chart_selector_eval import evaluate_all  # noqa: E402

    eval_rows = evaluate_all(conn)
    baseline = {"version": 1, "total": len(df), "by_cluster": {}, "datasets": {}}
    cluster_stats = {c["id"]: {"name": c["name"], "expected": CLUSTER_CHARTS.get(c["id"], "—"),
                               "total": 0, "matches": 0, "misses": []}
                     for c in CLUSTERS}

    for _, r in df.iterrows():
        mc = r["matrix_code"]
        cid = int(r["cluster"])
        actual_entry = eval_rows.get(mc) or {}
        actual = actual_entry.get("primary")
        expected = _expected_set(cid)
        match = (not expected) or (actual in expected)
        baseline["datasets"][mc] = {
            "cluster": cid,
            "expected": sorted(expected) if expected else [],
            "actual": actual,
            "match": match,
        }
        cluster_stats[cid]["total"] += 1
        if match:
            cluster_stats[cid]["matches"] += 1
        elif len(cluster_stats[cid]["misses"]) < 5:
            cluster_stats[cid]["misses"].append({"matrix_code": mc, "got": actual})

    baseline["by_cluster"] = {
        str(cid): {**stats,
                   "match_pct": round(100 * stats["matches"] / stats["total"], 1) if stats["total"] else 0.0}
        for cid, stats in cluster_stats.items()
    }
    overall_matches = sum(s["matches"] for s in cluster_stats.values())
    baseline["overall_match_pct"] = round(100 * overall_matches / max(len(df), 1), 1)

    BASELINE_PATH = PROJECT_ROOT / "data" / "eval" / "chart_taxonomy_baseline.json"
    BASELINE_PATH.write_text(json.dumps(baseline, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"Baseline written to {BASELINE_PATH}")
    print(f"\nOverall cluster-correctness: {baseline['overall_match_pct']}%")
    print(f"\n{'#':<3} {'Cluster':<24} {'Match':<14} Expected")
    for cid in sorted(cluster_stats):
        s = cluster_stats[cid]
        if s["total"] == 0:
            continue
        m = f"{s['matches']}/{s['total']} ({100*s['matches']/s['total']:.0f}%)"
        print(f"{cid:<3} {s['name']:<24} {m:<14} {s['expected']}")

    if args.screenshot:
        take_screenshots(taxonomy)


if __name__ == "__main__":
    main()
