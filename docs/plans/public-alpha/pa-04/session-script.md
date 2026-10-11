# PA-04 formative session script

Five sessions, about 40 minutes each, run by the maintainer on the release
candidate (not production). Target participants: local journalists or civic
analysts who do not know TEMPO codes. This script is preparation; recruitment
and outreach are the maintainer's decision and action.

## Before the session

- Candidate URL, commit and generation id written on the notes sheet.
- Fresh browser profile (no saved state), desktop or the participant's own
  laptop. Phone for one task if the participant usually works on mobile.
- Consent read aloud and noted (template below). Record screen/audio only with
  explicit consent; otherwise take notes only.
- Rotate the task order per participant (table below). Do not demonstrate the site.

## Consent (read aloud)

> We are testing a website, not you. There are no wrong answers. I will ask you
> to do a few tasks and think aloud. With your permission I will [take notes /
> record the screen and audio] only to improve the site. I won't publish your
> name or the recording, and I will delete the recording by [date]. You can stop
> at any time. Is that OK?

Note: consent yes/no, recording yes/no, date.

## Opening (2 min)

"Imagine you are preparing a local story or a briefing about your county. Use the
site as you would on your own. Please say what you are looking for and what you
expect as you go."

## Tasks (read the ordinary-language prompt only)

| # | Prompt | Success means |
|---|---|---|
| T1 | "How has the number of people living in Cluj county changed in recent years? What does 'resident' mean here?" | Finds resident population (POP105A) for Cluj county, states the latest value/year (2025: 697,030), explains usual residence vs domicile in their words, and notices or is told about the 2021→2022 census break |
| T2 | "How does the average net salary in Cluj compare with Iași and Bucharest? For which year?" | Reaches FOM106E for the three counties and states the comparison period. While Q2 is blocked, success = understanding that the total is unavailable and why, not misreading a sector/sex value as the average |
| T3 | "Which counties have the highest registered unemployment? Is that the same as the 'BIM' rate?" | Reaches SOM103A by county and distinguishes registered vs survey (BIM). While Q3 is blocked, same rule as T2 |
| T4 | "Which counties have the most tourist overnight stays per resident? What population is used? Is any county left out?" | Opens the tourism-intensity page, names the top county and year, says the denominator is resident population on 1 January of the same year, and finds the exclusion line (if any) |
| T5 | "Share one of these answers with a colleague, and save what they would need to check your number later." | Copies a link that reopens the same selection and downloads the evidence ZIP. Optional: says what is inside |

Order rotation: P1 T1-T5, P2 T3 T1 T5 T4 T2, P3 T4 T2 T1 T3 T5, P4 T2 T5 T3 T1 T4,
P5 T5 T4 T2 T3 T1 (T5 first means "pick any statistic about your county").

Hints, in order, only when stuck for 2 minutes: (1) "Where would you start
looking?" (2) "Is there a search?" (3) point to the element. Each hint changes the
outcome to "completed with help".

## Per-task record

| Field | Values |
|---|---|
| Outcome | done alone / done with help (hint level) / failed / abandoned |
| Time | mm:ss to answer or abandonment |
| Path | search query typed, pages visited |
| Wrong selections | wrong concept (e.g. domicile, BIM, gross), wrong period, wrong place level |
| Interpretation | the participant's explanation of the number, verbatim if possible |
| Confident and wrong? | yes/no. Any yes is a release blocker until fixed |
| Share/export | link reopened the same view? ZIP downloaded? |
| Quotes / confusion | free text |

## Closing (5 min)

- "What was the most confusing moment?"
- "Would you trust these numbers in an article? What would you need to check?"
- "Anything you expected to find and didn't?"

## After the five sessions

Fill `pa-04/sessions.md` (one table per participant, plus a summary by task).
Target: at least 4 of 5 complete each find/compare/share task alone, and no
unresolved defect makes anyone confidently report the wrong concept or period.
Fix recurring blockers and every misinterpretation defect, rerun the automated
checks, and record the final candidate commit. Five sessions inform design;
they do not establish a population-wide success rate.
