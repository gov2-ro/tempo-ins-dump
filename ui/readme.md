# Project: Romanian National Institute of Statistics - Data Navigator

## 1. Project Goal

The primary objective is to create a modern, intuitive, and value-added web interface to navigate and explore datasets from the 'Romanian National Institute of Statistics' (INS). The application will provide a user-friendly way to discover datasets, understand their metadata, and facilitate data exploration.

This will be a client-side application built with HTML, CSS, and JavaScript, leveraging the static data provided in the `/data` directory.

------

există datasets fără perioadă? !! **majoritatea** pare că au perioadă. dacă nu toate vezi care! 
if not ani, luni, trimiestre


mark date istorice as such - anything older than 10 years?
anything before 89?

pe domenii.

geo -> map
perioade -> timeline
perioade de tip multiplu -> filter, default - year

counters - 

ACC101B – only geo and year 
- map with period filter. 
- tabel w heatmap
- timeline per judet

ACC101C - simple counter
CAEN + an


## 1.1. Dimension Index Explorer (NEW)

In addition to the main dataset navigator, we now have a **Dimension Index Explorer** that provides specialized search capabilities for statistical dimensions and options.

### Files:
- **`dimensions.html`** - Interactive dimension and options search interface
- **`dimensions-style.css`** - Styles for the dimension explorer  
- **`dimensions-script.js`** - JavaScript functionality for dimension search
- **`data/dimension_index.json`** - Exported dimension index data

### Features:
- **Search functionality**: Find dimensions and options by name with real-time results
- **Filter options**: Search in dimensions only, options only, or both
- **File filtering**: Filter results by specific data files
- **File summary**: View all dimensions and options for each file
- **Dimension usage**: See which dimensions are used across multiple files
- **Statistics**: Overview of the indexed data with export timestamps

### Usage:
1. Generate the data: `python export-db-to-json.py`
2. Start local server: `python -m http.server 8000` 
3. Open: http://localhost:8000/dimensions.html

### Search Examples:
- "Perioade" (most common dimension)
- "Bucuresti" (geographic options)
- "Grade Celsius" (measurement units)

## 2. Data Structure Overview

The application will consume data from the following sources:

-   `data/indexes/matrices.csv`: The master list of all available datasets, linking a dataset `filename` (ID) to its name (`matrixName`) and category (`context-code`).
-   `data/indexes/context.json`: A hierarchical JSON defining the thematic categories and subcategories for navigation. This will be used to build the category tree.
-   `data/metas/{dataset_id}.json`: Contains rich metadata for each individual dataset, including its definition, dimensions, periodicity, and update history.
-   `data/datasets/{dataset_id}.csv`: The raw data for each dataset.

## 3. Core Features (MVP)

The application will be built with a two-pane layout, inspired by the supplied `meta-navigator.html` and `dataset-navigator 1.html` prototypes.

### 3.1. Left Pane: Category Navigator

-   **Collapsible Tree View:** A hierarchical navigator will be rendered based on `data/indexes/context.json`.
-   **Functionality:**
    -   Parents in the tree should be expandable/collapsible to show child categories.
    -   Each category node will display the number of datasets it contains.
    -   Clicking a category will filter the datasets displayed in the right pane.
    -   An "All Categories" option should be available at the top.

### 3.2. Right Pane: Dataset Viewer

-   **Dataset Cards:** Datasets will be displayed in a responsive grid layout. Each card will act as a summary and entry point for a dataset.
-   **Card Content:**
    -   **Header:** Dataset Code (e.g., `ART120E`) and full Title (`matrixName`).
    -   **Body:**
        -   A short snippet of the description (`definitie` from the meta file).
        -   Key metadata as tags, such as `Last Updated`, `Periodicity`, and `Unit of Measure`.
        -   A list of the main dimensions/columns.
-   **Interactivity:**
    -   Cards will be filterable via the Category Navigator and the Search Bar.
    -   Clicking a card will open a detailed modal view.

### 3.3. Search and Filtering

-   **Global Search Bar:** A prominent search bar at the top of the right pane will allow users to perform a text search across dataset titles, codes, and descriptions.
-   **Dynamic Filtering:** The dataset grid will update dynamically as the user types in the search bar or selects a new category.

### 3.4. Detailed Dataset Modal

-   When a dataset card is clicked, a modal window will appear, displaying comprehensive metadata from the corresponding `{dataset_id}.json` file.
-   **Modal Content:**
    -   Full Title and Description (`definitie`).
    -   Category path/breadcrumb (from `ancestors`).
    -   Data Sources (`surseDeDate`).
    -   Detailed list of all dimensions (`dimensionsMap`).
    -   Methodology, observations, and any other relevant notes.
    -   A direct link to download the corresponding `.csv` file from `data/datasets/`.
    -   Data preview - first 20 rows of the table

## 4. Phase 2: Future Enhancements

-   **Advanced Filtering:** Implement filtering based on specific metadata fields like periodicity, keywords, or dimensions.
-   **Data Preview:** In the modal, show a preview of the first few rows of the actual CSV data.
-   **Simple Visualization:** For selected datasets, generate basic charts (e.g., bar, line) to visualize the data directly in the interface.
-   **Bookmark/Favorites:** Allow users to mark datasets as favorites for quick access.

The application will consume data from the following sources:

-   `data/indexes/matrices.csv`: The master list of all available datasets, linking a dataset `filename` (ID) to its name (`matrixName`) and category (`context-code`).
-   `data/indexes/context.json`: A hierarchical JSON defining the thematic categories and subcategories for navigation. This will be used to build the category tree.
-   `data/metas/{dataset_id}.json`: Contains rich metadata for each individual dataset, including its definition, dimensions, periodicity, and update history.
-   `data/datasets/{dataset_id}.csv`: The raw data for each dataset.

## 3. Core Features (MVP)

The application will be built with a two-pane layout, inspired by the supplied `meta-navigator.html` and `dataset-navigator 1.html` prototypes.

### 3.1. Left Pane: Category Navigator

-   **Collapsible Tree View:** A hierarchical navigator will be rendered based on `data/indexes/context.json`.
-   **Functionality:**
    -   Parents in the tree should be expandable/collapsible to show child categories.
    -   Each category node will display the number of datasets it contains.
    -   Clicking a category will filter the datasets displayed in the right pane.
    -   An "All Categories" option should be available at the top.

### 3.2. Right Pane: Dataset Viewer

-   **Dataset Cards:** Datasets will be displayed in a responsive grid layout. Each card will act as a summary and entry point for a dataset.
-   **Card Content:**
    -   **Header:** Dataset Code (e.g., `ART120E`) and full Title (`matrixName`).
    -   **Body:**
        -   A short snippet of the description (`definitie` from the meta file).
        -   Key metadata as tags, such as `Last Updated`, `Periodicity`, and `Unit of Measure`.
        -   A list of the main dimensions/columns.
-   **Interactivity:**
    -   Cards will be filterable via the Category Navigator and the Search Bar.
    -   Clicking a card will open a detailed modal view.

### 3.3. Search and Filtering

-   **Global Search Bar:** A prominent search bar at the top of the right pane will allow users to perform a text search across dataset titles, codes, and descriptions.
-   **Dynamic Filtering:** The dataset grid will update dynamically as the user types in the search bar or selects a new category.

### 3.4. Detailed Dataset Modal

-   When a dataset card is clicked, a modal window will appear, displaying comprehensive metadata from the corresponding `{dataset_id}.json` file.
-   **Modal Content:**
    -   Full Title and Description (`definitie`).
    -   Category path/breadcrumb (from `ancestors`).
    -   Data Sources (`surseDeDate`).
    -   Detailed list of all dimensions (`dimensionsMap`).
    -   Methodology, observations, and any other relevant notes.
    -   A direct link to download the corresponding `.csv` file from `data/datasets/`.
    -   Data preview - first 20 rows of the table

## 4. Phase 2: Future Enhancements

-   **Advanced Filtering:** Implement filtering based on specific metadata fields like periodicity, keywords, or dimensions.
-   **Data Preview:** In the modal, show a preview of the first few rows of the actual CSV data.
-   **Simple Visualization:** For selected datasets, generate basic charts (e.g., bar, line) to visualize the data directly in the interface.
-   **Bookmark/Favorites:** Allow users to mark datasets as favorites for quick access.

