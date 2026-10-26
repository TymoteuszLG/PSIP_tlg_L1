FROM python:3.11-slim-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends gdal-bin \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir \
    "h3>=4,<5" \
    "shapely>=2,<3" \
    "pyproj>=3,<4" \
    "pyshp>=2,<3" \
    "psycopg[binary]>=3,<4"

WORKDIR /app
COPY app /app
COPY data /data