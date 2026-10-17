"""The visible prose of the tool envelopes, in English and Romanian (AQ-04C).

A tool's `message`, its warnings' `message` and its recovery suggestions' `message` are
sentences for a person or a model. They follow the request's `lang` and nothing else does:
reason and warning codes, subjects, dataset ids, filters, values, definitions, call arguments
and every number are the same in both languages. A text that carries one of these takes it as a
placeholder (`{col}`, `{code}`, `{n}`) and never translates it.

One catalogue instead of branching in the tool code: `t(lang, key, **values)`. Keys are
`<area>.<name>`; both languages must define the same keys with the same placeholders
(tests/test_aq04c_messages.py). A text already localized in its own module (`recipe._TX`,
`links._TX`, `contract._SCOPE_TEXT`, the dataset notes) stays there. Messages that come from a
shared service rather than a tool (`data_query.QueryError`, request validation) are passed
through as the service wrote them, except the four `QueryError` texts a tool user meets
(`contract._QUERY_ERRORS`) and the frame of an argument-validation message.

English is the reference wording the tests pin; an unknown `lang` falls back to Romanian like
every other `_TX` table in the tool layer.
"""
from __future__ import annotations


def tx(lang: str) -> dict:
    return TEXT.get(lang) or TEXT["ro"]


def t(lang: str, key: str, **values) -> str:
    """The text `key` in `lang`, with `values` filled in (KeyError for an unknown key)."""
    text = tx(lang)[key]
    return text.format(**values) if values else text


TEXT = {
    "en": {
        # ---- contract / registry / gate
        "contract.generation_unverified": "The served data generation is {status}; analytical "
                                          "results cannot be certified until the deployment's "
                                          "generation manifest is present.",
        "contract.retry_generation": "Retry after the data generation is refreshed.",
        "contract.preview_shortened": "The preview was shortened to fit the response budget; the "
                                      "canonical selection and evidence links give the complete "
                                      "result.",
        "contract.read_dataset": "Read the dataset's columns, values and sub-datasets.",
        "contract.find_dataset": "Find the dataset code by concept.",
        "contract.filter_one": "Filter at least one dimension (e.g. a period or an area).",
        "contract.response_budget": "The result's required provenance does not fit the response "
                                    "budget; narrow the request (fewer columns, values, areas or "
                                    "periods).",
        "contract.response_budget_narrow": "Ask for fewer filter values, grouped columns or "
                                           "periods.",
        "registry.unknown_tool": "Unknown tool {tool!r}; available: {tools}.",
        "registry.not_object": "Arguments must be a JSON object.",
        "registry.not_json": "Arguments must be plain JSON (no NaN/Infinity).",
        "registry.too_big": "Arguments are {n} bytes; the limit is {max}. Ask for fewer values.",
        "registry.too_big_narrow": "Send fewer filter values or areas.",
        "registry.invalid": "Invalid arguments — {parts}. Correct them and call again.",
        "registry.unknown_argument": "unknown argument",
        "registry.failed": "The tool failed (reference {ref}); nothing was computed.",
        "registry.generation_changed": "The served data generation changed during this call; "
                                       "nothing from it is reported. Run the request again.",
        "registry.generation_retry": "Run the same request again on the new generation.",
        "gate.busy_rate": "The server is handling many requests; retry shortly.",
        "gate.busy_slot": "Another analysis is running; retry shortly.",
        "gate.retry_in": "Retry in about {s} second(s).",
        "gate.scan_unbounded": "could not be bounded",
        "gate.scan_over": "may read up to {est} rows (the public limit is {limit})",
        "gate.query_budget": "This selection {what}. Choose a narrower dataset (describe_dataset "
                             "lists sub-datasets, e.g. one county) or a reviewed recipe.",
        "gate.query_budget_describe": "See the dataset's sub-datasets and columns.",
        "gate.query_budget_narrow": "Choose a narrower selection.",
        "gate.timeout": "The analysis did not finish within {s} seconds and was stopped. Narrow "
                        "the selection (fewer areas, one period) or choose a smaller dataset.",
        "gate.timeout_narrow": "Filter an area or period, or pick a sub-dataset.",
        "contract.dataset_not_found": "Dataset {code} not found",
        "contract.no_data_file": "Dataset {code} has no data file — it may be published as "
                                 "sub-datasets.",
        "contract.filter_needed": "Dataset has {rows} rows. Please apply at least one filter to "
                                  "narrow results (max {max} rows returned).",
        "contract.unknown_column": "Invalid column: unknown column {col!r}",
        "contract.query_failed": "The query failed (reference {ref}).",
        # ---- query_data
        "query.empty_filter": "Empty value lists impose no constraint and were ignored: {cols}.",
        "query.raw_uncertified": "The served data generation is {status}; these raw observations "
                                 "are not certified against a generation manifest.",
        "query.more_values": ", … ({n} values)",
        "query.rows_one": "{n} row returned.",
        "query.rows_many": "{n} rows returned.",
        "query.raw_rows_one": "{n} raw observation row returned.",
        "query.raw_rows_many": "{n} raw observation rows returned.",
        "query.raw_not_total": " Raw observations are not a verified total.",
        "query.approximation_tail": " APPROXIMATION: unweighted mean of non-additive values, not "
                                    "an official rate.",
        "query.preview_tail": " This is a preview: more rows exist.",
        "query.no_rows": "The selection returned no rows; this is not a zero.",
        "query.no_rows_warning": "The data has no observations for this selection. Absence of a "
                                 "row is not the value zero.",
        "query.incomplete_domain": "This total covers only part of the domain ({desc}); it is not "
                                   "an all-ages / all-population total. Do not present it as one.",
        "query.partial_message": "Valid only for the covered part of the domain: {desc}. "
                                 "{message} It is not a complete-domain total.",
        "query.complete_alternative": "{alt} covers the whole domain of {cols} with the same "
                                      "columns: run the same selection there. This is a "
                                      "candidate, not a verified answer; its values and labels "
                                      "may differ.",
        "query.no_complete_alternative": "No related dataset with a verified complete domain was "
                                         "found. Quote the figure only for the covered range "
                                         "above, or choose another dataset with "
                                         "discover_indicators.",
        "query.unverified_domain": " Whether it covers the whole domain is unverified "
                                   "(provenance.scope).",
        "query.unverified_total": "This sum has unverified domain completeness. It is not a "
                                  "verified official total; preserve the source definition and "
                                  "scope.",
        "query.level_suffix": " (level {level})",
        "query.auto_pinned": "Pins applied automatically to avoid double-counting: {parts}. The "
                             "full list is in provenance.effective_selection.",
        "query.approximation": "APPROXIMATION: unweighted mean of non-additive values (rate, "
                               "index or average) because no aligned weights exist. It is not the "
                               "official or national rate; say so when quoting it.",
        "query.time_collapsed": "Values are aggregated across all periods of {col}; filter or "
                                "group by time for a single-period figure.",
        "query.mixed_grain": "{col} spans several grains (levels) on this axis; do not compare or "
                             "add values across levels.",
        "query.quality_grouped": "This file has repeated observation keys ({grain}) elsewhere; "
                                 "the requested slice was checked and has none.",
        "query.quality_raw": "DATA QUALITY: this dataset has repeated observation keys ({grain}); "
                             "raw rows may disagree with each other. Do not total or rank them.",
        "query.raw_rows": "Raw observations, not a verified total. Do not add them up by hand; "
                          "request a grouped selection (group_by) to get a policy-checked total.",
        "query.time_windowed": "Only the most recent periods were returned (row cap); filter "
                               "TIME_PERIOD to reach earlier periods.",
        "query.partial_period": "Period {period} was incomplete under the row cap and was dropped.",
        "query.preview": "More rows exist than were returned (the result was capped). Use filters "
                         "or the evidence links for the rest; a preview never establishes a total "
                         "or an exhaustive ranking.",
        "query.null_values": "{nulls} of {n} row(s) have no value (null: suppressed or "
                             "unavailable at the source). Null is not zero; do not include it in "
                             "sums.",
        "query.no_rows_for_value": "No rows for {col} = {absent} in this selection (no "
                                   "observation exists; that is not a zero).",
        "query.empty_fallback": "No rows match the requested values; nothing was substituted: no "
                                "other period, area or category stands in for the requested one.",
        "query.no_period_obs": "{col} {periods} has no observations",
        "query.data_covers": " (the data covers {first} to {last})",
        "query.list_periods": "List the periods the data actually has.",
        "query.value_missing": "{col} {values} does not exist in the data",
        "query.lookup_values": "Look up the exact {col} values the data has.",
        "query.each_exists": "each requested value exists, but no observation matches all of them "
                             "together",
        "query.check_one_filter": "Check one filter at a time (find_dimension_values lists the "
                                  "values); nothing was widened for you.",
        "query.no_rows_match": "No rows match: {parts}. Nothing was substituted: no other period, "
                               "area or category stands in for the requested one.",
        "query.dimension_suffix": " (dimension {col})",
        "query.refused": "The shared aggregation policy refused this selection ({reason}{where}); "
                         "no value was computed. Do not state a figure for it.",
        "query.pin_others": "Pin the other dimensions to explicit values or group by them so "
                            "nothing has to be combined.",
        "query.missing_total": "{col} = {shown} does not exist in the data of {code}: the source "
                               "export has no such Total row",
        "query.missing_total_meta": " although INS's metadata lists a Total option",
        "query.total_recipe_cross_check": "INS's own total is served by the reviewed recipe "
                                          "'{rid}' (published values, with a reconstruction only "
                                          "as a cross-check).",
        "query.without_pin": "Ask the policy for the same selection without the {col} pin: it "
                             "combines the remaining {col} values only if it can verify they are "
                             "a complete, non-overlapping partition. Candidate only: the sum may "
                             "still be refused and is not promised to be safe.",
        "query.list_exact": "List the exact {col} values the data has.",
        "query.nothing_substituted": ". Nothing was computed, and no other value was substituted.",
        "query.none_exist": "None of the requested {col} values ({wanted}) exists in the data of "
                            "{code}; nothing was computed and no other value was substituted.",
        "query.grain_conflicting": "This slice of {code} repeats the same observation key with "
                                   "different values (conflicting grain), so no single total or "
                                   "breakdown exists.",
        "query.grain_duplicate": "This slice of {code} repeats the same observation key "
                                 "(duplicate keys), so a total would count it twice.",
        "query.grain_unverified": "This slice of {code} is too large to verify as free of "
                                  "repeated observation keys, so no total was computed.",
        "query.grain_alternative": "{alt} has certified unique keys and the requested columns and "
                                   "values: run the same selection there. This is a candidate, "
                                   "not a verified answer; check its definition and scope.",
        "query.grain_with_alt": "{what} Nothing was summed. A related dataset can express the "
                                "selection: {alts} (a candidate, not a verified answer).",
        "query.grain_no_alt": "{what} Nothing was summed, and no related dataset with certified "
                              "unique keys and the requested columns was found. The rows of this "
                              "dataset must not be totalled or ranked by hand; choose another "
                              "dataset for this indicator.",
        "query.grain_narrow": "Filter the selection to one area or one period so the slice can be "
                              "checked, then ask again.",
        "query.find_another": "Find another dataset for this indicator.",
        "query.overlap": "The options of {col} overlap (several levels or grains, e.g. single "
                         "years and age bands), so adding them would count the same units more "
                         "than once. Nothing was summed; restrict {col} to one verified level.",
        "query.level_one": "the verified level '{name}' ({n} value)",
        "query.level_many": "the verified level '{name}' ({n} values)",
        "query.restrict_level": "Restrict {col} to {label}. Candidate: the policy still decides.",
        "query.group_by_level": "Group by {col}: the axis is limited to one verified level (the "
                                "default, not all {n}-value levels combined). Candidate.",
        "query.complete_child": "{child} is a related dataset whose {col} domain is complete and "
                                "non-overlapping: run the same selection there. Candidate, not a "
                                "verified answer.",
        "query.choose_one_level": "List the exact {col} values and choose ONE level (never all "
                                  "levels together).",
        "query.weights": "This measure is a rate, index or average: values of different "
                         "categories cannot be added, and no aligned weights exist for a weighted "
                         "mean. Nothing was combined. A labelled unweighted mean is available "
                         "only if the user accepts it explicitly.",
        "query.keep_on_axis": "Keep {cols} on the axis instead of combining it (one value per "
                              "category; nothing is averaged).",
        "query.pin_every_other": "Pin every other dimension to one explicit value "
                                 "(find_dimension_values lists them) or add it to group_by.",
        "query.ask_unweighted": "Ask the user whether an UNWEIGHTED mean of these values is "
                                "acceptable: it is a labelled approximation, not the official or "
                                "national rate. Only if they agree, repeat this call with "
                                "approximate=true.",
        "query.mixed_units": "{col} holds several measurement units and the selection does not "
                             "pin one, so values were not combined across units. Nothing was "
                             "computed.",
        "query.list_units": "List the units in {col}, then pin exactly one.",
        "query.filter_one_unit": "Filter {col} to exactly one unit and ask again.",
        "query.this_dimension": "this dimension",
        "query.total_mismatch": "INS's own published figures disagree: the parts of {col} do not "
                                "add up to INS's Total, so no summed value is reported.",
        "query.no_source_total": "The source has no Total row to check this summed series "
                                 "against, and the grouping is not verified, so the sum was "
                                 "withheld.",
        "query.total_unchecked": "This summed series has not been checked against INS's own Total "
                                 "(no check on record) and the grouping is not verified, so the "
                                 "sum was withheld.",
        "query.total_recipe": "INS's own published total is served by the reviewed recipe '{rid}'.",
        "query.total_alternative": "{alt} has certified unique keys, the requested columns and "
                                   "values, and the policy and INS-total checks do not withhold "
                                   "the same selection there: run it. This is a candidate, not a "
                                   "verified answer.",
        "query.explicit_slice": "Ask for an explicit slice (pin the dimensions to single values "
                                "or group by them) instead of a combined total.",
        "query.nothing_summed": "{which} Nothing was summed.",
        "query.schema_mismatch": "A dimension recorded for {code}{col} is not a column of its "
                                 "data file, so no selection can be aggregated safely.",
        "query.no_context": "The metadata of {code} is not usable for a safe aggregation, so no "
                            "total can be computed here.",
        "query.nothing_computed": "{what} Nothing was computed.",
        "query.col_suffix": " ({col})",
        "query.unverified_structure": "The options of {col} have no verified structure (they may "
                                      "nest or include totals), so combining them was refused. "
                                      "Nothing was summed.",
        "query.pin_one": "List the exact {col} values and pin ONE of them (or its Total).",
        "query.keep_col": "Keep {col} on the axis instead of combining it. Candidate.",
        "query.contains_aggregate": "The selected {col} values mix a Total with its own parts, "
                                    "which would count the same units twice. Nothing was summed; "
                                    "choose the Total alone or the parts alone.",
        "query.use_total": "Use the Total alone ({totals}).",
        "query.use_parts": "Use the parts alone; the policy still decides whether they can be "
                           "combined. Candidate.",
        "query.list_values": "List the exact {col} values.",
        "query.describe_rec": "Read the dataset's columns, values, sub-datasets and notes.",
        "query.narrowing": "Narrow the selection (filter a period or an area, or group by fewer "
                           "columns) to see the remaining rows; a preview is not the whole result.",
        "query.try_narrower": "Try {dataset} with a narrower selection.",
        "query.labels_omitted": "Display labels were omitted to fit the response budget for "
                                "column(s): {subjects}. The values are the exact stored values.",
        "query.filters_summarized": "Long effective filter lists were summarized to fit the "
                                    "response budget for: {subjects}; the full lists are "
                                    "reproduced by repeating the canonical selection.",
        # ---- discover_indicators / describe_dataset / find_dimension_values
        "discover.generation_manifest": "The data generation manifest is {status}: this metadata "
                                        "is read from the served files and is not certified to a "
                                        "generation.",
        "discover.note.place_not_in_dataset": "A named place was not found among this dataset's "
                                              "REF_AREA values; it was not applied.",
        "discover.note.place_level_unavailable": "This indicator has no data at the named place's "
                                                 "level (county); the place was not applied.",
        "discover.freq.annual": "annual",
        "discover.freq.quarterly": "quarterly",
        "discover.freq.monthly": "monthly",
        "discover.parent_level": "parent",
        "discover.period_outside": "{year} is outside the data of {code} ({span}); the year was "
                                   "not applied and nothing was substituted.",
        "discover.period_not_single": "{code} is {frequency}: {year} is not one period. List its "
                                      "periods (find_dimension_values, query {query!r}) and "
                                      "filter exact values.",
        "discover.period_gap": "{year} is not an actual period of {code} ({span}, with gaps); the "
                               "year was not applied and nothing was substituted.",
        "discover.no_data_file": "{code} has no data file of its own; it is published as "
                                 "sub-datasets.",
        "discover.grain_conflicting": "{code} has rows with the same key and different values in "
                                      "the generation audit: grouped totals are refused. Not a "
                                      "query target.",
        "discover.grain_duplicate_keys": "{code} has rows with the same key in the generation "
                                         "audit: grouped totals are refused. Not a query target.",
        "discover.domain_incomplete": "Restricted domain: {desc}. Not an all-population answer.",
        "discover.aggregation_unavailable": "The shared aggregation policy refuses to collapse "
                                            "the other dimensions here ({reason}{column}): choose "
                                            "explicit values (describe_dataset) or use a reviewed "
                                            "recipe.",
        "discover.grain_unverified": "Grain is not certified by the generation evidence; "
                                     "query_data checks the selected slice.",
        "discover.latest_period": "'Latest' was resolved to the last period with data in {code}: "
                                  "{period}.",
        "discover.recipe_period": "{year} is outside the years both sources share{span}; the year "
                                  "was not applied and nothing was substituted (a recipe without "
                                  "a year would answer for the latest common year).",
        "discover.recipe_place": "{absent} is not among the REF_AREA labels of {dataset}, which "
                                 "the recipe matches exactly (accents, case and spacing aside). "
                                 "Look the label up (area_lookup) before running it; nothing "
                                 "similar was substituted.",
        "discover.recipe_grain": "A source of this recipe has grain problems in the generation "
                                 "audit; run_recipe may refuse or exclude entities.",
        "discover.recipe_domain": "A recipe's eligibility and exclusions are in its run_recipe "
                                  "result.",
        "discover.level_differs": "No queryable source at the requested level ({wanted}); this is "
                                  "the {level} source and cannot answer a question about a "
                                  "smaller area.",
        "discover.source_total": "Reviewed route to the county total.",
        "discover.no_verified_candidate": "No candidate is a ready data query (see each "
                                          "candidate's notes); next_call reads the first "
                                          "candidate's dimensions so explicit values can be "
                                          "chosen.",
        "discover.no_specific_wording": "No restated question selects this choice on its own; ask "
                                        "the user to say it in their own words.",
        "discover.resolution_failed": "This choice could not be resolved to a call; use its "
                                      "restatement (next_call).",
        "discover.no_match_choice": "The restated question no longer reaches this definition.",
        "discover.no_call": "No validated data call exists for this definition and question.",
        "discover.county_label": "County: {names}",
        "discover.county_description": "Whole-county figures (the series this indicator has); not "
                                       "the city alone.",
        "discover.all_counties_label": "All counties",
        "discover.all_counties_description": "One row per county; pick the place afterwards.",
        "discover.city_series_missing": "The reviewed city population series is not in this data "
                                        "generation. County data was not substituted.",
        "discover.recipe_unavailable": "The per-resident recipe is unavailable; no raw count was "
                                       "substituted.",
        "discover.constraint_withheld": "A constraint of the question is not applied by "
                                        "discovery, so no data call that ignores it is suggested "
                                        "here.",
        "discover.constraint_filter": "Read the dimensions and filter explicit values; if this "
                                      "dataset cannot express it, say so.",
        "discover.constraint_recipe": "This recipe cannot take it; say so.",
        "discover.kind.sex": "sex",
        "discover.kind.age": "age",
        "discover.kind.denominator": "denominator",
        "discover.kind.geography": "geography",
        "discover.constraint_warning": "The question asks for {kind} ({words}) but discovery did "
                                       "not apply it; the candidates do not answer it as they "
                                       "stand. Filter explicit values after describe_dataset, or "
                                       "tell the user it was not applied. Nothing was dropped "
                                       "silently.",
        "discover.assumed_cities": "Definition assumed for cities: {label} ({note}). Resident "
                                   "population is not available for cities in the reviewed "
                                   "series; state the definition explicitly.",
        "discover.assumed": "Definition assumed: {label}. State it explicitly; alternatives "
                            "remain available.",
        # ---- discovery: one county narrows a city ranking; a level picks a definition
        "discover.place_filter": "Cities in {county} only: every eligible city of that county is "
                                 "ranked before the top K is cut, and the eligible and "
                                 "outside-class counts are for that county alone.",
        "discover.assumed_level": "Definition assumed: {label}, taking the question at the "
                                  "{level} level. {missing}State the definition explicitly to use "
                                  "another; alternatives remain available.",
        "discover.level_missing": "{name} has no {level}-level series in the reviewed catalogue "
                                  "(it covers: {covers}). ",
        "discover.level_county": "county",
        "discover.level_region": "region",
        "discover.level_macroregion": "macroregion",
        "discover.level_national": "national",
        "discover.generic_word": "'{matched}' is a generic word: it can mean {names}.",
        "discover.generic_single": "'{matched}' is a generic word; only one reviewed definition "
                                   "exists for it.",
        "discover.city_not_county": "The question names a city in county {name}; TEMPO publishes "
                                    "this indicator by county. County figures are not the city's.",
        "discover.msg_definition": "The wording is ambiguous between {n} official definitions: "
                                   "{names}. No figure or dataset was chosen: ask the user to "
                                   "pick one. Only after they have picked, run that choice's "
                                   "action (status ready); its next_call restates the question "
                                   "with that definition.",
        "discover.the_place": "The place",
        "discover.msg_place": "{place} reads as a city, but this indicator is published by "
                              "county. Choose the county series or all counties; city-level "
                              "figures are not resolved by this tool.",
        "discover.use_choice": "Use: {label}",
        "discover.no_match": "No reviewed concept or dataset matched the query.",
        "discover.rephrase": "Rephrase with the indicator's name and, optionally, a level (e.g. "
                             "'pe județe') or a county and year. Nothing was substituted.",
        "discover.msg_ok": "{n} reviewed concept(s) with candidate datasets and {m} family search "
                           "hit(s). Candidates carry their grain status and any proven scope "
                           "restriction (domain.complete null = not verified); families are "
                           "unverified search hits.",
        "discover.msg_unapplied": " Not applied from the question: {items}; see warnings.",
        "discover.families_note": "Full-text search hits grouped by indicator family: candidates "
                                  "to read with describe_dataset, not verified answers. "
                                  "time_range is the dataset profile's, not checked against the "
                                  "data.",
        "discover.search_degraded": "Full-text search is unavailable; families are matched on "
                                    "dataset names only.",
        "discover.response_shortened": "Optional detail was cut to fit the response budget; call "
                                       "describe_dataset for the rest.",
        "describe.unknown": "Unknown dataset {code!r}.",
        "describe.find": "Find the dataset code by concept or topic.",
        "describe.code_shape": "Dataset codes look like POP105A_judete_grupe; copy one from "
                               "discover_indicators or describe_dataset.",
        "describe.total_note": "The metadata lists {names} for {col}, but the data has no such "
                               "value (INS's own total was not downloaded). Do not filter this "
                               "dimension to Total; a sum over its values is only valid where the "
                               "aggregation policy allows it.",
        "describe.no_values": "No actual values are available (no data file or unreadable column).",
        "describe.no_period_file": "No data file: the actual period range is unknown.",
        "describe.period_unreadable": "The period column could not be read.",
        "describe.metadata_range": "Metadata lists {mfirst}–{mlast} ({options} periods); the data "
                                   "has {first}–{last} ({periods} periods with observations). The "
                                   "data bounds are authoritative.",
        "describe.no_data_file": "This dataset has no data file of its own",
        "describe.no_data_file_splits": ": it is published as the sub-datasets in `splits`; "
                                        "describe or query one of them.",
        "describe.grain_conflicting": "The generation audit found rows with the same key and "
                                      "different values: grouped totals of this dataset are "
                                      "refused.",
        "describe.grain_duplicate_keys": "The generation audit found rows with the same key: "
                                         "grouped totals of this dataset are refused.",
        "describe.examples_note": "Examples are a sample of actual values, not an exhaustive "
                                  "allowlist: use each dimension's `lookup` "
                                  "(find_dimension_values) to search or page all of them, and use "
                                  "the exact value in filters.",
        "describe.no_period_data": "no period data",
        "describe.message": "{code}: {n} dimension(s), {span}",
        "describe.message_frequency": " ({frequency})",
        "describe.message_splits": ", {n} sub-dataset(s)",
        "values.no_match": "No value of {col} contains {query!r} (accent- and case-insensitive "
                           "substring match). Try fewer letters, or list the values without a "
                           "query.",
        "values.list_all": "List the values without a query.",
        "values.none": "{col} has no values in the data.",
        "values.past_end": "offset {offset} is past the last of {total} matching values.",
        "values.periods_with_data": " Periods with data: {first}–{last}.",
        "values.message": "{total} matching value(s) of {col}; showing {first}–{last}",
        "values.next_offset": "; next_offset={n}",
        "values.use_exact": ". Use the exact `value` in filters.",
        "values.obs_value": "OBS_VALUE is the observation value, not a dimension: it has no "
                            "selectable values.",
        "values.unknown_column": "{code} has no dimension column {col!r}.",
        "values.its_columns": " Its dimension columns are: {cols}.",
        # ---- policy / rank_entities / compare_periods
        "policy.city_change_unsupported": "City-only change rankings are not yet supported. "
                                          "Specify a county change comparison or a city "
                                          "population ranking for one year.",
        "policy.unsupported_measure": "This question needs a different denominator, density or "
                                      "correlation operation. No count or built-up-area ratio was "
                                      "substituted. Ask separately for the population ranking or "
                                      "the reviewed overnight-stays-per-resident recipe.",
        "policy.city_not_population": "No reviewed city-level series answers this question: the "
                                      "only one is the annual population by legal domicile, as a "
                                      "ranking. County data was not substituted.",
        "policy.city_resident": "No reviewed annual resident-population city ranking is available "
                                "here. The locality series counts legal domicile; explicitly ask "
                                "for domicile population to use it. County data was not "
                                "substituted.",
        "policy.city_not_configured": "No reviewed city population series is configured here. "
                                      "County data was not substituted.",
        "policy.recipe_unavailable": "The per-resident recipe is unavailable; no raw count was "
                                     "substituted.",
        "policy.top_k_max": "At most {max} ranked entities can be returned; ask for a smaller top "
                            "K.",
        "policy.top_k_min": "A ranking needs a top K of at least 1.",
        "policy.city_change_historical": "City change rankings use the current catalogue of "
                                         "municipalities and towns (INS GOS102A): a question that "
                                         "needs historical city status or constant boundaries "
                                         "cannot be answered, because no reviewed source records "
                                         "them.",
        "policy.city_change_years": "City change rankings need exactly two exact years (for "
                                    "example between 2015 and 2020); no latest, nearby or default "
                                    "year is assumed.",
        "policy.city_change_direction": "City change rankings need a stated direction: growth or "
                                        "decline. Absolute change or both directions in one "
                                        "question are not ranked.",
        "policy.city_change_least": "City change rankings follow the stated direction (growth: "
                                    "largest first; decline: most negative first); 'bottom', "
                                    "'smallest' or 'lowest' wording is ambiguous for changes and "
                                    "is not interpreted.",
        "policy.city_change_note": "A city change ranking covers the municipalities and towns in "
                                   "the referenced catalogue (INS GOS102A, SIRUTA keys), not "
                                   "communes. Membership does not prove historical city status or "
                                   "unchanged boundaries.",
        "rank.identity_ambiguous_labels": "The city catalogue repeats a SIRUTA key with different "
                                          "labels.",
        "rank.catalogue_unavailable": "INS GOS102A's SIRUTA municipality/town catalogue is "
                                      "unavailable.",
        "rank.siruta_required": "Locality values must carry exact SIRUTA keys; names are not "
                                "joined.",
        "rank.siruta_repeated": "One city SIRUTA key appears under multiple entities.",
        "rank.additive_only": "This ranking supports additive measures only; use a reviewed "
                              "recipe for rates.",
        "rank.annual_required": "An annual observation period is required.",
        "rank.use_year": "Use year instead of a time filter.",
        "rank.entity_columns": "entity_columns must name existing non-time dimensions.",
        "rank.key_too_long": "The full entity key exceeds eight columns.",
        "rank.cities_need_locality": "Cities require REF_AREA_2 with SIRUTA locality keys.",
        "rank.no_year": "No observations for {year}; no nearby year was substituted.",
        "rank.query_refused": "The shared query refused the ranking input.",
        "rank.source_incomplete": "No ranking was computed from a capped or windowed input; "
                                  "narrow the selection.",
        "rank.approximation": "An approximate aggregation is not a ranking input.",
        "rank.mixed_levels": "Choose a single entity level before ranking.",
        "rank.empty_key": "An entity has an empty key; no ranking was computed.",
        "rank.duplicate_key": "More than one value exists for an entity; no ranking was computed.",
        "rank.classification": "Cities are municipalities and towns in INS GOS102A's SIRUTA "
                               "catalogue; historical changes of UAT class are not tracked.",
        "rank.entities_excluded": "{n} entities lack a finite observation; they were not assigned "
                                  "zero.",
        "rank.unverified_total": "The collapsed domain's completeness is unverified; do not claim "
                                 "an official complete total.",
        "rank.message": "Top {k} of {n} eligible entities in {year}; ranked before limiting "
                        "output. {scope}",
        "changes.evidence_link": "Get the link to the complete ranking and the full exclusion "
                                 "list (evidence bundle).",
        "changes.tail": "Rank is the ordinal position under the requested metric and order, not a "
                        "claim of statistical significance.",
        "changes.class_tail": "Cities are the catalogue's municipalities and towns (INS GOS102A); "
                              "membership does not prove historical city status or unchanged "
                              "boundaries.",
        "changes.who_entity": "entity",
        "changes.who_class": "entity of the class 'municipalities and towns in the referenced "
                             "catalogue'",
        "changes.none_ranked": "No entity has a finite value at both endpoints of any interval, "
                               "so nothing was ranked. The exclusions say why; no gap was filled "
                               "with zero.",
        "changes.none_ranked_cities": "No municipality or town in the referenced catalogue has a "
                                      "finite value at both endpoints of any interval, so nothing "
                                      "was ranked ({outside} source entities are outside that "
                                      "class). No gap was filled with zero.",
        "changes.source_unit": "the source unit",
        "changes.ranked": "Per-entity change in {unit} for {n} interval(s) of {dataset}: every "
                          "eligible {who} was ranked ({eligible} ranked) and {returned} row(s) "
                          "are shown.",
        "changes.outside_class": " {outside} source entities outside the catalogue (communes, "
                                 "totals) were not ranked.",
        "changes.pairs_excluded": " {excluded} entity-interval pair(s) were excluded and are "
                                  "listed.",
        "changes.restricted": " Restricted domain: {desc}.",
        "changes.preview_shortened": "The preview was shortened to fit the response budget; the "
                                     "evidence bundle has the complete ranking and exclusion list.",
        "period.duplicate_keys": "More than one value for the same entity and year came back from "
                                 "the source query, so no single endpoint value exists. No change "
                                 "was computed.",
        "period.duplicate_keys_narrow": "Pin the dimension that repeats the key with filters, or "
                                        "compare a different dataset.",
        "period.read_periods": "Read the dataset's periods and frequency.",
        "period.too_many_periods": "{code} has more than {max} distinct period labels; only exact "
                                   "annual periods are supported.",
        "period.non_annual": "{code} has non-annual period values (e.g. {examples}); "
                             "compare_periods supports exact annual periods only, not monthly, "
                             "quarterly or mixed series.",
        "period.year_two_ways": "{code} labels the year {year} in more than one way ({labels}); "
                                "the periods cannot be matched exactly.",
        "period.no_periods": "{code} has no period values.",
        "period.a_dimension": "a dimension",
        "period.native.overlapping_levels": "{col} mixes levels that overlap (for example "
                                            "counties with regions, or single years with age "
                                            "bands); no single total or ranking exists until one "
                                            "level is chosen.",
        "period.native.unverified_structure": "The structure of {col} is not verified, so the "
                                              "source cannot say how its options combine.",
        "period.native.contains_aggregate": "{col} contains a total next to its parts; combining "
                                            "them would double count.",
        "period.native.label_hierarchy": "{col} encodes a hierarchy in its labels; summing it "
                                         "would double count.",
        "period.native.declared_partition_invalid": "{col} is not a valid disjoint partition.",
        "period.native.source_total_mismatch": "INS's own options of {col} do not add up to INS's "
                                               "total, so the dimension is not summed.",
        "period.native.mixed_units": "{col} has several units; values in different units are "
                                     "never combined.",
        "period.native.slice_value_missing": "A requested value of {col} is not in the data.",
        "period.native.conflicting_grain": "The selected rows repeat a full key with different "
                                           "values, so no single value exists.",
        "period.native.duplicate_keys": "The selected rows repeat a full key, so a sum would "
                                        "count it twice.",
        "period.native.grain_unverified": "The grain of the selected rows could not be verified.",
        "period.native.schema_mismatch": "The dataset's recorded dimension {col} is not in its "
                                         "data file.",
        "period.native.missing_weights": "The measure cannot be combined without weights.",
        "period.native.no_aggregation_context": "The dataset's aggregation rules are unavailable.",
        "period.native.default": "The shared aggregation policy refused this selection ({reason}).",
        "period.no_change": "No change was computed: {text}",
        "period.list_pin": "List the actual values of {col}, then pin it to one value or one "
                           "level with filters.",
        "period.read_dims_grain": "Read the dataset's dimensions, levels and grain status.",
        "period.pop_domicile": "The source defines this as the domicile (domiciliu) population, "
                               "which is not a count of residents.",
        "period.pop_resident": "The source defines this as the resident (usual residence) "
                               "population.",
        "period.pop_both": "The source text names both domicile and usual residence; check which "
                           "one this series counts.",
        "period.pop_unsaid": "The source definition does not say whether it counts domicile or "
                             "usual residence; do not read it as a resident count.",
        "period.class_warning": "Cities are municipalities and towns in the referenced catalogue "
                                "(INS GOS102A, SIRUTA keys). Membership does not prove historical "
                                "city status or unchanged boundaries; places outside the "
                                "catalogue (communes, totals) were not ranked.",
        "period.pairs_not_ranked": "{total} entity-interval pair(s) were not ranked ({reasons}); "
                                   "they are listed per interval, never filled with zero.",
        "period.boundary": "Stable labels or codes do not prove unchanged territory: boundary "
                           "changes, mergers and splits between the endpoint years are not "
                           "tracked, so a change can reflect territory as well as real change.",
        "period.inside_interval": "Inside the compared interval {hit}: {text}",
        "period.unsupported_measure": "{code} is classified as a {measure} measure (unit type "
                                      "{unit_type}): rates, means, indices and unknown units are "
                                      "not compared here, because the change of such a value has "
                                      "no single definition. A reviewed recipe may exist.",
        "period.non_additive": "non-additive",
        "period.unknown_unit_type": "unknown",
        "period.find_recipe": "Look for a reviewed recipe or indicator for this measure.",
        "period.no_time": "{code} has no time dimension, so there are no annual endpoints.",
        "period.read_dims": "Read the dataset's dimensions.",
        "period.filter_is_period": "Invalid filters: {col} is the period column; periods come "
                                   "from the intervals.",
        "period.entity_is_period": "Invalid entity_columns: {col} is the period column, not an "
                                   "entity.",
        "period.unknown_entity_column": "Invalid entity_columns: unknown column {col!r}",
        "period.year_absent": "Year {years} has no observations in {code}; the data covers "
                              "{first} to {last}. No nearby year was substituted.",
        "period.list_values": "List the actual values of {col}.",
        "period.source_capped": "The source query for the endpoint years is larger than the "
                                "{cap}-row cap (or was windowed), so the entity set is "
                                "incomplete. No ranking was computed from a capped input.",
        "period.source_capped_narrow": "Filter an entity column (for example one county) or pin "
                                       "other dimensions so the endpoint table fits the cap.",
        "period.approximation": "An approximate (unweighted) aggregation is not used for period "
                                "changes.",
        "period.mixed_levels": "{col} mixes levels that overlap (for example counties with "
                               "regions), so ranking its values would compare an area with its "
                               "own parts. Choose one level.",
        "period.list_one_level": "List the actual values of {col}, then filter to one level's "
                                 "values.",
        "period.read_levels": "Read the dataset's dimensions and levels.",
        "period.values_missing": "Requested value(s) of {col} are not in the data: {values}.",
        "period.no_observations": "The selection has no observations at the endpoint years.",
        "period.unexpected_shape": "The source query returned an unexpected shape (reference "
                                   "{ref}); nothing was computed.",
        "period.unexpected_period": "The source query returned an unexpected period (reference "
                                    "{ref}); nothing was computed.",
        "period.empty_key": "Some rows have an empty component in the entity key, so those "
                            "entities cannot be identified.",
        "period.full_key": "Compare with the full key ({cols}) so same-named places stay separate.",
        "period.identity_ambiguous": "{n} requested {requested} value(s), e.g. {example!r}, occur "
                                     "under several {added} values ({parents}); a name alone does "
                                     "not identify a place. Include {added} in entity_columns.",
        # ---- run_recipe
        "recipe.preview_shortened": "The preview was shortened to fit the response budget "
                                    "(exclusion sample, aggregate cells or ranking rows); the "
                                    "exclusion counts and the canonical selection give the "
                                    "complete result.",
        # ---- Ask (agent.py, ask_present.py)
        "agent.tool_budget": "Not executed: the tool-call limit was reached. Answer from the "
                             "results you have.",
        "agent.deadline": "Not executed: the time limit was reached. Answer from the results you "
                          "have.",
        "agent.invalid_arguments": "The tool arguments were cut off or were not a JSON object; "
                                   "call the tool again with complete arguments.",
        "agent.repeated": "This exact request was already made this turn and refused; its outcome "
                          "and recovery candidates are repeated, not re-run. Narrow or change the "
                          "request.",
        "agent.cancelled": "Not executed: the request was stopped.",
        "agent.tool_failed": "The tool failed; nothing was computed.",
        "agent.limit.iterations": "Reached the model-call limit",
        "agent.limit.tools": "Reached the tool-call limit",
        "agent.limit.deadline": "Reached the time limit",
        "agent.limit.output_budget": "Reached the output allowance",
        "agent.limit_stopped": " before a final answer; the result is partial.",
        "agent.limit_forced": " before the exploration finished; the answer is partial.",
        "agent.provider_failed": "The model provider failed ({code}) before a final answer; the "
                                 "result is partial.",
        "agent.ranking_hidden": "An unranked query preview was hidden: it does not answer the "
                                "requested ranking.",
        "agent.values_withheld": "Answer withheld: it stated figures but no data query succeeded.",
        "agent.numbers_not_found": "Numbers not found in any query result (derived or "
                                   "unverified): {numbers}",
        "agent.claim_withheld": "Answer withheld: explicit unit or period contradicts the cited "
                                "result.",
        "present.pairs_excluded": "{n} entity-interval pair(s) were excluded from the ranking "
                                  "(see the evidence link for the list).",
    },
    "ro": {
        # ---- contract / registry / gate
        "contract.generation_unverified": "Generația de date servită este {status}; rezultatele "
                                          "analitice nu pot fi certificate până când manifestul "
                                          "de generație al instalării nu este prezent.",
        "contract.retry_generation": "Încearcă din nou după ce generația de date a fost "
                                     "reîmprospătată.",
        "contract.preview_shortened": "Previzualizarea a fost scurtată ca să încapă în bugetul "
                                      "răspunsului; selecția canonică și linkurile de dovezi dau "
                                      "rezultatul complet.",
        "contract.read_dataset": "Citește coloanele, valorile și subseturile setului de date.",
        "contract.find_dataset": "Găsește codul setului de date după concept.",
        "contract.filter_one": "Filtrează cel puțin o dimensiune (de ex. o perioadă sau o zonă).",
        "contract.response_budget": "Proveniența obligatorie a rezultatului nu încape în bugetul "
                                    "răspunsului; restrânge cererea (mai puține coloane, valori, "
                                    "zone sau perioade).",
        "contract.response_budget_narrow": "Cere mai puține valori de filtru, coloane grupate sau "
                                           "perioade.",
        "registry.unknown_tool": "Instrument necunoscut {tool!r}; disponibile: {tools}.",
        "registry.not_object": "Argumentele trebuie să fie un obiect JSON.",
        "registry.not_json": "Argumentele trebuie să fie JSON simplu (fără NaN/Infinity).",
        "registry.too_big": "Argumentele au {n} octeți; limita este {max}. Cere mai puține valori.",
        "registry.too_big_narrow": "Trimite mai puține valori de filtru sau zone.",
        "registry.invalid": "Argumente invalide — {parts}. Corectează-le și apelează din nou.",
        "registry.unknown_argument": "argument necunoscut",
        "registry.failed": "Instrumentul a eșuat (referință {ref}); nu s-a calculat nimic.",
        "registry.generation_changed": "Generația de date servită s-a schimbat în timpul acestui "
                                       "apel; nimic din el nu este raportat. Repetă cererea.",
        "registry.generation_retry": "Repetă aceeași cerere pe noua generație.",
        "gate.busy_rate": "Serverul procesează multe cereri; încearcă din nou în scurt timp.",
        "gate.busy_slot": "O altă analiză este în curs; încearcă din nou în scurt timp.",
        "gate.retry_in": "Încearcă din nou peste aproximativ {s} secundă(e).",
        "gate.scan_unbounded": "nu a putut fi delimitată",
        "gate.scan_over": "poate citi până la {est} rânduri (limita publică este {limit})",
        "gate.query_budget": "Această selecție {what}. Alege un set de date mai restrâns "
                             "(describe_dataset listează subseturile, de ex. un județ) sau o "
                             "rețetă revizuită.",
        "gate.query_budget_describe": "Vezi subseturile și coloanele setului de date.",
        "gate.query_budget_narrow": "Alege o selecție mai restrânsă.",
        "gate.timeout": "Analiza nu s-a încheiat în {s} secunde și a fost oprită. Restrânge "
                        "selecția (mai puține zone, o singură perioadă) sau alege un set de date "
                        "mai mic.",
        "gate.timeout_narrow": "Filtrează o zonă sau o perioadă ori alege un subset.",
        "contract.dataset_not_found": "Setul de date {code} nu a fost găsit",
        "contract.no_data_file": "Setul de date {code} nu are fișier de date — poate fi publicat "
                                 "ca subseturi.",
        "contract.filter_needed": "Setul de date are {rows} rânduri. Aplică cel puțin un filtru "
                                  "ca să restrângi rezultatele (cel mult {max} rânduri returnate).",
        "contract.unknown_column": "Coloană invalidă: coloană necunoscută {col!r}",
        "contract.query_failed": "Interogarea a eșuat (referință {ref}).",
        # ---- query_data
        "query.empty_filter": "Listele goale de valori nu impun nicio constrângere și au fost "
                              "ignorate: {cols}.",
        "query.raw_uncertified": "Generația de date servită este {status}; aceste observații "
                                 "brute nu sunt certificate printr-un manifest de generație.",
        "query.more_values": ", … ({n} valori)",
        "query.rows_one": "{n} rând returnat.",
        "query.rows_many": "{n} rânduri returnate.",
        "query.raw_rows_one": "{n} rând de observații brute returnat.",
        "query.raw_rows_many": "{n} rânduri de observații brute returnate.",
        "query.raw_not_total": " Observațiile brute nu sunt un total verificat.",
        "query.approximation_tail": " APROXIMARE: media neponderată a unor valori neaditive, nu o "
                                    "rată oficială.",
        "query.preview_tail": " Aceasta este o previzualizare: există mai multe rânduri.",
        "query.no_rows": "Selecția nu a returnat niciun rând; aceasta nu este o valoare zero.",
        "query.no_rows_warning": "Datele nu au observații pentru această selecție. Absența unui "
                                 "rând nu înseamnă valoarea zero.",
        "query.incomplete_domain": "Acest total acoperă doar o parte din domeniu ({desc}); nu "
                                   "este un total pe toate vârstele / pe întreaga populație. Nu "
                                   "îl prezenta ca atare.",
        "query.partial_message": "Valabil doar pentru partea acoperită a domeniului: {desc}. "
                                 "{message} Nu este un total pe domeniul complet.",
        "query.complete_alternative": "{alt} acoperă întregul domeniu al {cols} cu aceleași "
                                      "coloane: rulează aceeași selecție acolo. Este un candidat, "
                                      "nu un răspuns verificat; valorile și etichetele pot diferi.",
        "query.no_complete_alternative": "Nu a fost găsit niciun set de date înrudit cu domeniu "
                                         "complet verificat. Citează cifra doar pentru intervalul "
                                         "acoperit de mai sus sau alege alt set de date cu "
                                         "discover_indicators.",
        "query.unverified_domain": " Nu este verificat dacă acoperă întregul domeniu "
                                   "(provenance.scope).",
        "query.unverified_total": "Completitudinea domeniului acestei sume nu este verificată. Nu "
                                  "este un total oficial verificat; păstrează definiția și "
                                  "domeniul sursei.",
        "query.level_suffix": " (nivel {level})",
        "query.auto_pinned": "Fixări aplicate automat pentru a evita numărarea dublă: {parts}. "
                             "Lista completă este în provenance.effective_selection.",
        "query.approximation": "APROXIMARE: media neponderată a unor valori neaditive (rată, "
                               "indice sau medie), pentru că nu există ponderi corespunzătoare. "
                               "Nu este rata oficială sau națională; spune acest lucru când o "
                               "citezi.",
        "query.time_collapsed": "Valorile sunt agregate pe toate perioadele din {col}; filtrează "
                                "sau grupează după timp pentru o cifră dintr-o singură perioadă.",
        "query.mixed_grain": "{col} acoperă mai multe granularități (niveluri) pe această axă; nu "
                             "compara și nu aduna valori între niveluri.",
        "query.quality_grouped": "Acest fișier are chei de observație repetate ({grain}) în altă "
                                 "parte; felia cerută a fost verificată și nu are.",
        "query.quality_raw": "CALITATEA DATELOR: acest set de date are chei de observație "
                             "repetate ({grain}); rândurile brute pot fi în dezacord între ele. "
                             "Nu le totaliza și nu le clasa.",
        "query.raw_rows": "Observații brute, nu un total verificat. Nu le aduna manual; cere o "
                          "selecție grupată (group_by) ca să obții un total verificat de politică.",
        "query.time_windowed": "Au fost returnate doar cele mai recente perioade (limita de "
                               "rânduri); filtrează TIME_PERIOD ca să ajungi la perioadele "
                               "anterioare.",
        "query.partial_period": "Perioada {period} era incompletă sub limita de rânduri și a fost "
                                "eliminată.",
        "query.preview": "Există mai multe rânduri decât cele returnate (rezultatul a fost "
                         "limitat). Folosește filtre sau linkurile de dovezi pentru restul; o "
                         "previzualizare nu stabilește niciodată un total sau un clasament "
                         "exhaustiv.",
        "query.null_values": "{nulls} din {n} rând(uri) nu au valoare (null: suprimată sau "
                             "indisponibilă la sursă). Null nu este zero; nu o include în sume.",
        "query.no_rows_for_value": "Niciun rând pentru {col} = {absent} în această selecție (nu "
                                   "există nicio observație; aceasta nu este zero).",
        "query.empty_fallback": "Niciun rând nu corespunde valorilor cerute; nimic nu a fost "
                                "înlocuit: nicio altă perioadă, zonă sau categorie nu ține locul "
                                "celei cerute.",
        "query.no_period_obs": "{col} {periods} nu are observații",
        "query.data_covers": " (datele acoperă de la {first} până la {last})",
        "query.list_periods": "Listează perioadele pe care le au efectiv datele.",
        "query.value_missing": "{col} {values} nu există în date",
        "query.lookup_values": "Caută valorile exacte ale {col} din date.",
        "query.each_exists": "fiecare valoare cerută există, dar nicio observație nu le "
                             "îndeplinește pe toate împreună",
        "query.check_one_filter": "Verifică un filtru pe rând (find_dimension_values listează "
                                  "valorile); nimic nu a fost extins în locul tău.",
        "query.no_rows_match": "Niciun rând nu corespunde: {parts}. Nimic nu a fost înlocuit: "
                               "nicio altă perioadă, zonă sau categorie nu ține locul celei "
                               "cerute.",
        "query.dimension_suffix": " (dimensiunea {col})",
        "query.refused": "Politica comună de agregare a refuzat această selecție "
                         "({reason}{where}); nu s-a calculat nicio valoare. Nu indica nicio cifră "
                         "pentru ea.",
        "query.pin_others": "Fixează celelalte dimensiuni la valori explicite sau grupează după "
                            "ele, astfel încât să nu trebuiască combinat nimic.",
        "query.missing_total": "{col} = {shown} nu există în datele {code}: exportul sursei nu "
                               "are un astfel de rând Total",
        "query.missing_total_meta": " deși metadatele INS listează o opțiune Total",
        "query.total_recipe_cross_check": "Totalul propriu al INS este servit de rețeta revizuită "
                                          "'{rid}' (valori publicate, cu reconstituire doar ca "
                                          "verificare încrucișată).",
        "query.without_pin": "Cere politicii aceeași selecție fără fixarea {col}: combină "
                             "valorile rămase ale {col} doar dacă poate verifica că formează o "
                             "partiție completă, fără suprapuneri. Doar candidat: suma poate fi "
                             "totuși refuzată și nu este promisă ca sigură.",
        "query.list_exact": "Listează valorile exacte ale {col} din date.",
        "query.nothing_substituted": ". Nu s-a calculat nimic și nicio altă valoare nu a fost "
                                     "înlocuită.",
        "query.none_exist": "Niciuna dintre valorile cerute pentru {col} ({wanted}) nu există în "
                            "datele {code}; nu s-a calculat nimic și nicio altă valoare nu a fost "
                            "înlocuită.",
        "query.grain_conflicting": "Această felie din {code} repetă aceeași cheie de observație "
                                   "cu valori diferite (granularitate conflictuală), deci nu "
                                   "există un total sau o defalcare unică.",
        "query.grain_duplicate": "Această felie din {code} repetă aceeași cheie de observație "
                                 "(chei duplicate), deci un total ar număra-o de două ori.",
        "query.grain_unverified": "Această felie din {code} este prea mare pentru a verifica dacă "
                                  "are chei de observație repetate, deci nu s-a calculat niciun "
                                  "total.",
        "query.grain_alternative": "{alt} are chei unice certificate și coloanele și valorile "
                                   "cerute: rulează aceeași selecție acolo. Este un candidat, nu "
                                   "un răspuns verificat; verifică definiția și domeniul lui.",
        "query.grain_with_alt": "{what} Nu s-a însumat nimic. Un set de date înrudit poate "
                                "exprima selecția: {alts} (un candidat, nu un răspuns verificat).",
        "query.grain_no_alt": "{what} Nu s-a însumat nimic și nu a fost găsit niciun set de date "
                              "înrudit cu chei unice certificate și coloanele cerute. Rândurile "
                              "acestui set de date nu trebuie totalizate sau clasate manual; "
                              "alege alt set de date pentru acest indicator.",
        "query.grain_narrow": "Filtrează selecția la o zonă sau o perioadă ca felia să poată fi "
                              "verificată, apoi cere din nou.",
        "query.find_another": "Găsește alt set de date pentru acest indicator.",
        "query.overlap": "Opțiunile {col} se suprapun (mai multe niveluri sau granularități, de "
                         "ex. ani de vârstă individuali și grupe de vârstă), deci adunarea lor ar "
                         "număra aceleași unități de mai multe ori. Nu s-a însumat nimic; "
                         "restrânge {col} la un singur nivel verificat.",
        "query.level_one": "nivelul verificat '{name}' ({n} valoare)",
        "query.level_many": "nivelul verificat '{name}' ({n} valori)",
        "query.restrict_level": "Restrânge {col} la {label}. Candidat: politica decide în "
                                "continuare.",
        "query.group_by_level": "Grupează după {col}: axa este limitată la un singur nivel "
                                "verificat (cel implicit, nu toate nivelurile de {n} valori "
                                "combinate). Candidat.",
        "query.complete_child": "{child} este un set de date înrudit al cărui domeniu {col} este "
                                "complet și fără suprapuneri: rulează aceeași selecție acolo. "
                                "Candidat, nu un răspuns verificat.",
        "query.choose_one_level": "Listează valorile exacte ale {col} și alege UN SINGUR nivel "
                                  "(niciodată toate nivelurile împreună).",
        "query.weights": "Această măsură este o rată, un indice sau o medie: valorile unor "
                         "categorii diferite nu pot fi adunate și nu există ponderi "
                         "corespunzătoare pentru o medie ponderată. Nu s-a combinat nimic. O "
                         "medie neponderată etichetată este disponibilă doar dacă utilizatorul o "
                         "acceptă explicit.",
        "query.keep_on_axis": "Păstrează {cols} pe axă în loc să le combini (o valoare pe "
                              "categorie; nu se face nicio medie).",
        "query.pin_every_other": "Fixează fiecare altă dimensiune la o singură valoare explicită "
                                 "(find_dimension_values le listează) sau adaug-o în group_by.",
        "query.ask_unweighted": "Întreabă utilizatorul dacă o medie NEPONDERATĂ a acestor valori "
                                "este acceptabilă: este o aproximare etichetată, nu rata oficială "
                                "sau națională. Doar dacă este de acord, repetă acest apel cu "
                                "approximate=true.",
        "query.mixed_units": "{col} conține mai multe unități de măsură și selecția nu fixează "
                             "una, deci valorile nu au fost combinate între unități. Nu s-a "
                             "calculat nimic.",
        "query.list_units": "Listează unitățile din {col}, apoi fixează exact una.",
        "query.filter_one_unit": "Filtrează {col} la exact o unitate și cere din nou.",
        "query.this_dimension": "această dimensiune",
        "query.total_mismatch": "Cifrele publicate de INS nu concordă: părțile {col} nu însumează "
                                "Totalul INS, deci nu se raportează nicio valoare însumată.",
        "query.no_source_total": "Sursa nu are un rând Total cu care să fie verificată această "
                                 "serie însumată, iar gruparea nu este verificată, deci suma a "
                                 "fost reținută.",
        "query.total_unchecked": "Această serie însumată nu a fost verificată față de Totalul INS "
                                 "(nu există nicio verificare înregistrată), iar gruparea nu este "
                                 "verificată, deci suma a fost reținută.",
        "query.total_recipe": "Totalul publicat de INS este servit de rețeta revizuită '{rid}'.",
        "query.total_alternative": "{alt} are chei unice certificate, coloanele și valorile "
                                   "cerute, iar verificările de politică și de total INS nu rețin "
                                   "aceeași selecție acolo: rulează-o. Este un candidat, nu un "
                                   "răspuns verificat.",
        "query.explicit_slice": "Cere o felie explicită (fixează dimensiunile la valori unice sau "
                                "grupează după ele) în loc de un total combinat.",
        "query.nothing_summed": "{which} Nu s-a însumat nimic.",
        "query.schema_mismatch": "O dimensiune înregistrată pentru {code}{col} nu este o coloană "
                                 "a fișierului de date, deci nicio selecție nu poate fi agregată "
                                 "în siguranță.",
        "query.no_context": "Metadatele {code} nu pot fi folosite pentru o agregare sigură, deci "
                            "aici nu se poate calcula niciun total.",
        "query.nothing_computed": "{what} Nu s-a calculat nimic.",
        "query.col_suffix": " ({col})",
        "query.unverified_structure": "Opțiunile {col} nu au o structură verificată (pot fi "
                                      "imbricate sau pot include totaluri), deci combinarea lor a "
                                      "fost refuzată. Nu s-a însumat nimic.",
        "query.pin_one": "Listează valorile exacte ale {col} și fixează UNA dintre ele (sau "
                         "Totalul ei).",
        "query.keep_col": "Păstrează {col} pe axă în loc să o combini. Candidat.",
        "query.contains_aggregate": "Valorile {col} selectate amestecă un Total cu propriile "
                                    "părți, ceea ce ar număra aceleași unități de două ori. Nu "
                                    "s-a însumat nimic; alege doar Totalul sau doar părțile.",
        "query.use_total": "Folosește doar Totalul ({totals}).",
        "query.use_parts": "Folosește doar părțile; politica decide în continuare dacă pot fi "
                           "combinate. Candidat.",
        "query.list_values": "Listează valorile exacte ale {col}.",
        "query.describe_rec": "Citește coloanele, valorile, subseturile și notele setului de date.",
        "query.narrowing": "Restrânge selecția (filtrează o perioadă sau o zonă ori grupează după "
                           "mai puține coloane) ca să vezi rândurile rămase; o previzualizare nu "
                           "este întregul rezultat.",
        "query.try_narrower": "Încearcă {dataset} cu o selecție mai restrânsă.",
        "query.labels_omitted": "Etichetele afișate au fost omise ca să încapă în bugetul "
                                "răspunsului, pentru coloanele: {subjects}. Valorile sunt "
                                "valorile exacte stocate.",
        "query.filters_summarized": "Listele lungi de filtre efective au fost rezumate ca să "
                                    "încapă în bugetul răspunsului, pentru: {subjects}; listele "
                                    "complete se reproduc repetând selecția canonică.",
        # ---- discover_indicators / describe_dataset / find_dimension_values
        "discover.generation_manifest": "Manifestul generației de date este {status}: aceste "
                                        "metadate sunt citite din fișierele servite și nu sunt "
                                        "certificate pentru o generație.",
        "discover.note.place_not_in_dataset": "Un loc numit nu a fost găsit printre valorile "
                                              "REF_AREA ale acestui set de date; nu a fost "
                                              "aplicat.",
        "discover.note.place_level_unavailable": "Acest indicator nu are date la nivelul locului "
                                                 "numit (județ); locul nu a fost aplicat.",
        "discover.freq.annual": "anual",
        "discover.freq.quarterly": "trimestrial",
        "discover.freq.monthly": "lunar",
        "discover.parent_level": "părinte",
        "discover.period_outside": "{year} este în afara datelor {code} ({span}); anul nu a fost "
                                   "aplicat și nimic nu a fost înlocuit.",
        "discover.period_not_single": "{code} este {frequency}: {year} nu este o singură "
                                      "perioadă. Listează-i perioadele (find_dimension_values, "
                                      "query {query!r}) și filtrează valori exacte.",
        "discover.period_gap": "{year} nu este o perioadă reală a {code} ({span}, cu goluri); "
                               "anul nu a fost aplicat și nimic nu a fost înlocuit.",
        "discover.no_data_file": "{code} nu are un fișier de date propriu; este publicat ca "
                                 "subseturi.",
        "discover.grain_conflicting": "{code} are rânduri cu aceeași cheie și valori diferite în "
                                      "auditul generației: totalurile grupate sunt refuzate. Nu "
                                      "este o țintă de interogare.",
        "discover.grain_duplicate_keys": "{code} are rânduri cu aceeași cheie în auditul "
                                         "generației: totalurile grupate sunt refuzate. Nu este o "
                                         "țintă de interogare.",
        "discover.domain_incomplete": "Domeniu restrâns: {desc}. Nu este un răspuns pentru "
                                      "întreaga populație.",
        "discover.aggregation_unavailable": "Politica comună de agregare refuză să colapseze aici "
                                            "celelalte dimensiuni ({reason}{column}): alege "
                                            "valori explicite (describe_dataset) sau folosește o "
                                            "rețetă revizuită.",
        "discover.grain_unverified": "Granularitatea nu este certificată de dovezile generației; "
                                     "query_data verifică felia selectată.",
        "discover.latest_period": "„Ultimul” a fost rezolvat la ultima perioadă cu date din "
                                  "{code}: {period}.",
        "discover.recipe_period": "{year} este în afara anilor pe care îi au în comun ambele "
                                  "surse{span}; anul nu a fost aplicat și nimic nu a fost "
                                  "înlocuit (o rețetă fără an ar răspunde pentru ultimul an "
                                  "comun).",
        "discover.recipe_place": "{absent} nu se află printre etichetele REF_AREA ale {dataset}, "
                                 "pe care rețeta le potrivește exact (fără diferențe de "
                                 "diacritice, majuscule sau spații). Caută eticheta (area_lookup) "
                                 "înainte de a rula rețeta; nimic asemănător nu a fost înlocuit.",
        "discover.recipe_grain": "O sursă a acestei rețete are probleme de granularitate în "
                                 "auditul generației; run_recipe poate refuza sau exclude "
                                 "entități.",
        "discover.recipe_domain": "Eligibilitatea și excluderile unei rețete sunt în rezultatul "
                                  "run_recipe.",
        "discover.level_differs": "Nicio sursă interogabilă la nivelul cerut ({wanted}); aceasta "
                                  "este sursa de nivel {level} și nu poate răspunde la o "
                                  "întrebare despre o zonă mai mică.",
        "discover.source_total": "Rută revizuită către totalul pe județe.",
        "discover.no_verified_candidate": "Niciun candidat nu este o interogare de date gata de "
                                          "rulat (vezi notele fiecărui candidat); next_call "
                                          "citește dimensiunile primului candidat ca să poată fi "
                                          "alese valori explicite.",
        "discover.no_specific_wording": "Nicio întrebare reformulată nu selectează singură "
                                        "această variantă; roagă utilizatorul să o spună cu "
                                        "cuvintele lui.",
        "discover.resolution_failed": "Această variantă nu a putut fi rezolvată într-un apel; "
                                      "folosește reformularea ei (next_call).",
        "discover.no_match_choice": "Întrebarea reformulată nu mai ajunge la această definiție.",
        "discover.no_call": "Nu există niciun apel de date validat pentru această definiție și "
                            "întrebare.",
        "discover.county_label": "Județ: {names}",
        "discover.county_description": "Cifre pentru întreg județul (seria pe care o are acest "
                                       "indicator); nu doar orașul.",
        "discover.all_counties_label": "Toate județele",
        "discover.all_counties_description": "Un rând pe județ; alege locul după aceea.",
        "discover.city_series_missing": "Seria revizuită a populației orașelor nu se află în "
                                        "această generație de date. Datele pe județ nu au fost "
                                        "înlocuite.",
        "discover.recipe_unavailable": "Rețeta pe locuitor nu este disponibilă; nu a fost "
                                       "înlocuit niciun număr brut.",
        "discover.constraint_withheld": "O constrângere din întrebare nu este aplicată de "
                                        "discovery, deci aici nu se sugerează niciun apel de date "
                                        "care o ignoră.",
        "discover.constraint_filter": "Citește dimensiunile și filtrează valori explicite; dacă "
                                      "acest set de date nu o poate exprima, spune acest lucru.",
        "discover.constraint_recipe": "Această rețetă nu o poate prelua; spune acest lucru.",
        "discover.kind.sex": "sex",
        "discover.kind.age": "vârstă",
        "discover.kind.denominator": "numitor",
        "discover.kind.geography": "geografie",
        "discover.constraint_warning": "Întrebarea conține o constrângere de tip {kind} "
                                       "({words}), dar discovery nu a aplicat-o; candidații nu "
                                       "răspund la ea așa cum sunt. Filtrează valori explicite "
                                       "după describe_dataset sau spune utilizatorului că nu a "
                                       "fost aplicată. Nimic nu a fost omis în tăcere.",
        "discover.assumed_cities": "Definiție presupusă pentru orașe: {label} ({note}). Populația "
                                   "rezidentă nu este disponibilă pentru orașe în seria "
                                   "revizuită; precizează explicit definiția.",
        "discover.assumed": "Definiție presupusă: {label}. Precizeaz-o explicit; alternativele "
                            "rămân disponibile.",
        # ---- discovery: one county narrows a city ranking; a level picks a definition
        "discover.place_filter": "Doar orașele din {county}: toate orașele eligibile din acel "
                                 "județ sunt clasate înainte de tăierea top K, iar numerele de "
                                 "entități eligibile și din afara clasei sunt doar pentru acel "
                                 "județ.",
        "discover.assumed_level": "Definiție presupusă: {label}, luând întrebarea la nivel de "
                                  "{level}. {missing}Precizează explicit definiția ca s-o "
                                  "schimbi; alternativele rămân disponibile.",
        "discover.level_missing": "{name} nu are serie la nivel de {level} în catalogul revizuit "
                                  "(acoperă: {covers}). ",
        "discover.level_county": "județ",
        "discover.level_region": "regiune",
        "discover.level_macroregion": "macroregiune",
        "discover.level_national": "țară",
        "discover.generic_word": "„{matched}” este un cuvânt generic: poate însemna {names}.",
        "discover.generic_single": "„{matched}” este un cuvânt generic; există o singură "
                                   "definiție revizuită pentru el.",
        "discover.city_not_county": "Întrebarea numește un oraș din județul {name}; TEMPO publică "
                                    "acest indicator pe județe. Cifrele pe județ nu sunt cele ale "
                                    "orașului.",
        "discover.msg_definition": "Formularea este ambiguă între {n} definiții oficiale: "
                                   "{names}. Nu a fost ales niciun număr sau set de date: cere "
                                   "utilizatorului să aleagă una. Abia după ce a ales, rulează "
                                   "acțiunea acelei variante (status ready); next_call "
                                   "reformulează întrebarea cu acea definiție.",
        "discover.the_place": "Locul",
        "discover.msg_place": "{place} pare un oraș, dar acest indicator este publicat pe județe. "
                              "Alege seria pe județ sau toate județele; cifrele la nivel de oraș "
                              "nu sunt rezolvate de acest instrument.",
        "discover.use_choice": "Folosește: {label}",
        "discover.no_match": "Niciun concept sau set de date revizuit nu se potrivește "
                             "interogării.",
        "discover.rephrase": "Reformulează cu numele indicatorului și, opțional, un nivel (de ex. "
                             "„pe județe”) sau un județ și un an. Nimic nu a fost înlocuit.",
        "discover.msg_ok": "{n} concept(e) revizuit(e) cu seturi de date candidate și {m} "
                           "rezultat(e) de căutare pe familii. Candidații au starea "
                           "granularității și orice restricție de domeniu dovedită "
                           "(domain.complete null = neverificat); familiile sunt rezultate de "
                           "căutare neverificate.",
        "discover.msg_unapplied": " Neaplicat din întrebare: {items}; vezi avertismentele.",
        "discover.families_note": "Rezultate ale căutării full-text grupate pe familii de "
                                  "indicatori: candidați de citit cu describe_dataset, nu "
                                  "răspunsuri verificate. time_range este cel din profilul "
                                  "setului de date, nefiind verificat față de date.",
        "discover.search_degraded": "Căutarea full-text nu este disponibilă; familiile sunt "
                                    "potrivite doar după numele seturilor de date.",
        "discover.response_shortened": "Detaliile opționale au fost tăiate ca să încapă în "
                                       "bugetul răspunsului; apelează describe_dataset pentru "
                                       "restul.",
        "describe.unknown": "Set de date necunoscut {code!r}.",
        "describe.find": "Găsește codul setului de date după concept sau temă.",
        "describe.code_shape": "Codurile seturilor de date arată ca POP105A_judete_grupe; copiază "
                               "unul din discover_indicators sau describe_dataset.",
        "describe.total_note": "Metadatele listează {names} pentru {col}, dar datele nu au o "
                               "astfel de valoare (totalul propriu al INS nu a fost descărcat). "
                               "Nu filtra această dimensiune la Total; o sumă peste valorile ei "
                               "este validă doar acolo unde o permite politica de agregare.",
        "describe.no_values": "Nu sunt disponibile valori reale (fără fișier de date sau coloană "
                              "ilizibilă).",
        "describe.no_period_file": "Fără fișier de date: intervalul real de perioade este "
                                   "necunoscut.",
        "describe.period_unreadable": "Coloana de perioadă nu a putut fi citită.",
        "describe.metadata_range": "Metadatele listează {mfirst}–{mlast} ({options} perioade); "
                                   "datele au {first}–{last} ({periods} perioade cu observații). "
                                   "Limitele din date sunt cele autoritative.",
        "describe.no_data_file": "Acest set de date nu are un fișier de date propriu",
        "describe.no_data_file_splits": ": este publicat ca subseturile din `splits`; descrie sau "
                                        "interoghează unul dintre ele.",
        "describe.grain_conflicting": "Auditul generației a găsit rânduri cu aceeași cheie și "
                                      "valori diferite: totalurile grupate ale acestui set de "
                                      "date sunt refuzate.",
        "describe.grain_duplicate_keys": "Auditul generației a găsit rânduri cu aceeași cheie: "
                                         "totalurile grupate ale acestui set de date sunt "
                                         "refuzate.",
        "describe.examples_note": "Exemplele sunt un eșantion de valori reale, nu o listă "
                                  "exhaustivă: folosește `lookup` (find_dimension_values) al "
                                  "fiecărei dimensiuni ca să le cauți sau să le parcurgi pe toate "
                                  "și folosește valoarea exactă în filtre.",
        "describe.no_period_data": "fără date de perioadă",
        "describe.message": "{code}: {n} dimensiune(i), {span}",
        "describe.message_frequency": " ({frequency})",
        "describe.message_splits": ", {n} subset(uri)",
        "values.no_match": "Nicio valoare din {col} nu conține {query!r} (potrivire de subșir "
                           "fără diferențe de diacritice și majuscule). Încearcă mai puține "
                           "litere sau listează valorile fără interogare.",
        "values.list_all": "Listează valorile fără interogare.",
        "values.none": "{col} nu are valori în date.",
        "values.past_end": "offset {offset} depășește ultima dintre cele {total} valori potrivite.",
        "values.periods_with_data": " Perioade cu date: {first}–{last}.",
        "values.message": "{total} valoare(i) potrivită(e) pentru {col}; se afișează "
                          "{first}–{last}",
        "values.next_offset": "; next_offset={n}",
        "values.use_exact": ". Folosește `value` exact în filtre.",
        "values.obs_value": "OBS_VALUE este valoarea observației, nu o dimensiune: nu are valori "
                            "selectabile.",
        "values.unknown_column": "{code} nu are coloana de dimensiune {col!r}.",
        "values.its_columns": " Coloanele sale de dimensiune sunt: {cols}.",
        # ---- policy / rank_entities / compare_periods
        "policy.city_change_unsupported": "Clasamentele schimbărilor doar pentru orașe nu sunt "
                                          "încă acceptate. Specifică o comparație a schimbărilor "
                                          "pe județe sau un clasament al populației orașelor "
                                          "pentru un singur an.",
        "policy.unsupported_measure": "Această întrebare necesită alt numitor sau o operație de "
                                      "densitate ori corelație. Nu a fost înlocuit niciun număr "
                                      "sau raport față de suprafața construită. Cere separat "
                                      "clasamentul populației sau rețeta revizuită a înnoptărilor "
                                      "pe locuitor.",
        "policy.city_not_population": "Nicio serie revizuită la nivel de oraș nu răspunde la "
                                      "această întrebare: singura este populația anuală după "
                                      "domiciliul legal, ca clasament. Datele pe județ nu au fost "
                                      "înlocuite.",
        "policy.city_resident": "Aici nu este disponibil niciun clasament revizuit anual al "
                                "orașelor după populația rezidentă. Seria pe localități numără "
                                "domiciliul legal; cere explicit populația după domiciliu ca să o "
                                "folosești. Datele pe județ nu au fost înlocuite.",
        "policy.city_not_configured": "Aici nu este configurată nicio serie revizuită a "
                                      "populației orașelor. Datele pe județ nu au fost înlocuite.",
        "policy.recipe_unavailable": "Rețeta pe locuitor nu este disponibilă; nu a fost înlocuit "
                                     "niciun număr brut.",
        "policy.top_k_max": "Pot fi returnate cel mult {max} entități clasate; cere un top K mai "
                            "mic.",
        "policy.top_k_min": "Un clasament are nevoie de un top K de cel puțin 1.",
        "policy.city_change_historical": "Clasamentele schimbărilor pentru orașe folosesc "
                                         "catalogul curent al municipiilor și orașelor (INS "
                                         "GOS102A): o întrebare care necesită statutul istoric de "
                                         "oraș sau limite constante nu poate primi răspuns, "
                                         "deoarece nicio sursă revizuită nu le înregistrează.",
        "policy.city_change_years": "Clasamentele schimbărilor pentru orașe au nevoie de exact "
                                    "doi ani exacți (de exemplu între 2015 și 2020); nu se "
                                    "presupune niciun an cel mai recent, apropiat sau implicit.",
        "policy.city_change_direction": "Clasamentele schimbărilor pentru orașe au nevoie de o "
                                        "direcție precizată: creștere sau scădere. Schimbarea "
                                        "absolută sau ambele direcții într-o singură întrebare nu "
                                        "sunt clasate.",
        "policy.city_change_least": "Clasamentele schimbărilor pentru orașe urmează direcția "
                                    "precizată (creștere: cele mai mari întâi; scădere: cele mai "
                                    "negative întâi); formulările „ultimele”, „cele mai mici” sau "
                                    "„cele mai scăzute” sunt ambigue pentru schimbări și nu sunt "
                                    "interpretate.",
        "policy.city_change_note": "Un clasament al schimbărilor pentru orașe cuprinde "
                                   "municipiile și orașele din catalogul de referință (INS "
                                   "GOS102A, chei SIRUTA), nu comunele. Apartenența nu dovedește "
                                   "statutul istoric de oraș sau limite neschimbate.",
        "rank.identity_ambiguous_labels": "Catalogul de orașe repetă o cheie SIRUTA cu etichete "
                                          "diferite.",
        "rank.catalogue_unavailable": "Catalogul SIRUTA de municipii/orașe INS GOS102A nu este "
                                      "disponibil.",
        "rank.siruta_required": "Valorile localităților trebuie să poarte chei SIRUTA exacte; "
                                "numele nu se asociază.",
        "rank.siruta_repeated": "O cheie SIRUTA de oraș apare la mai multe entități.",
        "rank.additive_only": "Acest clasament acceptă doar măsuri aditive; folosește o rețetă "
                              "revizuită pentru rate.",
        "rank.annual_required": "Este necesară o perioadă anuală de observație.",
        "rank.use_year": "Folosește year în loc de un filtru de timp.",
        "rank.entity_columns": "entity_columns trebuie să numească dimensiuni existente, care nu "
                               "sunt de timp.",
        "rank.key_too_long": "Cheia completă a entității depășește opt coloane.",
        "rank.cities_need_locality": "Orașele necesită REF_AREA_2 cu chei de localitate SIRUTA.",
        "rank.no_year": "Nu există observații pentru {year}; niciun an apropiat nu a fost "
                        "înlocuit.",
        "rank.query_refused": "Interogarea comună a refuzat datele de intrare ale clasamentului.",
        "rank.source_incomplete": "Nu s-a calculat niciun clasament dintr-o intrare limitată sau "
                                  "pe fereastră; restrânge selecția.",
        "rank.approximation": "O agregare aproximativă nu poate fi intrare pentru un clasament.",
        "rank.mixed_levels": "Alege un singur nivel de entitate înainte de clasare.",
        "rank.empty_key": "O entitate are o cheie goală; nu s-a calculat niciun clasament.",
        "rank.duplicate_key": "Există mai multe valori pentru o entitate; nu s-a calculat niciun "
                              "clasament.",
        "rank.classification": "Orașele sunt municipiile și orașele din catalogul SIRUTA al INS "
                               "GOS102A; schimbările istorice ale clasei UAT nu sunt urmărite.",
        "rank.entities_excluded": "{n} entități nu au o observație finită; nu li s-a atribuit "
                                  "zero.",
        "rank.unverified_total": "Completitudinea domeniului colapsat nu este verificată; nu "
                                 "pretinde un total oficial complet.",
        "rank.message": "Primele {k} din {n} entități eligibile în {year}; clasate înainte de "
                        "limitarea ieșirii. {scope}",
        "changes.evidence_link": "Obține linkul către clasamentul complet și lista completă a "
                                 "excluderilor (pachetul de dovezi).",
        "changes.tail": "Poziția este rangul ordinal după metrica și ordinea cerute, nu o "
                        "afirmație de semnificație statistică.",
        "changes.class_tail": "Orașele sunt municipiile și orașele din catalog (INS GOS102A); "
                              "apartenența nu dovedește statutul istoric de oraș sau limite "
                              "neschimbate.",
        "changes.who_entity": "entitate",
        "changes.who_class": "entitate din clasa „municipii și orașe din catalogul de referință”",
        "changes.none_ranked": "Nicio entitate nu are o valoare finită la ambele capete ale "
                               "vreunui interval, deci nimic nu a fost clasat. Excluderile spun "
                               "de ce; niciun gol nu a fost completat cu zero.",
        "changes.none_ranked_cities": "Niciun municipiu sau oraș din catalogul de referință nu "
                                      "are o valoare finită la ambele capete ale vreunui "
                                      "interval, deci nimic nu a fost clasat ({outside} entități "
                                      "sursă sunt în afara acelei clase). Niciun gol nu a fost "
                                      "completat cu zero.",
        "changes.source_unit": "unitatea sursei",
        "changes.ranked": "Schimbarea pe entitate în {unit} pentru {n} interval(e) din {dataset}: "
                          "fiecare {who} eligibilă a fost clasată ({eligible} clasate) și se "
                          "afișează {returned} rând(uri).",
        "changes.outside_class": " {outside} entități sursă din afara catalogului (comune, "
                                 "totaluri) nu au fost clasate.",
        "changes.pairs_excluded": " {excluded} perechi entitate–interval au fost excluse și sunt "
                                  "listate.",
        "changes.restricted": " Domeniu restrâns: {desc}.",
        "changes.preview_shortened": "Previzualizarea a fost scurtată ca să încapă în bugetul "
                                     "răspunsului; pachetul de dovezi are clasamentul complet și "
                                     "lista excluderilor.",
        "period.duplicate_keys": "Interogarea sursă a returnat mai multe valori pentru aceeași "
                                 "entitate și același an, deci nu există o singură valoare la "
                                 "capăt. Nu s-a calculat nicio schimbare.",
        "period.duplicate_keys_narrow": "Fixează cu filtre dimensiunea care repetă cheia sau "
                                        "compară un alt set de date.",
        "period.read_periods": "Citește perioadele și frecvența setului de date.",
        "period.too_many_periods": "{code} are mai mult de {max} etichete de perioadă distincte; "
                                   "sunt acceptate doar perioadele anuale exacte.",
        "period.non_annual": "{code} are valori de perioadă neanuale (de ex. {examples}); "
                             "compare_periods acceptă doar perioade anuale exacte, nu serii "
                             "lunare, trimestriale sau mixte.",
        "period.year_two_ways": "{code} etichetează anul {year} în mai multe moduri ({labels}); "
                                "perioadele nu pot fi potrivite exact.",
        "period.no_periods": "{code} nu are valori de perioadă.",
        "period.a_dimension": "o dimensiune",
        "period.native.overlapping_levels": "{col} amestecă niveluri care se suprapun (de exemplu "
                                            "județe cu regiuni sau ani individuali cu grupe de "
                                            "vârstă); nu există un total sau un clasament unic "
                                            "până nu se alege un singur nivel.",
        "period.native.unverified_structure": "Structura {col} nu este verificată, deci sursa nu "
                                              "poate spune cum se combină opțiunile ei.",
        "period.native.contains_aggregate": "{col} conține un total alături de părțile sale; "
                                            "combinarea lor ar număra de două ori.",
        "period.native.label_hierarchy": "{col} codifică o ierarhie în etichete; însumarea ar "
                                         "număra de două ori.",
        "period.native.declared_partition_invalid": "{col} nu este o partiție disjunctă validă.",
        "period.native.source_total_mismatch": "Opțiunile proprii ale INS pentru {col} nu "
                                               "însumează totalul INS, deci dimensiunea nu este "
                                               "însumată.",
        "period.native.mixed_units": "{col} are mai multe unități; valorile în unități diferite "
                                     "nu sunt niciodată combinate.",
        "period.native.slice_value_missing": "O valoare cerută pentru {col} nu se află în date.",
        "period.native.conflicting_grain": "Rândurile selectate repetă o cheie completă cu valori "
                                           "diferite, deci nu există o singură valoare.",
        "period.native.duplicate_keys": "Rândurile selectate repetă o cheie completă, deci o sumă "
                                        "ar număra-o de două ori.",
        "period.native.grain_unverified": "Granularitatea rândurilor selectate nu a putut fi "
                                          "verificată.",
        "period.native.schema_mismatch": "Dimensiunea {col} înregistrată pentru setul de date nu "
                                         "se află în fișierul său de date.",
        "period.native.missing_weights": "Măsura nu poate fi combinată fără ponderi.",
        "period.native.no_aggregation_context": "Regulile de agregare ale setului de date nu sunt "
                                                "disponibile.",
        "period.native.default": "Politica comună de agregare a refuzat această selecție "
                                 "({reason}).",
        "period.no_change": "Nu s-a calculat nicio schimbare: {text}",
        "period.list_pin": "Listează valorile reale ale {col}, apoi fixează-o la o valoare sau la "
                           "un nivel cu filtre.",
        "period.read_dims_grain": "Citește dimensiunile, nivelurile și starea granularității "
                                  "setului de date.",
        "period.pop_domicile": "Sursa definește aceasta ca populația după domiciliu (domiciliu), "
                               "care nu este o numărătoare a rezidenților.",
        "period.pop_resident": "Sursa definește aceasta ca populația rezidentă (reședința "
                               "obișnuită).",
        "period.pop_both": "Textul sursei menționează atât domiciliul, cât și reședința "
                           "obișnuită; verifică pe care o numără această serie.",
        "period.pop_unsaid": "Definiția sursei nu spune dacă numără domiciliul sau reședința "
                             "obișnuită; nu o citi ca pe o numărătoare a rezidenților.",
        "period.class_warning": "Orașele sunt municipii și orașe din catalogul de referință (INS "
                                "GOS102A, chei SIRUTA). Apartenența nu dovedește statutul istoric "
                                "de oraș sau limite neschimbate; locurile din afara catalogului "
                                "(comune, totaluri) nu au fost clasate.",
        "period.pairs_not_ranked": "{total} perechi entitate–interval nu au fost clasate "
                                   "({reasons}); sunt listate pe intervale, niciodată completate "
                                   "cu zero.",
        "period.boundary": "Etichetele sau codurile stabile nu dovedesc un teritoriu neschimbat: "
                           "schimbările de limite, fuziunile și divizările dintre anii de capăt "
                           "nu sunt urmărite, deci o schimbare poate reflecta teritoriul, nu doar "
                           "o schimbare reală.",
        "period.inside_interval": "În intervalul comparat {hit}: {text}",
        "period.unsupported_measure": "{code} este clasificat ca măsură {measure} (tip de unitate "
                                      "{unit_type}): ratele, mediile, indicii și unitățile "
                                      "necunoscute nu sunt comparate aici, deoarece schimbarea "
                                      "unei astfel de valori nu are o definiție unică. Poate "
                                      "exista o rețetă revizuită.",
        "period.non_additive": "neaditivă",
        "period.unknown_unit_type": "necunoscut",
        "period.find_recipe": "Caută o rețetă sau un indicator revizuit pentru această măsură.",
        "period.no_time": "{code} nu are o dimensiune de timp, deci nu există capete anuale.",
        "period.read_dims": "Citește dimensiunile setului de date.",
        "period.filter_is_period": "Filtre invalide: {col} este coloana de perioadă; perioadele "
                                   "vin din intervale.",
        "period.entity_is_period": "entity_columns invalid: {col} este coloana de perioadă, nu o "
                                   "entitate.",
        "period.unknown_entity_column": "entity_columns invalid: coloană necunoscută {col!r}",
        "period.year_absent": "Anul {years} nu are observații în {code}; datele acoperă de la "
                              "{first} până la {last}. Niciun an apropiat nu a fost înlocuit.",
        "period.list_values": "Listează valorile reale ale {col}.",
        "period.source_capped": "Interogarea sursă pentru anii de capăt este mai mare decât "
                                "limita de {cap} rânduri (sau a fost pe fereastră), deci setul de "
                                "entități este incomplet. Nu s-a calculat niciun clasament "
                                "dintr-o intrare limitată.",
        "period.source_capped_narrow": "Filtrează o coloană de entitate (de exemplu un județ) sau "
                                       "fixează alte dimensiuni ca tabelul capetelor să încapă în "
                                       "limită.",
        "period.approximation": "O agregare aproximativă (neponderată) nu este folosită pentru "
                                "schimbările între perioade.",
        "period.mixed_levels": "{col} amestecă niveluri care se suprapun (de exemplu județe cu "
                               "regiuni), deci clasarea valorilor ei ar compara o zonă cu "
                               "propriile părți. Alege un singur nivel.",
        "period.list_one_level": "Listează valorile reale ale {col}, apoi filtrează la valorile "
                                 "unui singur nivel.",
        "period.read_levels": "Citește dimensiunile și nivelurile setului de date.",
        "period.values_missing": "Valorile cerute pentru {col} nu se află în date: {values}.",
        "period.no_observations": "Selecția nu are observații la anii de capăt.",
        "period.unexpected_shape": "Interogarea sursă a returnat o formă neașteptată (referință "
                                   "{ref}); nu s-a calculat nimic.",
        "period.unexpected_period": "Interogarea sursă a returnat o perioadă neașteptată "
                                    "(referință {ref}); nu s-a calculat nimic.",
        "period.empty_key": "Unele rânduri au o componentă goală în cheia entității, deci acele "
                            "entități nu pot fi identificate.",
        "period.full_key": "Compară cu cheia completă ({cols}) ca locurile cu același nume să "
                           "rămână separate.",
        "period.identity_ambiguous": "{n} valoare(i) cerută(e) pentru {requested}, de ex. "
                                     "{example!r}, apar la mai multe valori {added} ({parents}); "
                                     "un nume singur nu identifică un loc. Include {added} în "
                                     "entity_columns.",
        # ---- run_recipe
        "recipe.preview_shortened": "Previzualizarea a fost scurtată ca să încapă în bugetul "
                                    "răspunsului (eșantionul de excluderi, celulele agregate sau "
                                    "rândurile clasamentului); numărul excluderilor și selecția "
                                    "canonică dau rezultatul complet.",
        # ---- Ask (agent.py, ask_present.py)
        "agent.tool_budget": "Neexecutat: s-a atins limita de apeluri către instrumente. Răspunde "
                             "din rezultatele pe care le ai.",
        "agent.deadline": "Neexecutat: s-a atins limita de timp. Răspunde din rezultatele pe care "
                          "le ai.",
        "agent.invalid_arguments": "Argumentele instrumentului au fost tăiate sau nu erau un "
                                   "obiect JSON; apelează din nou instrumentul cu argumente "
                                   "complete.",
        "agent.repeated": "Aceeași cerere a fost deja făcută în acest tur și refuzată; rezultatul "
                          "și candidații de recuperare sunt repetați, nu rulați din nou. "
                          "Restrânge sau schimbă cererea.",
        "agent.cancelled": "Neexecutat: cererea a fost oprită.",
        "agent.tool_failed": "Instrumentul a eșuat; nu s-a calculat nimic.",
        "agent.limit.iterations": "S-a atins limita de apeluri către model",
        "agent.limit.tools": "S-a atins limita de apeluri către instrumente",
        "agent.limit.deadline": "S-a atins limita de timp",
        "agent.limit.output_budget": "S-a atins alocația de ieșire",
        "agent.limit_stopped": " înainte de un răspuns final; rezultatul este parțial.",
        "agent.limit_forced": " înainte de încheierea explorării; răspunsul este parțial.",
        "agent.provider_failed": "Furnizorul modelului a eșuat ({code}) înainte de un răspuns "
                                 "final; rezultatul este parțial.",
        "agent.ranking_hidden": "O previzualizare de interogare fără clasare a fost ascunsă: nu "
                                "răspunde clasamentului cerut.",
        "agent.values_withheld": "Răspuns reținut: indica cifre, dar nicio interogare de date nu "
                                 "a reușit.",
        "agent.numbers_not_found": "Cifre negăsite în niciun rezultat de interogare (derivate sau "
                                   "neverificate): {numbers}",
        "agent.claim_withheld": "Răspuns reținut: unitatea sau perioada explicită contrazice "
                                "rezultatul citat.",
        "present.pairs_excluded": "{n} perechi entitate–interval au fost excluse din clasament "
                                  "(vezi linkul de dovezi pentru listă).",
    },
}
