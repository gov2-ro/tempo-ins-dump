# AQ-09C — MCP question sweep: baseline record

Part C of [09-mcp-usability.md](09-mcp-usability.md). Date: 2026-11-18. Baseline of the code **before** AQ-09
parts A and B and before AQ-08 (chart hints). The same 20 questions are re-run after those fixes.
No application code changed. Raw calls: [aq-09c-sweep-baseline.jsonl](aq-09c-sweep-baseline.jsonl).
Question set: [aq-09c-sweep-questions.json](aq-09c-sweep-questions.json).

## Setup

- Code: branch `aq-09c-sweep-baseline`, from tip `9205dd8` of `fix/ask-answer-quality` (the AQ-09 brief lives
  there). Contract `tempo-tools/2`.
- Data: `TEMPO_DATA_DIR=/Users/pax/devbox/gov2/tempo-ins-dump/data`, read only. Generation `062bd2b0`
  (status `present`). No file under `data/` changed (checked by modification time).
- Method: **in-process** `app.services.tools.registry.call_tool(name, arguments)`, the one entry point behind both
  Ask and the public MCP. Reason: no port, no content logs, no server state, and the envelopes are identical.
  Not covered: the MCP transport, SDK schema checks and the Ask page. The Ask UI failure of question 1 (hidden
  `query_data` table) is therefore not reproduced here.
- Driver: a throw-away script outside the repository. It calls the tool, logs `{q, tool, arguments, envelope, ms}`
  and prints the envelope. Calls are in `seq` order in the JSONL (416 KB).
- The "model" is the author, acting as a careful model: first call `discover_indicators` with the full question,
  then follow `next_call`, `action` and `recovery`. At most 12 dispatches per question (none needed more than 9).
  A question that needs a user choice stops at the choice (outcome `clarification`); the author then picks one
  option and notes it. Guesses are marked **GUESS**.
- Task-file check: `data/eval/ask_tasks.json` (`ask-tasks/1`) holds scripted conversations with hand-computed
  expected numbers on a synthetic fixture, or pinned cases for one generation. Baseline failures do not fit
  that format, so the questions stay in this record and in the questions JSON. Nothing was added to the task file.

## Outcome counts (20 questions)

| Outcome | n | Questions |
|---|---|---|
| answered, correct as far as checked | 8 | 02, 03, 04, 07, 08, 13, 14, 19 |
| clarification (answerable after the user's choice) | 2 | 06, 09 |
| partial (part of the question unanswerable) | 3 | 01, 10, 18 |
| failed (no usable answer) | 3 | 05, 11, 12 |
| no data in the corpus; tool and model can say so | 3 | 15, 16, 20 |
| answered, probably wrong (double count) | 1 | 17 |

Note on `status`: `partial / unverified_total` appears on almost every data answer (10 of 20 questions). It never
distinguishes a good answer from a bad one, so it carries no signal for a model.

## Question table

Dispatches = tool calls. "First block" = the first response that misled or blocked.

| # | Question | Calls (key arguments) | Disp. | Outcome | Correct? | First block or misleading response |
|---|---|---|---|---|---|---|
| 01 | RO "top cele mai mari și cele mai mici 5 judete cu venituri/PIB per capita, și pe suprafata daca poti" | discover (full question) -> discover "PIB pe locuitor județe" -> discover "produs intern brut regional…" -> describe CON103H_judete -> rank_entities (refused) -> query_data 2022 by REF_AREA -> discover x3 for area | 9 | partial | GDP part yes (model sorts 42 single cells: top Municipiul București 209,362, Cluj, Timiș, Gorj, Constanța; bottom Vaslui 30,377, Botoșani, Giurgiu, Călărași, Suceava). Area: not found. | Call 1: `0 concept(e)…`, five unrelated families (TBE0233, INT111C…), no CON103H. Warning `constraint_not_applied`: "constrângere de tip numitor ('per capita')… candidații nu răspund la ea" although per capita is the measure. Then `rank_entities`: "Acest clasament acceptă doar măsuri aditive; folosește o rețetă revizuită pentru rate." (no recovery). Area queries return GOS102A, AGR102x (irrigated area), never a total area. |
| 02 | RO "Care municipii au crescut și care au scăzut cel mai mult ca populație între 2016 și 2026?" | discover (full question) -> compare_periods POP107D_grupe_localitate cities desc top 5 -> same asc top 10 | 3 | answered | Yes, with caveats. Desc: Vaslui +32,636, Popești-Leordeni, Bragadiru; asc: Timișoara -40,541, Brăila, Ploiești. | No block. discover picked domicile population and the city dataset at once (`assumed_definition` warning). Residual: `entity_class cities` is municipii AND orașe (Ilfov orașe in the top); no way to keep municipii only. Vaslui +32.6k is a known domicile inflation (backlog) and no tool says so. `next_call` gives only `order: desc`; the "decreased" half needs a second call. |
| 03 | EN "What is the unemployment rate in Cluj county?" | discover -> run_recipe registered_unemployment_county areas Cluj | 2 | answered | Yes: 1.5% (registered, 2025). Warning says ILO has no county series. | None. |
| 04 | RO "Cum a evoluat populația României în ultimii 30 de ani?" | discover -> query_data POP105A (resident, 15 years) -> discover "populația după domiciliu România 1996-2026" (**GUESS**: model picks domicile because it is longer) -> query_data POP107A 1996–2025 | 4 | answered (partial) | Yes for domicile 1996–2025. The resident series only has 2012–2026. | Call 1: concept resident_population, coverage 2012–2026, no warning that "ultimii 30 de ani" is not covered and no mention of the 1992+ domicile series. The 2026 value (POP107D, newer vintage) is not in the answer. |
| 05 | EN "Which 10 counties have the highest average gross monthly wage?" | discover (EN) -> describe FOM107E_judete -> find_dimension_values ECON_ACTIVITY "total" (empty) -> rank_entities (refused) -> discover RO "câștigul salarial mediu brut lunar pe județe total economie" | 5 | failed | No ranking possible. | Call 1 (EN): 0 concepts, families FOM107A/E/C. The RO wording finds concept `gross_earnings` (alias gap in EN). `describe` note: "INS also publishes the total… our download does not include it". `rank_entities`: `unsupported_measure`. Even without the gate there is no all-activity, both-sex cell to rank. |
| 06 | RO "Câți născuți vii au fost în București în 2023?" | discover -> (user picks residence) query_data POP201H_judete | 2 | clarification, then answered | Yes: 15,952 (usual residence). | `needs_clarification` domicile vs residence: correct. The `newer_vintage` warning then points to POP201K with no call that opens it. |
| 07 | EN "Compare the population of Cluj-Napoca and Iași in 2021" | discover (EN) -> discover RO domicile -> find_dimension_values REF_AREA_2 "cluj-napoca" -> same "iasi" -> query_data POP107D_grupe_localitate | 5 | answered (after **GUESS**) | Yes: Cluj-Napoca 328,108; Iași 390,832 (domicile, 1 Jan 2021). | `ambiguous_place`: "Cluj reads as a city, but this indicator is published by county… city-level figures are not resolved by this tool." False: city-level domicile data exists (used in Q02, Q08). The repair needed the dataset name from another question. Resident population has no city level, but the message does not say so or offer domicile. |
| 08 | RO "Top 10 cele mai mari orașe din România după populație" | discover -> rank_entities POP107D_grupe_localitate cities year null | 2 | answered | Yes (domicile, 1 Jan 2026): București 2,108,049; Iași 370,437; Cluj-Napoca 324,860… | None. The same dataset resolves a named city to the county in Q07. |
| 09 | EN "How many tourists stayed overnight in Brașov county in 2023?" | discover -> (**GUESS**: user means tourists, not nights) describe TUR104B_judete -> query_data | 3 | clarification, then answered (partial) | 1,556,679 tourist arrivals (sum over 19 structure types and 2 origins; hierarchy not verified). | Choices are "Tourist overnight stays" or "Tourism intensity". Arrivals (`TUR104B_judete`) is only an unverified family hit. The offered `action` answers a different question (nights). |
| 10 | RO "Cum a evoluat rata inflației lunar în 2024?" | discover -> describe IPC102A -> find_dimension_values TIME_PERIOD "2024" -> query_data 36 rows | 4 | partial | Monthly index for 3 categories only (food, non-food, services). No overall CPI. | `needs_clarification` (previous month vs since December). Choice text: "fără celulă pentru total, doar categorii mari". The model must build the 12-month filter by hand (`period_not_single`). |
| 11 | RO "Care județ are cea mai mare rată a mortalității infantile?" | discover -> describe POP209A_judete -> rank_entities (refused) -> query_data (refused) | 4 | failed | No county ranking. Only urban and rural separately. | Call 1: two families, no concept (POP209A domicile? POP209B usual residence: model guesses). `rank_entities`: `unsupported_measure`. `query_data`: `missing_weights`; recovery is honest (keep RESIDENCE). The total over RESIDENCE is not in the download. |
| 12 | EN "Average life expectancy in Romania by sex over time" | discover -> describe POP217B -> query_data (refused) -> describe TCP0341 | 4 | failed | No national series. Only 8 regions (POP217B) or counties (TCP0341). | Call 1: 0 concepts, 5 families. POP217B note: "INS also publishes the total… our download does not include it". `missing_weights`: "A labelled unweighted mean is available only if the user accepts it" (not a national rate). |
| 13 | RO "Câți elevi sunt în învățământul liceal în județul Iași în 2022?" | discover -> describe SCL103F_judete -> find_dimension_values (slip: wrong column name, `unknown_column`) -> find_dimension_values NIVELURI_DE_EDUCATIE "liceal" -> query_data | 5 | answered (after **GUESS**) | 24,089 for "liceal secundar ciclul 2". Plausible; not verified against the other overlapping levels. | Call 1: 0 concepts. The 5 matching levels overlap ("liceal secundar ciclul 2", "secundar ciclul 2 (liceal și profesional)", postliceal…): the tools give no hint which one is "liceal". The wrong-column call was the author's slip, not a tool fault. |
| 14 | EN "Which counties lost the most population since 2011?" | discover -> discover "… domicile population" (**GUESS**) -> compare_periods POP107A_judete_grupe 2011→2025 asc | 3 | answered | Yes (domicile): Prahova −79,126, Teleorman −76,771, Olt, Hunedoara, Buzău. | Call 1: concept resident_population (2012–2026), `period_unavailable` for 2011, no alternative offered. The domicile concept's `next` is a `query_data` for one year, not `compare_periods`. |
| 15 | RO "Prețul mediu al apartamentelor în București în 2024" | discover -> discover "prețuri imobiliare locuințe vânzare chirii" | 2 | no data | Correct to say no data. | Both calls: `status ok`, "5 rezultat(e) de căutare pe familii": exports, services, agricultural prices. No "no match" signal. |
| 16 | EN "How many crimes were reported in Cluj county in 2023?" | discover | 1 | no data | Correct to say no data (closest: domestic violence cases, TRW1632_judete). | `status ok` with 3 families (domestic violence, one irrelevant language survey). |
| 17 | RO "Top 5 județe după numărul de locuințe noi terminate în 2023" | discover -> describe LOC104A_judete -> rank_entities (refused `source_total_mismatch`) -> rank_entities LOC104A (the recovery's candidate) -> query_data check | 5 | answered, probably wrong | Rank: București 18,654; Ilfov; Constanța; Timiș; Cluj. The check query shows București = 13,834 (private) + 4,820 ("Din care: din fondurile populației"): a subset is summed with its parent. | Child `rank_entities`: "părțile SURSE_DE_FINANTARE nu însumează Totalul INS" (correct refusal). Its recovery proposes the parent dataset, which has the same dimension and **no refusal**, only `unverified_total`. The parent answer is likely double counted. |
| 18 | EN "Romania total exports by year" | discover -> describe EXP101I -> query_data group_by TIME_PERIOD | 3 | partial | 161 monthly values (2013-01 to 2026-05), no annual figure. | Call 1: 0 concepts; EXP101I is monthly (sum of 10 sections × intra/extra). No tool aggregates months to years; the model would add 12 numbers by hand. |
| 19 | RO "Care este câștigul salarial mediu net în Timiș față de media pe țară?" | discover -> run_recipe net_earnings_county areas Timis | 2 | answered | Yes: Timiș 5,508 lei vs national TOTAL 4,959 (2024). | None. The national value sits in `aggregates` under `TOTAL`, not in `rows`. |
| 20 | EN "Which county has the highest population density?" | discover -> discover RO "populația pe km2…" | 2 | no data | Correct: no published density series in the corpus (title search finds none). | `unsupported_operation`: "Ask separately for the population ranking or the reviewed overnight-stays-per-resident recipe." The tourism recipe is off topic. The refusal runs before any family search, so a published series could never be found. |

## Failures by cause, ranked by questions affected

A question can have more than one cause. Counts are questions, not calls.

| Rank | Cause | n | Questions |
|---|---|---|---|
| 1 | No reviewed concept: only unverified family search | 7 | 01, 05 (EN), 11, 12, 13, 17, 18 |
| 1 | Misleading or empty message | 7 | 01, 04, 07, 09, 15, 17, 20 |
| 3 | Missing data: INS "Total" cell not in the download (rates, indices, averages), or no source (area) | 5 | 05, 10, 11, 12 (Total cell); 01 (county area) |
| 4 | Tool refusal too strict (`rank_entities` on a rate with one value per entity) | 3 | 01, 05, 11 |
| 4 | Wrong dataset or unsafe selection offered | 3 | 09 (arrivals), 13 (overlapping levels), 17 (parent double count) |
| 4 | Other tool gap: city handling, municipii filter, month to year | 3 | 02, 07, 18 |

Detail of the misleading messages:
- `constraint_not_applied` flags "per capita" / "pe locuitor" as an unapplied denominator when it names the measure (Q01).
- The full question goes into the family search with filler words ("top", "daca poti"): Q01 call 1 found no GDP table, while "PIB pe locuitor județe" finds CON103H_judete first. Short queries work; long ones fail.
- "City-level figures are not resolved by this tool" (Q07) is false for domicile population.
- `status: ok` with unrelated families when nothing matches (Q15, Q16).
- `rank_entities` refusal text has no `recovery` (Q01, Q05, Q11).
- The `source_total_mismatch` recovery points to a parent that is not checked (Q17).
- Unsupported-operation text names the tourism recipe for a density question (Q20).
- No warning when the asked period ("ultimii 30 de ani", "since 2011") is outside the concept's coverage, and no alternative (Q04, Q14).

## Proposed fixes

Mapping: A and B are the parts of [09-mcp-usability.md](09-mcp-usability.md). "New" is not in the brief. The owner prioritizes.

| # | Fix | Questions | Map |
|---|---|---|---|
| 1 | Accept a rate in `rank_entities` and `compare_periods` when the method is `single_row` or `aggregate_row`; reword the refusal; add a `recovery` | 01, 05, 11 (part) | A |
| 2 | Reviewed concepts: GDP per inhabitant (CON103H) and total GDP (CON103I) | 01 | B |
| 3 | More reviewed concepts, same format: national life expectancy, infant mortality, dwellings completed, pupils by education level, annual exports. Add EN aliases for the existing earnings concepts ("wage", "earnings") | 05, 11, 12, 13, 17, 18 | New (extends B) |
| 4 | Parent dataset: apply the INS Total check (or the "Din care" subset rule) to LOC104A as the split child does; stop the `source_total_mismatch` recovery from proposing an unchecked parent. Correctness risk, first in time | 17 | New |
| 5 | Discovery text: do not flag a measure's own denominator as unapplied; drop filler words from the family query; return a "no match" status when no family is close; stop offering the tourism recipe for density; warn when the requested period exceeds coverage and name the longer series | 01, 04, 14, 15, 16, 20 | New |
| 6 | Named city: resolve to the locality dataset (domicile) instead of the county; fix the `city_not_county` message | 07 | New |
| 7 | Total cells: serve the INS Total for non-additive datasets (rates, life expectancy, CPI) through the published-totals mechanism or recipes. Needs owner approval (data and download scope) | 05, 10, 11, 12 | New |
| 8 | County area: find a source (`core-assets` or INS). Brief says: report the candidates and stop and ask | 01 | B |
| 9 | Month-to-year aggregation for additive monthly series (for example exports) | 18 | New |
| 10 | Arrivals vs nights as a choice in tourism discovery; hint for overlapping education levels | 09, 13 | New |
| 11 | `next_call` for a change question should offer both orders (or `compare_periods` with `order`); entity class "municipii only" | 02, 14 | New |
| 12 | Hidden `query_data` table in the Ask page (2026-11-18 run, question 1) | 01 | Out of scope here (Ask UI; AQ-08 area) |

## Assumptions and limits

- The author is a model but not the live one (DeepSeek, Claude Desktop). Tool choice here is more careful than
  Ask's DeepSeek run. Dispatch counts are lower bounds.
- Q02 passed on the first call: the 2026-11-18 Claude Desktop failure (`level_unavailable` for resident population)
  does not reproduce on this code, which now assumes domicile population for cities.
- Correctness was checked against the tool output only (no outside figures). Q17 "probably wrong" rests on the
  arithmetic 13,834 + 4,820 = 18,654 and the child's INS-total refusal, not on the INS published figure.
- Q09's 1,556,679 sums 19 structure types without a verified hierarchy.
- Q14 used "domicile population" as an added search word: a **GUESS** a model must make itself.
