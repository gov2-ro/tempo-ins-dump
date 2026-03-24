"""
Dissolve county polygons into development regions and macroregions.
Input:  app/static/geo/romania-counties.geojson
Output: app/static/geo/romania-regions.geojson      (8 features)
        app/static/geo/romania-macroregions.geojson (4 features)

Feature names match geo_name_clean values stored in the DB / parquet REF_AREA.
"""
import json
from pathlib import Path
from collections import defaultdict
from shapely.geometry import shape, mapping
from shapely.ops import unary_union

COUNTY_TO_REGION = {
    # NORD-VEST
    'Bihor': 'Regiunea NORD-VEST', 'Bistrita-Nasaud': 'Regiunea NORD-VEST',
    'Cluj': 'Regiunea NORD-VEST', 'Maramures': 'Regiunea NORD-VEST',
    'Satu Mare': 'Regiunea NORD-VEST', 'Salaj': 'Regiunea NORD-VEST',
    # CENTRU
    'Alba': 'Regiunea CENTRU', 'Brasov': 'Regiunea CENTRU',
    'Covasna': 'Regiunea CENTRU', 'Harghita': 'Regiunea CENTRU',
    'Mures': 'Regiunea CENTRU', 'Sibiu': 'Regiunea CENTRU',
    # NORD-EST
    'Bacau': 'Regiunea NORD-EST', 'Botosani': 'Regiunea NORD-EST',
    'Iasi': 'Regiunea NORD-EST', 'Neamt': 'Regiunea NORD-EST',
    'Suceava': 'Regiunea NORD-EST', 'Vaslui': 'Regiunea NORD-EST',
    # SUD-EST
    'Braila': 'Regiunea SUD-EST', 'Buzau': 'Regiunea SUD-EST',
    'Constanta': 'Regiunea SUD-EST', 'Galati': 'Regiunea SUD-EST',
    'Tulcea': 'Regiunea SUD-EST', 'Vrancea': 'Regiunea SUD-EST',
    # SUD-MUNTENIA
    'Arges': 'Regiunea SUD-MUNTENIA', 'Calarasi': 'Regiunea SUD-MUNTENIA',
    'Dambovita': 'Regiunea SUD-MUNTENIA', 'Giurgiu': 'Regiunea SUD-MUNTENIA',
    'Ialomita': 'Regiunea SUD-MUNTENIA', 'Prahova': 'Regiunea SUD-MUNTENIA',
    'Teleorman': 'Regiunea SUD-MUNTENIA',
    # BUCURESTI-ILFOV
    'Municipiul București': 'Regiunea BUCURESTI - ILFOV',
    'Ilfov': 'Regiunea BUCURESTI - ILFOV',
    # SUD-VEST OLTENIA
    'Dolj': 'Regiunea SUD-VEST OLTENIA', 'Gorj': 'Regiunea SUD-VEST OLTENIA',
    'Mehedinti': 'Regiunea SUD-VEST OLTENIA', 'Olt': 'Regiunea SUD-VEST OLTENIA',
    'Valcea': 'Regiunea SUD-VEST OLTENIA',
    # VEST
    'Arad': 'Regiunea VEST', 'Caras-Severin': 'Regiunea VEST',
    'Hunedoara': 'Regiunea VEST', 'Timis': 'Regiunea VEST',
}

REGION_TO_MACRO = {
    'Regiunea NORD-VEST': 'MACROREGIUNEA UNU',
    'Regiunea CENTRU': 'MACROREGIUNEA UNU',
    'Regiunea NORD-EST': 'MACROREGIUNEA DOI',
    'Regiunea SUD-EST': 'MACROREGIUNEA DOI',
    'Regiunea SUD-MUNTENIA': 'MACROREGIUNEA TREI',
    'Regiunea BUCURESTI - ILFOV': 'MACROREGIUNEA TREI',
    'Regiunea SUD-VEST OLTENIA': 'MACROREGIUNEA PATRU',
    'Regiunea VEST': 'MACROREGIUNEA PATRU',
}


def dissolve(src_geojson: Path, name_map: dict, out_path: Path):
    with open(src_geojson) as f:
        counties = json.load(f)

    groups = defaultdict(list)
    unmapped = []
    for feat in counties['features']:
        county_name = feat['properties'].get('name', '')
        group_name = name_map.get(county_name)
        if group_name:
            groups[group_name].append(shape(feat['geometry']))
        else:
            unmapped.append(county_name)

    if unmapped:
        print(f'  WARNING: unmapped counties: {unmapped}')

    features = []
    for group_name, geoms in sorted(groups.items()):
        union = unary_union(geoms)
        features.append({
            'type': 'Feature',
            'properties': {'name': group_name},
            'geometry': mapping(union),
        })

    out = {'type': 'FeatureCollection', 'features': features}
    with open(out_path, 'w') as f:
        json.dump(out, f, ensure_ascii=False)
    print(f'  Wrote {len(features)} features → {out_path}')
    return groups


if __name__ == '__main__':
    src = Path('app/static/geo/romania-counties.geojson')
    out_dir = Path('app/static/geo')

    print('Building romania-regions.geojson...')
    region_groups = dissolve(src, COUNTY_TO_REGION, out_dir / 'romania-regions.geojson')

    # For macroregions: dissolve regions → macroregions using the region geojson we just built
    print('Building romania-macroregions.geojson...')
    dissolve(out_dir / 'romania-regions.geojson', REGION_TO_MACRO,
             out_dir / 'romania-macroregions.geojson')

    print('Done.')
