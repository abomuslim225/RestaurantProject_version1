FROM python:3.12-slim-bookworm AS base

# Xavfsizlik va logging uchun
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Build va runtime uchun kerakli tizim kutubxonalari
# libpq-dev - psycopg2 uchun, libjpeg/zlib - Pillow uchun, build-essential - cryptography uchun
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    libjpeg-dev \
    zlib1g-dev \
    libwebp-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip \
    && pip install -r requirements.txt

COPY . .

RUN chmod +x entrypoint.sh

# Statik va media fayllar uchun papkalar (volume orqali ham mount qilinadi)
RUN mkdir -p /app/static /app/media

ENTRYPOINT ["./entrypoint.sh"]
CMD ["daphne", "-b", "0.0.0.0", "-p", "8000", "root.asgi:application"]