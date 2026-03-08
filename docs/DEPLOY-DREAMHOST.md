# Deploy to Dreamhost (shared hosting, subdomain)

## Architecture

- **App URL**: `tempo.yourdomain.com` (Passenger WSGI subdomain)
- **Data path on server**: `~/yourdomain.com/tempo-data/` (separate from app code)
- **App code path**: `~/tempo.yourdomain.com/`

---

## Step 1 — Dreamhost panel

1. Go to **Domains → Manage Domains → Add New Domain**
2. Create subdomain: `tempo.yourdomain.com`
3. Check **"Run this domain on Passenger (for web applications)"**
4. Set web directory to `/home/USERNAME/tempo.yourdomain.com`
5. Save

---

## Step 2 — Create files locally

### `requirements.txt`
```
flask
duckdb
pyarrow
pandas
```

### `passenger_wsgi.py`
```python
import sys, os
from pathlib import Path

# Force Passenger to use virtualenv Python 3
INTERP = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'venv', 'bin', 'python3')
if sys.executable != INTERP:
    os.execl(INTERP, INTERP, *sys.argv)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Override data paths via env var (set in .htaccess)
import duckdb_config
data_override = os.environ.get('TEMPO_DATA_DIR')
if data_override:
    duckdb_config.DATA_DIR = Path(data_override)
    duckdb_config.DB_FILE = duckdb_config.DATA_DIR / 'tempo_metadata.duckdb'
    duckdb_config.PARQUET_DIR = duckdb_config.DATA_DIR / 'parquet' / 'ro'

from duckdb_browser import app as application
```

### `.htaccess`
```apache
PassengerEnabled On
PassengerAppRoot /home/USERNAME/tempo.yourdomain.com

SetEnv TEMPO_DATA_DIR /home/USERNAME/yourdomain.com/tempo-data
```
Replace `USERNAME` and domain names.

---

## Step 3 — Upload app code

```bash
rsync -av \
  duckdb-browser.py \
  duckdb_config.py \
  passenger_wsgi.py \
  requirements.txt \
  .htaccess \
  USERNAME@yourdomain.com:~/tempo.yourdomain.com/
```

---

## Step 4 — SSH: set up virtualenv

```bash
ssh USERNAME@yourdomain.com
cd ~/tempo.yourdomain.com
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
mkdir -p tmp
```

---

## Step 5 — Upload data (only what the app needs, ~200 MB)

**Skip the large raw CSVs** — only upload:
- `data/tempo_metadata.duckdb` (69 MB)
- `data/parquet/ro/` (133 MB — 1,886 parquet files)

```bash
# From your local machine:
ssh USERNAME@yourdomain.com "mkdir -p ~/yourdomain.com/tempo-data/parquet/ro"

rsync -av --progress \
  data/tempo_metadata.duckdb \
  USERNAME@yourdomain.com:~/yourdomain.com/tempo-data/

rsync -av --progress \
  data/parquet/ro/ \
  USERNAME@yourdomain.com:~/yourdomain.com/tempo-data/parquet/ro/
```

Do **not** upload: `4-datasets/` (5 GB), `5-compact-datasets/` (3.6 GB), `6-sdmx-csv/` (2.4 GB), `2-metas/` (35 MB).

---

## Step 6 — Test & restart

```bash
# SSH: quick sanity check
cd ~/tempo.yourdomain.com
source venv/bin/activate
python -c "from passenger_wsgi import application; print('OK')"

# Restart Passenger
touch tmp/restart.txt
```

Then visit `https://tempo.yourdomain.com` — should show the landing page.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| 500 error on load | Check `~/logs/tempo.yourdomain.com/http/error.log` |
| "No module named flask" | Virtualenv path wrong in `passenger_wsgi.py` — verify `venv/bin/python3` exists |
| Data not found | Check `TEMPO_DATA_DIR` env var — verify `.htaccess` SetEnv and path |
| Stale after code change | `touch ~/tempo.yourdomain.com/tmp/restart.txt` |
| Slow first request | Normal — Passenger cold-starts after idle periods |
