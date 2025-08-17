#!/usr/bin/env bash
set -euo pipefail
DOMAIN=dxstrat.com
apt-get update && apt-get install -y nginx certbot python3-certbot-nginx
cat >/etc/nginx/sites-available/darwinxpool.conf <<NGX
server {
 listen 80;
 server_name ${DOMAIN};
 location / { proxy_pass http://127.0.0.1:8080/; proxy_set_header Host $host; proxy_set_header X-Real-IP $remote_addr; proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for; proxy_set_header X-Forwarded-Proto $scheme; }
}
NGX
ln -sf /etc/nginx/sites-available/darwinxpool.conf /etc/nginx/sites-enabled/darwinxpool.conf
nginx -t && systemctl reload nginx
certbot --nginx -d ${DOMAIN} --non-interactive --agree-tos -m admin@${DOMAIN} || true
