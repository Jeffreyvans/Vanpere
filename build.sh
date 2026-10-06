#!/usr/bin/env bash
set -o errexit
pip install -r requirements.txt
python manage.py collectstatic --noinput
python manage.py migrate --noinput
python manage.py createcachetable
# Creates the built-in administrator from ADMIN_EMAIL/ADMIN_PASSWORD (idempotent; never prints the password).
python manage.py create_admin
