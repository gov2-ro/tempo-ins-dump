
**Role:** You are an expert Product Designer specializing in Data Visualization and Complex Dashboards.
**The Goal:** Design the UX/UI architecture for a "Universal Statistical Data Explorer." The goal is to make complex government/institutional data accessible to non-experts without dumbing it down.
**The Data Model:**
Assume all datasets are normalized into a "Long Format":
* **Metric:** 1 Value column.
* **Fixed Dimensions:** 1 Time column, 1 Geo column (optional).
* **Variable Dimensions:** 1 to 4 Categorical columns (e.g., Demographics, Industry).


**The Challenge:**
Since the "Variable Dimensions" change per dataset, the UI must be **adaptive**.
**Request:**
Please outline a UI approach for the **"Dataset Detail View"** (the page where a user explores a single dataset). Specifically:
1. **Layout:** How do I arrange the Chart, the Data Table, and the Controls?
2. **The "Pivot" Problem:** How do I let users choose which dimension is the X-axis (e.g., Time) and which are the Filters (e.g., Geo)?
3. **Visual Hierarchy:** How do we handle metadata (units, sources, footnotes) without cluttering the view?


**Deliverable:**
A text-based wireframe or component breakdown of this specific view.

---

### 3. Initial UI Approach (Preview)

Since you asked for help with the UI right now, here is a high-level approach based on your "1 Value, 1 Time, 1 Geo, N Dims" pattern.

The best pattern for this is the **"Configuration Sidebar + Canvas"** model.

#### The "Sentence Builder" Concept (Natural Language UI)

Instead of a wall of dropdowns, use a "Sentence" at the top of the screen to control the query. This is very friendly for non-experts.

> **"Show me [Unemployment Rate] in [France] broken down by [Age Group] over [The Last 10 Years]."**

* **[Unemployment Rate]:** The Value (Locked)
* **[France]:** The Geo Filter
* **[Age Group]:** The "Series" (what generates the lines on the chart)
* **[Last 10 Years]:** The Time Filter

#### The "Pivot" Sidebar

On the left (or right), you have a "Dimension Mapper." This solves the problem of "Which dimension is the Chart Legend vs. which is just a Filter?"

**Components:**

1. **X-Axis:** Defaults to "Time" (User can swap to "Geo" for a map view).
2. **Group By (Lines/Bars):** Dropdown to select one of your 1-4 dimensions (e.g., "Gender").
3. **Filters (The rest):** All other dimensions appear here as multi-select checkboxes.

**Example:**

* If "Gender" is the **Group By**, the chart shows 2 lines (Male/Female).
* The "Geo" and "Age" dimensions become **Filters** (single select or multi-select).
