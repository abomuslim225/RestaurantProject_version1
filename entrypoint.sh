#!/bin/sh
set -e
echo "Postgres kutilmoqda..."
until python -c "
import socket, os, sys
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.settimeout(1)
try:
    s.connect((os.getenv('DB_HOST', 'db'), int(os.getenv('DB_PORT', 5432))))
    s.close()
except Exception:
    sys.exit(1)
"; do
  sleep 1
done
echo "Postgres tayyor."

if [ "$RUN_MIGRATIONS" = "true" ]; then
  echo "Migratsiya va statik fayllar yig'ilmoqda..."
  python manage.py migrate --noinput
  python manage.py collectstatic --noinput
fi

exec "$@"