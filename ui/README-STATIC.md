# INS Data Explorer - Static Version

This directory contains both the original Flask-based server version and the new static version of the INS Data Explorer.

## 🚀 Quick Start - Static Version (Recommended)

### 1. Build the static data files
```bash
# From the project root
python build-static-index.py
```

### 2. Serve the static site
```bash
# From the ui/ directory
cd ui
python3 -m http.server 8080
```

### 3. Open in browser
Visit: http://localhost:8080/index-static.html

## 📁 Files Overview

### Static Version
- **`index-static.html`** - Main static HTML page
- **`explorer-static.js`** - Client-side JavaScript (no server required)
- **`csv-parser.js`** - Lightweight CSV parser for browser
- **`data/`** - Generated static data files
  - `datasets-index.json` - Master dataset index
  - `flags-index.json` - Flag counts
  - `datasets/` - Individual dataset JSON files (symlinked)
  - `csv/` - CSV files for preview (symlinked)

### Original Server Version
- **`server.py`** - Flask server
- **`explorer.html`** - Server-dependent HTML
- **`explorer.js`** - Client-side JS that calls server APIs

### Shared Files
- **`explorer.css`** - Shared CSS styles
- **`build-static-index.py`** - Build script (in project root)

## ⚡ Benefits of Static Version

- **No server dependency** - Works on any web host
- **Faster loading** - All data loaded once, then filtered client-side
- **Better caching** - Static files cache well
- **Easier deployment** - Just copy files
- **Works offline** - Once loaded, works without internet

## 🔧 How It Works

1. **Build Process**: `build-static-index.py` scans all dataset JSON files and creates:
   - A master index with metadata for all datasets
   - Flag counts for the sidebar
   - Symlinks to dataset and CSV files

2. **Client-Side Loading**: 
   - Loads the master index once on page load
   - Filters and searches happen entirely in JavaScript
   - CSV previews loaded on-demand via fetch()
   - Lightweight CSV parser handles large files

3. **Caching**: 
   - Dataset details cached after first load
   - CSV previews cached to avoid re-parsing
   - Browser caching for static files

## 🛠 Development

### To update the static data:
```bash
# Rebuild the indexes
python build-static-index.py

# Restart your web server
```

### To modify the UI:
- Edit `explorer-static.js` for client-side logic
- Edit `index-static.html` for HTML structure
- Edit `explorer.css` for styling (shared with server version)

## 📊 Performance

- **Initial load**: ~75KB for dataset index + flags
- **Memory usage**: Efficient client-side filtering
- **Preview loading**: Only loads requested CSV data
- **File size handling**: Automatically truncates large files (>4MB) to 400 rows

## 🔄 Migration from Server Version

The static version maintains 100% feature parity with the server version:

- ✅ Dataset listing with search and flag filtering
- ✅ Dataset detail view with navigation
- ✅ CSV preview with DataTables integration
- ✅ Intelligent data summary widget
- ✅ URL permalinks and browser navigation
- ✅ Validation flags and data quality indicators

## 🎯 Usage Examples

### Local Development
```bash
cd ui
python3 -m http.server 8080
# Visit http://localhost:8080/index-static.html
```

### Web Server Deployment
```bash
# Copy ui/ directory to your web server
rsync -av ui/ user@server:/var/www/html/explorer/
# Visit https://yourserver.com/explorer/index-static.html
```

### GitHub Pages / Netlify
```bash
# The ui/ directory can be deployed directly to any static host
# Just ensure the data/ directory is included
```
