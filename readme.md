[https://tempo-online.gov2.ro/](tempo-online.gov2.ro) - scrapes data from insse/[tempo-online](http://statistici.insse.ro:8077/tempo-online)  


## Scripts

- `1-fetch-context.py` - fetches contexts &rarr; _data/1-indexes/**\<lang\>**/context.csv_ 
- `2-fetch-matrices.py` - fetches datasets &rarr; _data/1-indexes/**\<lang\>**/matrices.csv_
- `3-fetch-metas.py` - reads _matrices.csv_ and fetches dataset meta json &rarr; _data/2-metas/**\<lang\>**/**\<dataset-id\>**.json_
- `3-build-meta-index.py` – 
- `5-varstats-db.py` - parses downloaded dataset meta and saves fields to SQLite.db
- `6-fetch-csv.py` - loops through metas jsons and downloads dataset as csv &rarr; _data/3-datasets/**\<lang\>**/**\<dataset-id\>**.csv_
- `7-data-compactor.py` – compact csv dimensions - replace `opt_label` with `nomItemId` reference
- `0-tempoins-fetch-indexes.py` - fetches ctgs and datasets from prev version: [tempoins](http://statistici.insse.ro/tempoins/) - with archived datasets
- `browser/` - alpha GUI (to be deprecated for [Evidence](https://evidence.dev))

query-dimensions.py

#### Run the initial analysis
python build-dimension-index.py

#### Search for specific terms
python build-dimension-index.py search "Perioade"
python build-dimension-index.py search "Bucuresti" 

#### Use the query helper for advanced searches
python query-dimensions.py summary      # File overview
python query-dimensions.py usage        # Dimension usage stats
python query-dimensions.py search "grade" # Search options
python query-dimensions.py file ZDP1321   # File details

## Profilers

- `data_profiler.py`
- `variable_classifier.py`
- `unit_classifier.py`
- `rules-dictionaries/`
    - `unit_rules.csv`
    - `variable_classification_rules.csv`


## Data

- 1-indexes/<lang>/
    - matrices.csv
    - context.json
    - context.csv
- 2-metas – jsons
- 3-db
    - tempo-indexes.db
- 4-datasets – csvs 
    - TKP0961.csv
- 5-compact-datasets - compact csvs



## Roadmap 
### alpha
- [x] fetch index
- [x] download csvs
- [x] refactor csvs -> db
- [x] dashboard / charts (alpha)
- [x] compact data

### beta
- [x] categorise filters
- [ ] auto charts
- [ ] dataset filtering, charting options


## UI 

ui/dim-browser.html 

### Roadmap
- [x] filter datasets by dimension
- [x] add context info
- [x] permalinks #variables in url
- [x] combine labels/dimensions
- [x] show dataset preview
- [x] collapse definition