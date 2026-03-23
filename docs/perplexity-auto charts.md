<img src="https://r2cdn.perplexity.ai/pplx-full-logo-primary-dark%402x.png" style="height:64px;margin-right:32px"/>

# please, turn this into an explicit chart-selection algorithm and a page wireframe spec

Use a semantic-first decision engine: classify columns into measure, time, geo, sex, age, and other categories, then choose one primary view, one optional complementary view, and a table, instead of exposing the raw cube to users.[^1][^2]
That fits your goal of smart defaults with minimal toggles, and it matches the structure of the example files, which include clean geo-time-category cubes, sex-age-time cubes, and harder mixed-dimension cases with multiple measures or mixed category families.[^3][^4][^5][^6]

## Selection algorithm

1. Parse the dataset into roles: `measure`, `time?`, `geo?`, `sex?`, `age?`, `other_dims[]`, `flags?`, and detect hierarchies such as region-to-county or age-band order before charting.[^1]
2. Build a default slice by picking the latest time, the most meaningful geo level, the primary measure, and `"Total"` members where available; if a dimension has many values, keep top $N$ plus `Other` and hide the rest behind search.[^2][^1]
3. Score chart candidates with simple rules: prefer line when time is central, choropleth when geo is central, pyramid when sex and ordered age coexist, grouped bar for comparison, stacked bar for composition, heatmap for dense two-way categorical grids, and small multiples when too many series would clutter one view.[^2][^1]

## Decision rules

| Condition | Primary | Complementary | Default controls |
| :-- | :-- | :-- | :-- |
| `geo present` + `single time point or selected time` [^2][^1] | Choropleth map [^2] | Ranked bar for exact comparison [^2] | Time picker only; geo level auto-picked from highest readable level [^1] |
| `sex present` + `ordered age groups present` [^4][^1] | Population pyramid [^4] | Line or small multiples if time matters [^2] | No visible toggle unless multiple statuses/measures exist [^4][^2] |
| `time present` + `1 compare dim` + `<= 6 series` [^2] | Line [^2] | Table [^2] | Series auto-limited to top lines, others searchable [^2] |
| `time present` + `7–20 series` [^2] | Small multiples [^2] | Ranked bar at latest period [^2] | None by default beyond period range [^2] |
| `1 compare dim` + `< 10 categories` [^2] | Grouped bar for comparison, stacked bar for composition [^2] | Table with heat shading [^2] | None [^2] |
| `2 categorical axes` + moderate cardinality [^2] | Heatmap or matrix bubble [^2] | Sorted bar on selected row/column [^2] | One axis swap action at most [^2] |
| `mixed family dimension` such as sex/age/education/region in one field [^6] | Ranked bar after semantic family split [^6][^1] | Heatmap by family over time [^6] | One required “Compare by” switch [^6] |

A compact implementation sketch would be: `if sex && age_ordered -> pyramid; else if geo && time_count==1 -> map; else if geo && selected_time -> map; else if time && compare_card<=6 -> line; else if time && compare_card<=20 -> small_multiples; else if dims2_dense -> heatmap; else if compare_card<10 && part_to_whole -> stacked_bar; else grouped_bar`.[^1][^2]
Add a penalty layer so the engine avoids maps for tiny geographies without shapes, avoids stacked bars for many segments, avoids multi-line charts above about six visible series, and avoids Sankey unless the dataset is truly a source-target flow table.[^2][^1]

## Wireframe spec

Desktop layout should be: top header with dataset title and summary, left collapsible filter rail, center main visualization area, right metadata/notes rail, and a bottom panel with `Chart | Table | Metadata` tabs. [^1][^2]
The top strip should show breadcrumbs as removable chips for current selections, plus only three persistent controls: `Period`, `Measure` when relevant, and `Compare by` only when the dataset has multiple valid semantic families.[^5][^6][^1]
The left rail should hold search-first controls for large dimensions, top-$N$ presets, and advanced mappings for `Series` or `Small multiples`, but those should stay collapsed until the user explicitly opens them.[^1][^2]

A concrete page skeleton: `Header / Selection chips / Main chart / Secondary chart strip / Data table toggle / Metadata drawer`.[^1]
Inside the main chart card, place a title, one-sentence annotation, chart canvas, and a tiny action row with `Drill down`, `Show ranking`, `Download`, and `Reset`.[^2][^1]
Below it, add one secondary card only when it adds a different reading of the same slice, such as map plus ranked bar or pyramid plus age-group trend, because redundancy is useful only when it improves precision or orientation.[^4][^3][^2]

## Interaction rules

Clicks should refine the cube instead of opening new forms: clicking a county filters the table and trend below, clicking a legend isolates a series, and clicking an age bar in a pyramid pins that age group everywhere else.[^2][^1]
Hover should reveal value, rank, unit, and flag metadata, while breadcrumb chips provide the main visible state model and make the interface understandable without a complex filter panel.[^1][^2]
When the dataset is ambiguous, show one explicit selector labeled by meaning, not by schema, such as `Compare regions / sexes / ages / education`, because the mixed comparison field in TCJ0331 would otherwise create poor defaults.[^6][^1]

Default reductions should be automatic: latest period selected, totals preferred, top $N$ values shown, `Other` aggregated, and sparse combinations suppressed unless the user asks for full detail in the table.[^2][^1]
If there is no time dimension, switch the page into cross-sectional mode; if there is no geo dimension, remove map affordances entirely; if there are multiple measures, surface a measure chip prominently because units change the valid chart choices.[^5][^1]
For mobile, collapse the side rails into bottom sheets and keep only the main chart, chips, and table tab visible by default.[^2]

## Applied defaults

For **TUR105G**, the page should open on the latest month with a choropleth by region, a secondary ranked bar for the same slice, and one hidden drill path from macroregion to county, because the file combines accommodation type, tourist type, geography, month, and counts.[^3]
For **TLS1112**, open directly on a population pyramid for the latest year and default poverty status, with a secondary line strip by age group over time, because the file has sex, ordered age groups, status, year, and percentages.[^4]
For **FOM121B**, open on a heatmap of age by occupation with male/female small multiples and a visible measure chip, because the file mixes counts, base salary, and realized income across age, occupation, sex, and year.[^5]

If you want a next step, the most useful one is a JSON-like configuration schema for this algorithm, so engineering can implement the rules without hard-coding dataset names.

<div align="center">⁂</div>

[^1]: chatgpt1.md

[^2]: perplexity1.md

[^3]: TUR105G.csv

[^4]: TLS1112.csv

[^5]: FOM121B.csv

[^6]: TCJ0331.csv

