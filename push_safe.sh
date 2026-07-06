#!/usr/bin/env bash
set -e

msg="${1:-Mise a jour SENDlocal}"

git add .gitignore mxsend.py sendSPeed.py email1 message.txt dkim_mail_authentifications_app_public.txt push_safe.sh
git commit -m "$msg"
git push -u origin main
