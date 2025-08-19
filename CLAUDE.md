# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview
This is a Romanian National Institute of Statistics (INS) data scraper and explorer tool that fetches, processes, and visualizes statistical data from the TEMPO Online database. The project has two main components: a data pipeline for fetching/processing data, and a web-based UI for exploring datasets.

## Architecture

### Data Pipeline (Python Scripts)
Sequential numbered scripts process data through multiple stages:
1. `1-fetch-context.py` - Fetches contexts → `data/1-indexes/ro/context.csv`
2. `2-fetch-matrices.py` - Fetches datasets → `data/1-indexes/ro/matrices.csv`
3. `3-fetch-metas.py` - Fetches metadata → `data/2-metas/ro/{dataset-id}.json`
4. `4-build-meta-index.py` - Builds meta index
5. `5-varstats-db.py` - Creates SQLite database from metadata
6. `6-fetch-csv.py` - Downloads CSV data → `data/4-datasets/ro/{dataset-id}.csv`
7. `7-data-compactor.py` - Compacts CSV dimensions

### UI Components (ui/ folder)
Multi-interface web application with several explorers:

#### Main Dataset Navigator
- `index.html` + `script.js` + `style.css` - Primary interface for browsing datasets
- Two-pane layout: category tree navigation + dataset cards
- Modal view for detailed dataset information

#### Dimension Index Explorer 
- `dimensions.html` + `dimensions-script.js` + `dimensions-style.css` - Specialized dimension search
- Client-side JSON approach for exploring statistical dimensions and options

#### PHP API Version
- `dimensions-api.html` + `dimensions-script-api.js` - Server-side API version  
- `api.php` + `config.php` - RESTful PHP API with SQLite backend
- Handles 300K+ records with caching, rate limiting, security features

#### Data Profiler Explorer
- `explorer.html` + `explorer.js` + `explorer.css` - Data validation and profiling interface
- `server.py` - Flask backend serving profiling results and dataset previews

## Development Commands

### Python Environment
Always activate: `source ~/devbox/envs/240826/bin/activate`

### Data Pipeline
```bash
# Run initial analysis
python build-dimension-index.py

# Search for specific terms
python build-dimension-index.py search "Perioade"
python build-dimension-index.py search "Bucuresti"

# Query helper for advanced searches
python query-dimensions.py summary      # File overview
python query-dimensions.py usage        # Dimension usage stats
python query-dimensions.py search "grade" # Search options
python query-dimensions.py file ZDP1321   # File details
```

### UI Development

#### Main Navigator
```bash
# Serve static files
python -m http.server 8000
# Open: http://localhost:8000/ui/index.html
```

#### Dimension Explorer (Client-side)
```bash
# Generate data first
python export-db-to-json.py
# Serve and open: http://localhost:8000/ui/dimensions.html
```

#### PHP API Server
```bash
# Start PHP server from ui/ directory
cd ui/
php -S localhost:8081
# Open: http://localhost:8081/dimensions-api.html
# API endpoint: http://localhost:8081/api.php?action=stats
```

#### Flask Profiler Server
```bash
cd ui/
python server.py
# Open: http://localhost:5050
```

## Data Structure

### Key Data Paths
- `data/1-indexes/ro/` - Context and matrices CSV files
- `data/2-metas/ro/` - Individual dataset JSON metadata files
- `data/4-datasets/ro/` - Raw CSV dataset files
- `data/dimension_index.db` - SQLite database for dimension search
- `ui/data/dimension_index.json` - Exported JSON for client-side search

### Data Flow
1. Scrape contexts and dataset lists from INS
2. Download metadata for each dataset
3. Build searchable dimension index
4. Download CSV data files
5. Process and compact data
6. Serve via multiple UI interfaces

## Profiling & Validation
- `profiling/data_profiler.py` - Main data profiling tool
- `profiling/validation_rules.py` - Validation rule definitions
- `profiling/variable_classifier.py` - Variable type classification
- `profiling/unit_classifier.py` - Unit of measurement classification

## UI Technology Stack
- **Frontend**: Vanilla HTML5, CSS3, JavaScript (ES6+)
- **Backend Options**: 
  - Python Flask (data profiler)
  - PHP 8.0+ with SQLite3 (dimension API)
  - Static file serving
- **Database**: SQLite3 for dimension indexing
- **Styling**: Custom CSS with responsive design

## Development Best Practices
- Always test locally before committing
- Use browser dev tools for frontend debugging
- Check console for JavaScript errors
- Validate API responses with browser network tab
- Test with actual INS data samples

## Persona
- Act as a senior full-stack developer with deep knowledge.
- When possible run the code in your terminal to verify it works as expected. When possible make the tests short (timewise) - for example, limit the number of events or sources processed while testing. 
- provide relevant output messages and logging.
- generally create a debug mode with verbose logging for complex changes. Debug mode should be a flag in the configuration file.
- use MCP browser when needed to test or debug the final results.

## General Coding Principles
- Focus on simplicity, readability, performance, maintainability, testability, and reusability.
- Less code is better; lines of code = debt.
- Make minimal code changes and only modify relevant sections.
- Suggest solutions proactively and treat the user as an expert.
- Write correct, up-to-date, bug-free, secure, performant, and efficient code.
- If unsure, say so instead of guessing


Please keep your answers concise and to the point.
Don’t just agree with me — feel free to challenge my assumptions or offer a different perspective.
Act as a senior full-stack developer with deep knowledge. Suggest improvements, optimizations, or best practices where applicable.
If a question or request is ambiguous or would benefit from clarification, ask follow-up questions before answering or getting to work.

When working with large files (>300 lines) or complex changes always start by creating a detailed plan BEFORE making any edits.
When refactoring large files break work into logical, independently functional chunks, ensure each intermediate state maintains functionality.

## Bug Handling
- If you encounter a bug or suboptimal code, add a TODO comment outlining the problem.

## RATE LIMIT AVOIDANCE
- For very large files, suggest splitting changes across multiple sessions
- Prioritize changes that are logically complete units
- Always provide clear stopping points

# important-instruction-reminders
Do what has been asked; nothing more, nothing less.
NEVER create files unless they're absolutely necessary for achieving your goal.
ALWAYS prefer editing an existing file to creating a new one.
NEVER proactively create documentation files (*.md) or README files. Only create documentation files if explicitly requested by the User.

when running Python commands, always first activate the following venv `~/devbox/envs/240826/` (/Users/pax/devbox/envs/240826/bin/activate)