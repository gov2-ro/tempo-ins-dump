
A few observations from real-world stat explorers (Eurostat, OECD.Stat, World Bank DataBank, Our World in Data):

**What works well:** Our World in Data's progressive disclosure, Eurostat's dimension-as-filter approach, Tableau Public's drag-and-drop slot model. **What's painful:** OECD.Stat's modal-heavy dimension selection, most agencies burying the "change chart type" option, poor defaults that show 200 series on one line chart.

**Key UX principle I'd push:** Don't make users configure everything before seeing anything. Show a smart default chart immediately, then let them reshape it. Think "direct manipulation" over "form-then-submit."

Let me build the wireframe:Here's an interactive wireframe you can click through. Let me walk you through the key design decisions and push back on a few of your initial ideas:

## Layout Architecture

**Three-zone model:** page filter bar → left sidebar (config) → main canvas. This mirrors what works in Tableau/Power BI but adapted for a single-dataset SDMX context where you don't need a data source picker taking up space.

**The "Smart Presets" tab** is the most important UX idea here — most stat agency users aren't visualization experts. Auto-configured presets like "Trend by cause" or "Age pyramid" let them get a useful chart in one click, then tweak from there. The presets encode your chart-type-to-dimension logic.

**Dimension slots** (X / Series / Facet / Filter) — this is the Tableau "marks card" pattern simplified. The key insight: every unassigned dimension auto-becomes a page filter. Users don't need to think about filtering explicitly; they just map what they care about.

## Chart Type Recommendations I'd Refine

A few challenges with your initial list:

- **Sankey** — I'd drop it for this context. Sankeys imply flows between categories (budget allocations, migration). SDMX statistical tables rarely have that structure. It'll confuse more than help.
- **Matrix bubble / pie-in-bubble** — interesting but niche. I'd offer it as an advanced option, not a default. Heatmaps cover the same 2D categorical space more readably.
- **Population pyramid** — great, but the trigger should be stricter: only when you detect an age-group dimension with ordered bins AND a sex dimension with exactly 2 non-total levels. Otherwise you get weird pyramids.
- **Table with heatmap** — yes, absolutely. Conditional formatting on the value column is low-effort, high-value. I'd make it the default table mode.

## Additional Ideas Not in Your List

- **Slope chart** — for comparing two time points across many categories/countries. Cleaner than grouped bars for "2019 vs 2023" comparisons.
- **Bump chart / rank chart** — for tracking rank changes over time (e.g., which country had highest mortality rate each year).
- **Sparkline table** — a table where each row has an inline mini-line-chart. Excellent for "overview of all countries over time" use cases.
- **Diverging bar** — for showing deviation from a reference (EU average, previous year, etc.). Very natural for stat data.
- **Dot plot / Cleveland dot plot** — often better than bar charts for comparing many categories (20+ countries). Less ink, easier to read.

## Questions Before We Go Deeper

Want me to iterate on any of these areas, or should we explore specific interaction patterns (like how dimension drag-and-drop should work, or how the smart chart recommendation engine should pick defaults)?