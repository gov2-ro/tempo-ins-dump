Ready for review
Select text to add comments on the plan
Chart & Filter Framework — Design Plan
Context
Design a generalizable, archetype-driven chart + filter framework for the INS TEMPO explorer. Grounded in 15 representative datasets (2024+ updated). Next step after this plan: implement.

15 Representative Datasets (Reference)
#	Code	Archetype	Dims	Geo	Gran	Rows	Fill	Key Notes
1	TUR105G	geo_time	5	42co	monthly	154k	27%	accommodation×tourist type
2	SAR118B	geo_time	3	regions	annual	204	92%	regions only, no counties
3	PTT102A	geo_time	4	43co	annual	7k	46%	service type
4	LOC108A	geo_time	5	42co	monthly	192k	27%	2 units (nr+m²), has residence dim
5	TLS1112	demographic	5	none	annual	256	44%	sex×age×poverty_status
6	TCJ0331	demographic	4	none	annual	3k	96%	composite dim (sex+age+edu+region)
7	TAL0125	demographic	5	none	annual	364	48%	occupation×sex×age
8	TDE0381	demographic	4	none	annual	1k	93%	composite dim, health status
9	AGR200A	time_series	3	none	annual	455	33%	3 units (kg/l/pieces) — mandatory
10	TAI0122	time_series	3	none	annual	421	83%	30 social indicators
11	TAM0126	time_series	3	none	annual	290	97%	AROPE rate, high fill
12	PPI1039	time_series	3	none	monthly	42k	95%	177 CAEN sectors — typeahead
13	BUF114I	time_residence	5	none	annual	14k	18%	60 products, sparse
14	AMG115B	time_residence	5	none	annual	5k	28%	hours×professional_status
15	CAV101L	time_residence	4	none	annual	216	67%	simple %
Archetype → Chart Mapping
A. geo_time — Geographic + Temporal
Primary: Choropleth map (ECharts + Romania GeoJSON)

Color encodes value for selected period
Time slider below map (play/pause for animation)
Click county → drill to county trend line
Secondary: County ranking bar (horizontal, for selected year)

Tertiary (sparse/dense): Sparkline grid — small county thumbnails

Special case — regional only (SAR118B): No county map possible → replace with regional grouped bar + trend line

Special case — multi-unit (LOC108A): UM selector is mandatory and shown before chart; switching UM redraws map

B. demographic — Gender/Age Breakdowns
Primary: Grouped bar chart

X = categories (age groups or other breakdown)
Series = gender (if present), or other dim
Period selector drives which snapshot is shown
Secondary: Small multiples line — one panel per category, trend over time

Special — has age + gender (TAL0125, TLS1112): Show population pyramid option (toggle)

Special — composite dim (TCJ0331, TDE0381): Treat as flat categorical — no semantic grouping, render as-is in dropdown

C. time_series — Temporal Only
Primary: Multi-line chart

X = time, Y = value
Series = selected values from main categorical dim
Secondary: Area + trend annotation (when trend_direction known from dataset_trends)

Special — high-cardinality (PPI1039, 177 sectors): Typeahead series selector (max 8 simultaneous series)

Special — multi-unit (AGR200A): UM selector is mandatory (shown prominently before chart), blocks rendering

D. time_residence — Urban/Rural Split
Primary: Multi-line chart with residence always as fixed series

Urban / Rural / Total always shown as distinct lines (never collapsed to a filter)
Other dims become filters
Secondary: Small multiples line — one panel per residence type, if other dims selected

Filter Panel Rules
Dimension Type Detection → Control Type
Condition	Control
Geo dimension	Map interaction + region dropdown (NOT a filter panel item)
Time dimension	Slider / range picker (NOT a filter panel item)
UM column with >1 value	Mandatory top-level selector — blocks chart until selected
Residence dim in time_residence archetype	Always chart series, never a filter
Composite dim (/ in header)	Flat dropdown, no grouping, label as-is
Cardinality ≤ 10	Pill/chip group (multi-select, all visible)
Cardinality 11–30	Scrollable dropdown with multi-select
Cardinality > 30	Typeahead search input (max 8 selections for series)
Default Selections
Gender: default to "Total" / all
Age: default to "Total" / all
Residence: show all series by default
Categorical: default to first option (or most-used based on dataset_tags)
Period/time: default to most recent available
Sparse Data Handling (fill_rate < 25%)
Show data availability notice: "This dataset has X% data coverage"
Line chart: show gaps, don't interpolate
Heatmap offered as alternate view (shows presence/absence clearly)
Layout Templates
geo_time
┌─[UM selector — if multi-unit]──────────────────────────────┐
│ [Category filters as pills/dropdowns]                       │
├─────────────────────────────────────┬───────────────────────┤
│                                     │ County trend (line)   │
│     Choropleth Map                  │ for selected county   │
│                                     │                       │
├─────────────────────────────────────┴───────────────────────┤
│ ◄ [time slider with play button] ►                          │
└─────────────────────────────────────────────────────────────┘
│ [County ranking bar — toggleable]                           │
demographic
┌─[Period selector]──[Gender pills]──[Age dropdown]──[Other]──┐
├─────────────────────────────────────────────────────────────┤
│                  Grouped Bar Chart                          │
│                  (primary view)                             │
├─────────────────────────────────────────────────────────────┤
│              Small Multiples Line (trend)                   │
│              [toggled on demand]                            │
└─────────────────────────────────────────────────────────────┘
time_series
┌─[UM selector — MANDATORY if multi-unit]─────────────────────┐
├─[Series selector: pills / typeahead]────[Time range slider]─┤
├─────────────────────────────────────────────────────────────┤
│                  Multi-line / Area Chart                    │
│                  (trend annotation if known)                │
└─────────────────────────────────────────────────────────────┘
time_residence
┌─[Category filters]──────────────────[Time range slider]─────┐
├─────────────────────────────────────────────────────────────┤
│   Multi-line Chart                                          │
│   — Urban  — Rural  — Total  (always shown)                 │
└─────────────────────────────────────────────────────────────┘
Decision Tree (Archetype → Chart)
Has geo (counties)?
  YES → geo_time
        county_count > 0 → choropleth + time slider
        county_count = 0 (regions only) → regional grouped bar + trend
  NO →
    Has residence (urban/rural) dim?
      YES → time_residence → multi-line, residence as series
      NO →
        Has gender OR age dim?
          YES → demographic → grouped bar (+ pyramid if age+gender)
          NO → time_series → multi-line (+ area+trend if trend known)
Generalisation Rules Summary
UM > 1 value → mandatory top filter, never aggregate across units
Geo dim → map control, not dropdown filter
Time dim → slider control, not dropdown filter
Residence in time_residence → always chart series
Composite dim (/ in header) → flat dropdown, no semantic inference
Cardinality > 30 → typeahead, cap simultaneous series at 8
Sparse (fill < 25%) → show warning, offer heatmap view
Trend known → annotate line charts automatically
Short series (< 5 periods) → prefer bar over line
Data Sources
Archetype: matrix_profiles.archetype
Chart recommendations: dataset_chart_recs (relevance-ranked)
Dimension cardinality: dimensions.option_count
Trend info: dataset_trends.trend_direction, trend_slope
Unit types: matrix_profiles.unit_types (JSON array)
Fill rate / sparseness: dataset_coverage.fill_rate
Composite dim detection: dimensions.dim_column_name contains _ joining multiple concepts, or original label contains /
Critical Files to Modify (Implementation)
app/services/chart_config.py — extend archetype → chart config mapping
app/routers/datasets.py or new app/routers/chart.py — endpoint returning chart config per dataset
app/static/js/chart-factory.js — dispatch to chart modules
app/static/js/filter-panel.js — dynamic filter rendering based on rules above
New chart modules as needed: chart-time-series.js, chart-demographic.js (extend existing)
Verification
Load each of the 15 datasets in the browser
Confirm correct chart type rendered
Confirm filter panel controls match dimension cardinality rules
Test UM selector blocking on AGR200A, LOC108A
Test typeahead on PPI1039 (177 sectors)
Test composite dim flat dropdown on TCJ0331, TDE0381
Test sparse data warning on BUF114I (18% fill)
Test regional-only map fallback on SAR118B