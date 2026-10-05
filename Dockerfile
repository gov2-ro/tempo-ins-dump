FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# DuckDB FTS extension for the pinned duckdb version, baked in at build time so
# `LOAD fts` never needs a network download at runtime (Fly machines may cold-start offline).
RUN python -c "import duckdb; c = duckdb.connect(); c.execute('INSTALL fts'); c.execute('LOAD fts'); print('fts', duckdb.__version__)"

COPY app/ app/
COPY llms.txt .

# Data is staged by scripts/prepare-deploy-data.sh (must run BEFORE the image build;
# fly release_command cannot repair stale data already copied into the image).
COPY deploy-data/ data/

# Fail the build if the staged data is incomplete or the index can't be opened.
RUN test -f data/MANIFEST.json && test -f data/corpus/search.duckdb && test -f data/corpus/metadata.duckdb \
 && python -c "import duckdb; c = duckdb.connect('data/corpus/search.duckdb', read_only=True); c.execute('LOAD fts'); print('search_docs', c.execute('select count(*) from search_docs').fetchone()[0])"

EXPOSE 8080

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
