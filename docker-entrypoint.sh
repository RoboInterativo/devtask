#!/bin/sh
# ждём, пока БД начнёт принимать TCP-соединения
until nc -z db 5432; do
  echo "waiting for db..."
  sleep 1
done
python manage.py migrate
python manage.py collectstatic --noinput
uwsgi --ini uwsgi.ini
