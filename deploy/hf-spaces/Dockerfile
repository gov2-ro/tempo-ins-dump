FROM python:3.12-slim

WORKDIR /app

RUN useradd -m -u 1000 user

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ app/

# Download data from GitHub Release during build
ARG DATA_URL
RUN apt-get update && apt-get install -y --no-install-recommends curl && \
    curl -L ${DATA_URL} -o /tmp/data.tar.gz && \
    mkdir -p /app/data && \
    tar xzf /tmp/data.tar.gz -C /app/data && \
    rm /tmp/data.tar.gz && \
    apt-get remove -y curl && apt-get autoremove -y && \
    rm -rf /var/lib/apt/lists/*

ENV TEMPO_DATA_DIR=/app/data

USER user

EXPOSE 7860

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7860", "--workers", "1"]
