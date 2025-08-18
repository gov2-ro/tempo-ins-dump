I made a dump of data from  the 'Romanian National Institute of Statistics' datasets dumped from http://statistici.insse.ro:8077/tempo-online

I have a repository of csvs and meta data, dimensions. My goal is to create a dashboard for each dataset(table) which would have different charts and filters based on the data type and columns of each table.

I have attached some relevant samples:
- `Tempo Online columns.csv` where I made a list of all recurring header variables (in the first column, separated by `|`).
- `labels.csv` for all variables, along with occurences
- `datasets/*.csv` for some examples of datasets/tables – they are intentionally trimmed to 15 rows 
- `metas/*.json` for meta info, dimensions for each dataset.
- `matrices.csv` the full list of datasets.

I would like you to first have a look at the data, then help me devise an approach / script to categorising / profiling each type of table taht would further help me create relevant charts for each table.

Some patterns I have noticed: 
- the last column is the value
- the penultimate column is UM (Measuring Unit)
- If the dataset has a timestamp it is in the antepenultimate column (year or period, trimester etc)
- before that there might be a location related colum – if it exists
- the rest of the columns are generally category type columns – which can work as filters.

Some ideas of categorisation and display:
- if it has a timestamp then we can chart variance in time
- if it has a location/GIS related column (city, county etc) – we can make maps (probably choropleth type maps)
- category columns can be used as filters, or for comparative line or pie charts (or equivalent)

### Some value types heuristics
- name heuristics
- time: Perioade, Luni, Trimestre, Ani
- geo: Localitati, regiuni, Municipii, orase, tari, continente
- demographics: varsta, sexe
- um: `UM: `
- procent: 'procent'


## Roadmap
- [x] run data profilers?
- [x] categorise type of tables / data / columns
- [ ] specific checks
    - [ ] is geo
    - [ ] is time?
    - [ ] has multiple um?
- [ ] generate views/charts based on type of table / data
- [ ] check/normalize/transform against Eurostat schema: [About Eurostat](https://ec.europa.eu/eurostat/data/database); [schema](https://ec.europa.eu/eurostat/cache/metadata/en/)


see also VALIDATION_README.md

## Scripts

- `rules-dictionaries/`
    - `unit_rules.csv` – how to guess um types
    - `ctg_rules` - detect colum types
- `unit_classifier.py` – 