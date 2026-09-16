#!/bin/sh
# Seed an empty /config on first run, so `docker run` against a fresh
# directory starts rather than erroring on a missing settings.yaml.
set -e

if [ ! -f /config/settings.yaml ]; then
    echo "glance: /config is empty, seeding defaults"
    cp -rn /defaults/config/. /config/ 2>/dev/null || true
fi

# Artwork lives with the config, so it survives an image upgrade.
if [ ! -d /config/static ]; then
    mkdir -p /config/static
    cp -rn /defaults/assets/static/. /config/static/ 2>/dev/null || true
fi

mkdir -p /data/cache
exec "$@"
