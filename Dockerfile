# A checkout that runs, not an installed package -- the same shape as every
# other way of running this, so the docs do not have to fork.
FROM python:3.13-slim

# Pillow ships manylinux wheels for every architecture this is likely to run
# on, so there is no compiler here and the image stays small.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    GLANCE_CONFIG=/config/settings.yaml \
    GLANCE_DATA_DIR=/data \
    GLANCE_STATIC_DIR=/config/static

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY glance/ ./glance/
COPY tools/ ./tools/
COPY config/ /defaults/config/
COPY assets/ /defaults/assets/
COPY docker-entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# /config is yours and is meant to be a volume; /data holds the caches and the
# rotation state. Both are seeded on first run from /defaults, so `docker run`
# with an empty directory gives you something that starts.
VOLUME ["/config", "/data"]
EXPOSE 8080

HEALTHCHECK --interval=60s --timeout=5s --start-period=10s \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=4).status==200 else 1)"

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["python", "-m", "uvicorn", "glance.server:app", "--host", "0.0.0.0", "--port", "8080"]
