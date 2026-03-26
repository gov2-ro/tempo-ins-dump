# Deployment Preparation Plan

## Context

The FastAPI + DuckDB app currently runs only locally (`uvicorn app.main:app`). No deployment artifacts exist — no Dockerfile, no requirements.txt, no env var support. This plan prepares the app for hosting on **Fly.io**, **Hugging Face Spaces**, and **Oracle Cloud free tier** with minimal code changes.

**Total deploy data: ~375 MB** (213 MB parquet-v3, 135 MB DuckDB, 19 MB view-profiles, 8 MB v2-only parquet)

---

## Phase 1: Common Base (all platforms)

### 1.1 Create `requirements.txt`

```
fastapi==0.133.1
uvicorn[standard]==0.30.6
duckdb==1.4.2
pydantic==2.8.2
```

Use Python 3.12 (not 3.14 — DuckDB lacks Linux/ARM wheels for 3.14).

### 1.2 Externalize config — `app/config.py`

Add `os.environ.get()` with current values as defaults. Only one new env var matters: `TEMPO_DATA_DIR`.

```python
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = Path(os.environ.get("TEMPO_DATA_DIR", str(PROJECT_ROOT / "data")))
DB_PATH = DATA_DIR / "tempo_metadata.duckdb"
PARQUET_DIR = DATA_DIR / "parquet-v3" / "ro"
PARQUET_V2_DIR = DATA_DIR / "parquet-v2" / "ro"

DEFAULT_PAGE_SIZE = 50
MAX_DATA_ROWS = int(os.environ.get("TEMPO_MAX_ROWS", "50000"))
LARGE_DATASET_THRESHOLD = 50_000
DEBUG = os.environ.get("TEMPO_DEBUG", "false").lower() in ("1", "true", "yes")
```

Local dev works unchanged (defaults to `PROJECT_ROOT/data`).

### 1.3 Fix view-profiles path — `app/main.py` (line 25)

```python
from app.config import DATA_DIR
# ...
view_profiles_dir = DATA_DIR / "view-profiles"
```

### 1.4 DuckDB memory limit — `app/db.py` (line 16)

Add memory limit for constrained platforms:

```python
_conn = duckdb.connect(str(DB_PATH), read_only=True, config={"memory_limit": "200MB"})
```

### 1.5 Create `Dockerfile`

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app/ app/
COPY deploy-data/ data/
EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
```

### 1.6 Create `.dockerignore`

Exclude `data/`, `docs/`, `ui/`, `profiling/`, `.git/`, `__pycache__/`, etc.

### 1.7 Create `scripts/prepare-deploy-data.sh`

Stages deployment data into `deploy-data/`:
- Copy `data/parquet-v3/ro/`
- Copy 368 v2-only parquet files into `parquet-v3/ro/` (merge, so we ship one dir)
- Copy `data/tempo_metadata.duckdb`
- Copy `data/view-profiles/`
- Create `deploy-data.tar.gz` (~200 MB compressed)

### 1.8 Create GitHub Release

Upload `deploy-data.tar.gz` as a release artifact — single source of truth for all platforms.

---

## Phase 2: Platform-Specific Configs

### 2.1 Fly.io — `fly.toml`

```toml
app = "tempo-ins-explorer"
primary_region = "ams"

[http_service]
  internal_port = 8080
  force_https = true

[env]
  TEMPO_DATA_DIR = "/app/data"

[[vm]]
  size = "shared-cpu-1x"
  memory = "512mb"
```

**Deploy**: `fly launch && fly deploy` (data baked into image).
**Alternative**: Fly Volume for data — faster redeploys when only code changes.

### 2.2 Hugging Face Spaces — `deploy/hf-spaces/`

HF-specific Dockerfile (port 7860, non-root user, data downloaded from GitHub Release):

```dockerfile
FROM python:3.12-slim
WORKDIR /app
RUN useradd -m -u 1000 user
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app/ app/
# Download data from GitHub Release during build
ARG DATA_URL
RUN apt-get update && apt-get install -y curl && \
    curl -L ${DATA_URL} -o /tmp/data.tar.gz && \
    tar xzf /tmp/data.tar.gz -C /app/ && rm /tmp/data.tar.gz
USER user
EXPOSE 7860
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7860"]
```

Plus `README.md` with HF Spaces YAML header (`sdk: docker`, `app_port: 7860`).

### 2.3 Oracle Cloud — `deploy/oracle/`

Full VM approach (no Docker needed, more RAM available):

- **`tempo-explorer.service`** — systemd unit running uvicorn with `--workers 2`
- **`nginx-tempo.conf`** — reverse proxy + HTTPS (Let's Encrypt)
- **`deploy.sh`** — rsync code + data, setup venv, enable service

Data uploaded via `scp deploy-data.tar.gz` or direct rsync.

---

## Summary: Common vs Platform-Specific

| Artifact | Common | Fly.io | HF Spaces | Oracle |
|---|---|---|---|---|
| `requirements.txt` | x | | | |
| `app/config.py` changes | x | | | |
| `app/main.py` changes | x | | | |
| `app/db.py` changes | x | | | |
| `Dockerfile` | x | | port 7860, data download | optional |
| `.dockerignore` | x | | | |
| `scripts/prepare-deploy-data.sh` | x | | | |
| `fly.toml` | | x | | |
| HF `README.md` + Dockerfile | | | x | |
| systemd + nginx configs | | | | x |

---

## Files Modified

| File | Change |
|---|---|
| `app/config.py` | Add `os.environ.get()` for DATA_DIR, MAX_ROWS, DEBUG (~5 lines) |
| `app/main.py` | Import DATA_DIR, use for view-profiles path (1 line) |
| `app/db.py` | Add `memory_limit` config (1 line) |

## Files Created

| File | Purpose |
|---|---|
| `requirements.txt` | Python deps |
| `Dockerfile` | Common container build |
| `.dockerignore` | Build exclusions |
| `scripts/prepare-deploy-data.sh` | Data staging + tarball |
| `fly.toml` | Fly.io config |
| `deploy/hf-spaces/Dockerfile` | HF-specific (port 7860, data download) |
| `deploy/hf-spaces/README.md` | HF Spaces metadata |
| `deploy/oracle/tempo-explorer.service` | systemd unit |
| `deploy/oracle/nginx-tempo.conf` | Reverse proxy |
| `deploy/oracle/deploy.sh` | Upload + setup script |

## Verification

1. **Local Docker test**: `docker build -t tempo . && docker run -p 8080:8080 tempo`
2. Verify: landing page loads, dataset list works, choropleth renders, view-profiles load
3. Check DuckDB memory stays within limits: `curl localhost:8080/api/datasets`
