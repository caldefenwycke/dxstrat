#!/usr/bin/env bash
set -euo pipefail
apt-get update
apt-get install -y python3.12 python3.12-venv python3-pip nginx jq
id -u darwinx &>/dev/null || adduser --system --group --home /opt/darwinx darwinx
chown -R darwinx:darwinx /opt/darwinx
sudo -u darwinx bash -lc 'cd /opt/darwinx && python3.12 -m venv venv && source venv/bin/activate && pip install -U pip && pip install -r requirements.txt'
python db/migrate.py
cp systemd/darwinx-stratum.service /etc/systemd/system/
cp systemd/darwinxpool-api.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable darwinx-stratum darwinxpool-api
systemctl start darwinx-stratum darwinxpool-api
