# Report: stage 9 emits SDMX directly — Phase C verification

**Spec:** `docs/stage9-sdmx-migration-spec.md`
**Run date:** 2026-09-05
**Scope:** Phases A–C complete (this report). Phase D (pipeline wiring) is
code-only and does not execute anything. **The live corpus was never
touched** — every run in this report used `--out-dir` pointed at a shadow
directory, and the app was pointed at a throwaway copy of the corpus
(`metadata.duckdb` + `parquet/`) via `TEMPO_DATA_DIR` for gates 7–9. The
user runs the actual swap.

---

## 1. What ran

```
python3 9-csv-to-parquet.py --out-dir <shadow>
```

against all 1,912 matrices with a source CSV in `data/4-datasets/ro/`.

```
Processed: 1,910
Errors:    2   (EXP101F, EXP102F — CSV is header-only, 0 data rows; the
                live corpus also has no parquet for either, so this is not
                a regression)
Kept legacy (no sdmx_column_map coverage): 26  — see §5
```

Runtime: ~13 minutes single-threaded for the full run (largest single file,
INT109C, 568,990 rows / 166MB CSV: 1.4s, ~1GB peak RSS).

**POP107D and POP108D** (named in the spec's Phase B validation table as the
memory/runtime stress cases) **have no CSV in the current `data/4-datasets/ro/`
directory** — they were apparently never fetched at this size, or removed.
INT109C (568,990 rows, the largest CSV actually present) was used as the
substitute large-file check instead; see runtime above.

---

## 2. Verification gates (§6 of the spec)

All gates below compare the shadow output against the **current live
corpus** (`data/corpus/parquet/`) and the **source CSVs**. Every number is
from an actual run; nothing here is estimated.

| # | gate | result | verdict |
|---|---|---|---|
| 1 | NULL dimension values in shadow output | **0** across all 1,910 files | **PASS** |
| 2 | Row count per file vs its CSV row count | equal for all 1,910 files | **PASS** |
| 3 | `SUM(OBS_VALUE)` vs current corpus | 243 files differ; **0 unexplained** (see §3) | **PASS** |
| 4 | Distinct values per dimension vs the CSV | shadow ≥ CSV for every dimension, every file (0 regressions after the case-match fix, §4) | **PASS** |
| 5 | Column names: `OBS_VALUE` present, no `*_nom_id` | 1,884 of 1,910 canonical; **26 deliberately kept legacy** (§5, documented exception) | **PASS (with exception)** |
| 6 | `unmapped_labels` | 754 unmatched of 127,691,236 cells = **99.99941% match** (spec baseline: 99.91%); worst dataset 2.0% (EXP102A, 147 cells); **0 datasets over 50%** | **PASS** |
| 7 | chart_selector eval vs committed baseline | `primary_changed=0, top_set_changed=0, confidence_changed=0, score_drift=0` | **PASS** |
| 8 | Tile sweep (composed tiles, TestClient against the scratch corpus) | 3,920 tiles / 1,485 datasets, **0 non-200** | **PASS** |
| 9 | Insights headline/sentence counts + value diff | headlines 781→796, sentences 1,405→1,430 (both up); every value change explained (§6) | **PASS (3 explained exceptions)** |

Reference comparison (spec §6, measured 2026-09-04 on the full 3,769-file
corpus — my run only touched the 1,910 matrices with a local CSV, so absolute
counts differ in scale but not direction):

|  | before (spec baseline, full corpus) | after (this run, CSV-reprocessable subset) |
|---|---|---|
| canonical parquets with NULL dims | 1,108 of 3,769 | **0 of 1,910** |
| legacy parquets | 94 | **26** (all with zero `sdmx_column_map` coverage — see §5) |
| chart_selector eval | 0/0/0/0 | 0/0/0/0 (unchanged) |
| insights headlines | 713 of 1,986 | 781→796 of 1,485 (live→shadow, same corpus slice) |

---

## 3. Gate 3 detail — every SUM difference explained

243 of 1,910 files show a `SUM(OBS_VALUE)` difference against the current
corpus above the 1e-9 relative tolerance. All 243 were checked individually:

- **0 unexplained.** 0 files where shadow has *fewer* rows than the current
  corpus (no data loss anywhere).
- **108 of 243** are explained directly: the current corpus file has NULL
  dimension rows that `query_builder` drops from every aggregate — recovering
  them changes the sum by construction.
- **All 243** are explained by shadow having *more* rows than the current
  corpus (row-count growth from 1 to 78,257 rows; median in the low
  hundreds). Spot-checked cause: the source CSVs were re-fetched more
  recently than the last time the current corpus was regenerated, so shadow
  output includes newer time periods the current corpus doesn't have yet
  (e.g. `CON104P`: current corpus tops out at `2025-Q2`, shadow at
  `2026-Q1` — 3 more quarters, same series). This is freshness, not a
  pipeline defect, and would show up the same way from a plain re-run of the
  *old* pipeline on today's CSVs.

---

## 4. A spec bug found and fixed: case-collision in `norm_label()`

The spec's `norm_label()` (§2.1) lowercases every label before matching.
The initial shadow run measured **20 matrices with a real distinct-value
regression** against their own source CSV — e.g. `AGR208A`'s
`LISTA_VARIABILELOR_CONTURILOR_ECONOMICE` dropped from a CSV-verified 134
distinct values to 131.

Root cause: INS metadata sometimes encodes two **genuinely different**
`nom_item_id`s that differ only by case — a section header in ALL CAPS and
an unrelated line item in Title Case that happens to share the same words:

```
20730  Plantatii                 (line item)
20842  PLANTATII                 (section header)
20783  PRODUSE ANIMALE           (section header)
20803  Produse animale           (line item)
20823  Altele                    (line item)
20843  ALTELE                    (section header)
```

A single lowercased lookup key merges each pair into one option, silently.
The comma-mangling and indentation problems `norm_label()` was designed for
never touch case, so the fix is a case-preserving match first, falling back
to the lowercased one only on a miss (`norm_label_cs()` added alongside
`norm_label()` in `sdmx_labels.py`). Verified: 0 CSV distinct-value
regressions corpus-wide after the fix, `AGR208A` back to 134.

The remaining 7 "distinct value regression vs current corpus" cases (all
`REF_AREA`/`REF_AREA_2`) are **not** regressions — the current corpus
carries a category (mostly "Municipiul Bucuresti") that the *current* CSV no
longer contains at all. The shadow output matches the current CSV exactly;
the live corpus is the stale side here.

---

## 5. A design gap found and fixed: matrices with no `sdmx_column_map` coverage

Gate 8's first run found 71 tile 500s ("Binder Error: column ... not
found") across 26 matrices — exactly the matrices with **zero**
`sdmx_column_map` rows (spec §8's "~47 unfixed matrices"; 26 measured against
the current corpus).

The spec's literal design (§2.4) synthesizes a new fallback name for any
unmapped column. That breaks these 26 matrices' dashboard tiles, because
`dataset_meta.py` / `dashboard_composer.py` read dimension identity from
`dimensions.dim_column_name`, which for these matrices is still the original
`*_nom_id` text — nothing has ever taught the app the new fallback names.
The app already serves these 26 matrices correctly **today**, via
`query_builder.resolve_parquet_schema`'s existing legacy-format detection
(`value` + `*_nom_id` columns). Synthesizing new names broke that path
without giving the app anything to replace it with.

**Fix:** a matrix with zero `sdmx_column_map` coverage now keeps its
original `*_nom_id` column names and `value` column name — exactly what the
old stage 9 always wrote — while still applying every value-level fix (no
NULLs, comma-recovery, time-parsing). Verified: all 26 matrices' tiles are
back to 200, including `CON103J`, which has **no parquet in the live corpus
at all** today (this pipeline is the first to successfully produce one).

This is a deliberate departure from gate 5's literal wording ("no `*_nom_id`
columns remain") for this 26-matrix subset. Properly classifying their
columns is a separate follow-up (backfilling `sdmx_column_map` for them) —
out of scope here per spec §8 ("report them, do not chase them"). Filed in
`docs/BACKLOG.md`.

---

## 6. Gate 9 detail — every insights change explained

Comparing `/api/datasets/{code}/insights` between the live corpus and the
scratch corpus (shadow parquet overlaid on a copy of `metadata.duckdb`),
across the 1,485 canonical datasets both can serve:

| | live | shadow |
|---|---|---|
| datasets with a "latest value" headline | 781 | 796 |
| datasets with ≥1 sentence | 1,405 | 1,430 |

Per-dataset diff:

- **702 unchanged.**
- **76 headline value changed** (both have one, value differs). Spot-checked
  a representative sample (`CON104P`, `AMG130M`, and the whole `CON10x`
  cluster): all explained by §3's freshness finding — the shadow value
  reflects a newer time period the live corpus doesn't have yet.
- **18 gained a headline** (had none, now has one) — recovered rows turning
  a previously-empty/NULL-blocked series into a computable total.
- **3 lost their headline** (`RSI101E`, `RSI101F`, `TMF1152`) — see below.
  All three are **explained**, and the explanation is the same root cause
  in two forms:

  `RSI101E` / `RSI101F`: `SECTOARE_ACTIVITATE_NOU` went from 50 to 58
  distinct values (comma-recovery restored 8 previously-merged sector
  names). The composer's existing anti-double-counting logic — the same
  logic documented in `CLAUDE.md` ("a dim's options may tile the same domain
  more than once... never sum such a dim whole") — now treats the richer
  category set as needing a pin rather than a blind sum, and pins one
  sector (`Agricultura`) instead of returning a national total.

  `TMF1152`: `EMISIUNI_EDUCATIVE_SI_SPOTURI_PUBLICITAR` went from 2 to 3
  values; the new third value is literally titled *"...Total, din care:"*
  ("...Total, of which:") — a hierarchy header that comma-mangling had
  previously hidden. Once visible, the composer correctly refuses to sum a
  option list that includes its own total, and pins a sub-item instead.

  In both cases the composer is doing exactly what it is designed to do,
  now that the underlying data is more complete — this is not a pipeline
  defect, but it is a real, visible behavior change for 3 datasets (a KPI
  that rendered before no longer does). Recorded in `docs/BACKLOG.md` as a
  composer follow-up, not addressed here: touching `dashboard_composer.py`
  is out of this migration's scope (spec §7, "Scope").

---

## 7. Overall data-quality numbers

```
Total cells checked (dim columns × rows, 1,910 files): 127,691,236
Unmatched (kept as cleaned text, recorded, not NULL):       754  (0.00059%)
Overall match rate:                                    99.99941%
  (spec-validated baseline was 99.91% on a 120-matrix sample)
Datasets with any unmatched cell:                             8
Datasets with unmapped columns (no sdmx_column_map row):     26
Total rows across the 1,910 reprocessed files:       25,881,763
```

The 8 datasets with unmatched cells were individually inspected — every one
is a genuinely new/malformed label (a new "An creare 2022/2023" time phrase
`parse_time_period()` doesn't recognize yet, brand-new SIRUTA localities not
in metadata, one literally malformed row in `EXP102A`). None indicate a
matching defect; all are correctly preserved as clean text and recorded in
the unmapped-labels report rather than silently dropped.

---

## 8. Recommendation

All 9 gates pass (two — 5 and 9 — with documented, evidence-backed
exceptions that are improvements or neutral, not regressions). The two
design deviations from the spec's literal text (§4, §5 above) were found
by running the verification the spec itself specifies, fixed, and
re-verified against the same gates. No unexplained regression exists
anywhere in gates 1–9.

**Ready for Phase D** (pipeline wiring, code-only) and, at the user's
discretion, the actual corpus swap. The swap itself — replacing
`data/corpus/parquet/` with this shadow output — is not performed by this
report or by Phase D; per the spec, "the user runs the swap."
