"""
Test the chart_selector engine against all 1,886 INS TEMPO datasets.
Compares new scoring engine output to current archetype-based selections.

Usage:
    python test_chart_selector.py                   # full report
    python test_chart_selector.py --spot ACC101B    # spot-check one dataset
    python test_chart_selector.py --disagreements   # only show archetype mismatches
"""
import sys
import json
import duckdb
from collections import Counter

sys.path.insert(0, '.')
from app.services.chart_selector import build_signature, select_charts, assign_roles

DB_PATH = "data/tempo_metadata.duckdb"

# Old archetype → what chart it mapped to
ARCHETYPE_DEFAULT = {
    'geo_time': 'choropleth',
    'demographic': 'grouped_bar',
    'time_residence': 'line',
    'time_series': 'line',
}


def load_all(conn):
    """Load all metadata into dicts keyed by matrix_code."""
    print("Loading metadata...")

    profiles = {r[0]: dict(zip(
        ['matrix_code','has_time','time_granularity','time_year_min','time_year_max',
         'has_geo','geo_levels','has_gender','has_age','has_residence',
         'unit_types','primary_unit_type','dim_count','archetype','parse_coverage'],
        r)) for r in conn.execute("SELECT * FROM matrix_profiles").fetchall()}

    # dim_type per dimension — majority vote
    dim_type_map = {}
    for dim_id, dtype, cnt in conn.execute("""
        SELECT dopt.dimension_id, dop.dim_type, COUNT(*) as cnt
        FROM dimension_options dopt
        JOIN dimension_options_parsed dop ON dopt.nom_item_id = dop.nom_item_id
        GROUP BY dopt.dimension_id, dop.dim_type
        ORDER BY dopt.dimension_id, cnt DESC
    """).fetchall():
        if dim_id not in dim_type_map:
            dim_type_map[dim_id] = dtype

    dims_by_matrix = {}
    for dim_id, mc, col, opt_count in conn.execute(
        "SELECT dimension_id, matrix_code, dim_column_name, option_count FROM dimensions"
    ).fetchall():
        dims_by_matrix.setdefault(mc, []).append({
            'dimension_id': dim_id, 'dim_column_name': col,
            'option_count': opt_count, 'dim_type': dim_type_map.get(dim_id)
        })

    coverages = {r[0]: dict(zip(
        ['matrix_code','time_dim_column','time_min_year','time_max_year','time_year_count',
         'time_gap_years','time_granularity','geo_dim_column','geo_county_count',
         'geo_has_national','geo_has_locality','geo_level_counts','theoretical_max',
         'actual_rows','fill_rate','freshness_years','sparse_dims','dim_count','created_at'],
        r)) for r in conn.execute("SELECT * FROM dataset_coverage").fetchall()}

    value_profiles = {r[0]: dict(zip(
        ['matrix_code','row_count','val_min','val_max','val_mean','val_median','val_stddev',
         'val_p25','val_p75','null_pct','zero_pct','negative_pct','coeff_variation',
         'magnitude','distribution_shape'],
        r)) for r in conn.execute("SELECT * FROM dataset_value_profiles").fetchall()}

    trends = {r[0]: dict(zip(
        ['matrix_code','trend_direction','trend_slope','yoy_growth_latest','max_value_year',
         'min_value_year','has_seasonality','breakpoint_years','geo_variance','geo_outlier_counties'],
        r)) for r in conn.execute("SELECT * FROM dataset_trends").fetchall()}

    matrices = [r[0] for r in conn.execute(
        "SELECT matrix_code FROM matrices ORDER BY matrix_code").fetchall()]

    return profiles, dims_by_matrix, coverages, value_profiles, trends, matrices


def evaluate(mc, profiles, dims_by_matrix, coverages, value_profiles, trends):
    profile = profiles.get(mc, {})
    dims = dims_by_matrix.get(mc, [])
    cov = coverages.get(mc)
    vp = value_profiles.get(mc)
    tr = trends.get(mc)

    sig = build_signature(profile, dims, cov, vp, tr)
    ranked = select_charts(sig)
    primary = ranked[0]['chart_type'] if ranked else 'table'
    old_primary = ARCHETYPE_DEFAULT.get(sig['_archetype'], 'line')

    return {
        'matrix_code': mc,
        'archetype': sig['_archetype'],
        'old_primary': old_primary,
        'new_primary': primary,
        'new_ranked': ranked,
        'sig': sig,
        'agrees': primary == old_primary,
    }


def fmt_sig(sig):
    parts = []
    if sig['has_time']: parts.append(f"time({sig['time_points']}yr)")
    if sig['has_geo']: parts.append(f"geo({sig['geo_count']})")
    if sig['has_gender']: parts.append(f"gender({sig['gender_count']})")
    if sig['has_age']: parts.append(f"age({sig['age_count']})")
    if sig['has_residence']: parts.append("residence")
    for d in sig['categorical_dims']:
        parts.append(f"ind({d['count']})")
    unit = sig.get('primary_unit_type', 'count')
    if unit != 'count': parts.append(f"unit={unit}")
    if sig['has_negatives']: parts.append("neg!")
    if sig['is_sparse']: parts.append("sparse!")
    if sig['has_seasonality']: parts.append("seasonal!")
    if sig['trend_direction'] == 'volatile': parts.append("volatile!")
    return " | ".join(parts)


def spot_check(mc, profiles, dims_by_matrix, coverages, value_profiles, trends):
    result = evaluate(mc, profiles, dims_by_matrix, coverages, value_profiles, trends)
    sig = result['sig']
    print(f"\n{'='*60}")
    print(f"  {mc}  (archetype: {result['archetype']})")
    print(f"{'='*60}")
    print(f"  Signature: {fmt_sig(sig)}")
    print(f"  Old primary: {result['old_primary']}")
    print(f"  New primary: {result['new_primary']}  {'✓ agrees' if result['agrees'] else '⚠ differs'}")
    if result['new_ranked']:
        conf = result['new_ranked'][0].get('confidence', '?')
        print(f"  Confidence: {conf}")
    print(f"\n  Ranked chart options:")
    for r in result['new_ranked']:
        bar = '█' * int(r['score'] * 20)
        comp = f"  ↔ {r['complementary_to']}" if r.get('complementary_to') else ""
        print(f"    {r['chart_type']:20s}  {r['score']:.2f}  {bar}{comp}")
    roles = assign_roles(result['new_primary'], dims_by_matrix.get(mc, []))
    print(f"\n  Role assignment ({result['new_primary']}):")
    for role, val in roles.items():
        if val and val != [] and val != {}:
            print(f"    {role:14s}: {val}")


def main():
    args = sys.argv[1:]
    spot_mode = '--spot' in args
    disagreements_only = '--disagreements' in args

    conn = duckdb.connect(DB_PATH, read_only=True)
    profiles, dims_by_matrix, coverages, value_profiles, trends, matrices = load_all(conn)
    conn.close()

    print(f"\nEvaluating {len(matrices)} datasets...")

    if spot_mode:
        idx = args.index('--spot')
        codes = args[idx+1:]
        for mc in codes:
            if mc not in profiles:
                print(f"  {mc}: not found")
            else:
                spot_check(mc, profiles, dims_by_matrix, coverages, value_profiles, trends)
        return

    results = [evaluate(mc, profiles, dims_by_matrix, coverages, value_profiles, trends)
               for mc in matrices]

    # ---- Summary stats ----
    total = len(results)
    agrees = sum(1 for r in results if r['agrees'])
    print(f"\n{'='*60}")
    print(f"  CHART SELECTION SUMMARY — {total} datasets")
    print(f"{'='*60}")
    print(f"\n  Agreement with old archetype system: {agrees}/{total} ({100*agrees/total:.1f}%)")

    print("\n  New primary chart distribution:")
    new_dist = Counter(r['new_primary'] for r in results)
    for chart, cnt in new_dist.most_common():
        pct = 100 * cnt / total
        bar = '█' * int(pct / 2)
        print(f"    {chart:22s}  {cnt:4d}  ({pct:4.1f}%)  {bar}")

    print("\n  Old archetype distribution (for reference):")
    old_dist = Counter(r['archetype'] for r in results)
    for arch, cnt in old_dist.most_common():
        old_chart = ARCHETYPE_DEFAULT.get(arch, '?')
        print(f"    {arch:18s}  {cnt:4d}  → was {old_chart}")

    print("\n  Archetype × New Primary cross-tab:")
    cross = Counter((r['archetype'], r['new_primary']) for r in results)
    archetypes = ['geo_time', 'demographic', 'time_residence', 'time_series']
    new_charts = [ct for ct, _ in new_dist.most_common()]
    header = f"  {'':18s}" + "".join(f"  {c[:12]:12s}" for c in new_charts)
    print(header)
    for arch in archetypes:
        row = f"  {arch:18s}"
        for ct in new_charts:
            cnt = cross.get((arch, ct), 0)
            row += f"  {cnt:12d}" if cnt > 0 else f"  {'':12s}"
        print(row)

    # ---- Disagreements ----
    disagree = [r for r in results if not r['agrees']]
    print(f"\n  Disagreements: {len(disagree)} datasets ({100*len(disagree)/total:.1f}%)")
    if disagree:
        print("  (where new primary ≠ archetype default)")
        print(f"\n  {'Code':10s}  {'Archetype':16s}  {'Old':14s}  {'New':22s}  {'Score':5s}  Signature")
        print("  " + "-" * 100)
        for r in sorted(disagree, key=lambda x: (x['archetype'], x['new_primary'])):
            top_score = r['new_ranked'][0]['score'] if r['new_ranked'] else 0
            sig_str = fmt_sig(r['sig'])
            if disagreements_only or len(disagree) <= 30:
                print(f"  {r['matrix_code']:10s}  {r['archetype']:16s}  {r['old_primary']:14s}  "
                      f"{r['new_primary']:22s}  {top_score:.2f}  {sig_str}")
            else:
                # Sample: top 5 per archetype
                pass

        if not disagreements_only and len(disagree) > 30:
            print(f"\n  (showing first 30 of {len(disagree)} — use --disagreements for all)")
            for r in sorted(disagree, key=lambda x: x['new_ranked'][0]['score'] if x['new_ranked'] else 0, reverse=True)[:30]:
                top_score = r['new_ranked'][0]['score'] if r['new_ranked'] else 0
                sig_str = fmt_sig(r['sig'])
                print(f"  {r['matrix_code']:10s}  {r['archetype']:16s}  {r['old_primary']:14s}  "
                      f"{r['new_primary']:22s}  {top_score:.2f}  {sig_str}")

    # ---- Spot checks ----
    print(f"\n{'='*60}")
    print("  SPOT CHECKS — known datasets")
    print(f"{'='*60}")
    for mc in ['ACC101B', 'AMG101A', 'BUF104G', 'SOM101B', 'FOM104B', 'POP105A']:
        if mc in profiles:
            spot_check(mc, profiles, dims_by_matrix, coverages, value_profiles, trends)

    # ---- Unit type distribution ----
    print(f"\n{'='*60}")
    print("  UNIT TYPE × PRIMARY CHART")
    print(f"{'='*60}")
    unit_dist = Counter(r['sig'].get('primary_unit_type', 'count') for r in results)
    for ut, cnt in unit_dist.most_common():
        primaries = Counter(r['new_primary'] for r in results if r['sig'].get('primary_unit_type') == ut)
        top3 = ", ".join(f"{ct}({n})" for ct, n in primaries.most_common(3))
        print(f"  {ut:14s}  {cnt:4d}  → {top3}")

    # ---- Confidence distribution ----
    conf_dist = Counter(
        r['new_ranked'][0].get('confidence', '?') if r['new_ranked'] else '?'
        for r in results
    )
    print(f"\n  Confidence distribution:")
    for conf, cnt in conf_dist.most_common():
        print(f"    {conf:8s}  {cnt:4d}  ({100*cnt/total:.1f}%)")

    # ---- Interesting findings ----
    print(f"\n{'='*60}")
    print("  INTERESTING: Datasets that gain new chart options")
    print(f"{'='*60}")
    gained_heatmap = [r for r in results if any(x['chart_type'] == 'heatmap' for x in r['new_ranked'])]
    gained_pyramid = [r for r in results if r['new_primary'] == 'population_pyramid']
    gained_small = [r for r in results if r['new_primary'] == 'small_multiples']
    gained_area = [r for r in results if r['new_primary'] == 'area_stacked']
    print(f"  Datasets eligible for heatmap: {len(gained_heatmap)}")
    print(f"  Datasets primary = population_pyramid: {len(gained_pyramid)}")
    print(f"  Datasets primary = small_multiples: {len(gained_small)}")
    print(f"  Datasets primary = area_stacked: {len(gained_area)}")

    if gained_pyramid:
        print(f"\n  Sample population pyramid datasets:")
        for r in gained_pyramid[:5]:
            print(f"    {r['matrix_code']:10s}  {fmt_sig(r['sig'])}")

    if gained_small:
        print(f"\n  Sample small_multiples datasets:")
        for r in gained_small[:5]:
            print(f"    {r['matrix_code']:10s}  {fmt_sig(r['sig'])}")

    if gained_area:
        print(f"\n  Sample area_stacked datasets (boosted by unit awareness):")
        for r in gained_area[:5]:
            print(f"    {r['matrix_code']:10s}  {fmt_sig(r['sig'])}")


if __name__ == '__main__':
    main()
