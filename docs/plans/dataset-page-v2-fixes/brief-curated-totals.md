# DP-01 Part 1 (option B) — a curated list of total options (brief)

Owner decision, 2026-11-26: fix "Total indisponibil" with a short, hand-checked list (option B).
The automatic profiler rule (option A, `brief.md` Part 1 Step 2) waits for the weekly refresh (HZ-5b).
This list becomes A's test cases later.

Work in a worktree. Commit only your own files. Do not deploy, and do not change the live corpus.

## The problem

Total detection recognises a total only by a label that starts with a total word (`TOTAL_RE`).
"Consum total de alcool (alcool 100%)" does not, so the KPI of `CLV104A_litri_alcool_pur_100` would sum
2.0 + 8.7 = 10.7. The source-total gate withholds that sum and the page shows "Total indisponibil".
The correct KPI is INS's own total: 8.7 (2024).

## The list (reviewed by Opus against the option lists and values)

Create `app/data/curated_totals.json`. Each entry names the dataset code, the column and the exact
option value as stored in the parquet, plus a short reason. Include these:

| code | column | total option |
|---|---|---|
| CLV104A_litri_alcool_pur_100 | PRINCIPALELE_PRODUSE_ALIMENTARE_SI_BAUTU | Consum total de alcool (alcool 100%) |
| CON113A, CON113B, CON114A, CON114B | ACTIVE_NEFINANCIARE_VALORI_BRUTE | N11G Total Active fixe, brute |
| CON113C, CON113D | ACTIVE_NEFINANCIARE_VALORI_NETE | N11N Total Active fixe, nete |
| ECC501A, TNX1252 | TYPE | Deseuri menajere si asimilabile colectate de la populatie si operatori economici - total, din care: |
| TOW1331 | CATEGORY | Deseuri menajere si asimilabile generate - total, din care: |
| TAZ0221 | CATEGORY | Suprafata terenurilor intabulate pe total tara |
| TFP0512 | TIMP_PETRECUT_CU_ACTIVITATI_CASNICE_SI_D | Ingrijirea gospodariei si familiei si ajutor acordat altor gospodarii - TOTAL, din care: |
| TMF1152 | EMISIUNI_EDUCATIVE_SI_SPOTURI_PUBLICITAR | Emisiuni educative si mesaje de interes public cu rol de educatie in caz de cutremur - Total, din care: |
| TSZ1682, ZEC1631 | CATEGORY | Infractiuni de coruptie si serviciu-total, din care |
| TFF4102 | DEPOZITELE_GOSPODARIILOR_POPULATIEI | Depozitele gospodariilor populatiei - total, din care: |

Copy each value from the parquet, not from this table (spaces and punctuation must match exactly).
If a value does not exist in its dataset, stop and report it.

Rejected after review (do not add): `CON115A` (its dimension holds `N12N Stocuri`, which is outside
fixed assets, so `N11N` is not the dimension's total); `TKA0931` (two measures, production and GVA,
each with its own total); `AGR202A_*` (two candidates and missing cells); unit-measure labels
("Cheltuieli…: Total"), "Din total …" labels and `ASS118E_*` (false positives in the scan).

## The change

1. `app/services/dimension_structure.load()` reads the list once (cache it). For a listed
   (code, column), it sets `aggregate_value` to the listed option and `additive` to `False`. Create
   the column entry when the profiler has none. Keep `source='curated'` (or a similar marker) so a
   reader can tell it from a profiled aggregate. Every other field stays as the profiler wrote it.
2. Check that the query-time policy then pins the option (method `aggregate_row`): the KPI is the
   total's own value, never a sum, and the source-total gate does not refuse it. If the gate still
   refuses, find why and stop and report before you change the gate.
3. Static site: find how `scripts/build-static.py` exports the structure and policies per dataset,
   and make sure the exported structure carries the curated aggregate. `policy.js` must then behave
   the same as Python. Keep `tools/static-engine/parity.mjs` and `api-parity.mjs` passing.
4. `scripts/check-kpi-totals.py`: a listed column must not report `no_total_option`. It must use
   the listed option as the total (read through the same loader or the same JSON file; no second copy
   of the list).
5. A test validates the JSON file: every entry has code, column, option and reason; no duplicate
   (code, column). Add a `corpus`-marked test that each listed option exists in its parquet.

Do not touch `TOTAL_RE`, the profiler (`13-dimension-structure.py`) or `kpi_total_checks` rows.

## Acceptance

- A synthetic fixture: a dataset with "Consum total de X" and one part, listed in a test copy of the
  list. The insights KPI returns the total's latest value; not the sum and not a refusal.
- The same fixture without the list entry: today's behaviour (refusal) is unchanged.
- Real data, read-only, through the in-process app (dev MCP `tempo_call_endpoint` or TestClient):
  `/api/datasets/CLV104A_litri_alcool_pur_100/insights` shows 8.7 for 2024. Report the KPI for every
  listed dataset, before and after.
- `python -m pytest tests -q` passes (run it once, not in parallel with another suite).
- Static parity tests pass. A browser smoke of the local v2 page of `CLV104A_litri_alcool_pur_100`
  shows 8.7 and no "Total indisponibil"; check the console.
- Add an entry in `docs/activity-history.md` and tick DP-01 Part 1 (option B) in `docs/BACKLOG.md`.
  Add an AGENTS.md line next to "Dataset notes" that says what the list is and when to edit it;
  stop and ask if you think the line belongs elsewhere.

Report what you measured and what you assumed. Stop and ask if a step would change a spec, an ADR,
an invariant, or a file outside `app/`, `scripts/build-static.py`, `scripts/check-kpi-totals.py`,
`tools/static-engine/`, tests and the docs named above.
