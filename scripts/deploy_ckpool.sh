#!/usr/bin/env bash
set -euo pipefail
ROOT=/opt/darwinx
install -d "$ROOT/logs" "$ROOT/runtime" "$ROOT/config"
source "$ROOT/config/.env"

# Render ckpool.conf from template
sed -e "s/RPC_USER_FROM_ENV/${RPC_USER}/" \
    -e "s/RPC_PASSWORD_FROM_ENV/${RPC_PASSWORD}/" \
    -e "s/HOT_POOL_ADDRESS_FROM_ENV/${HOT_POOL_ADDRESS}/" \
    -e "s#CKPOOL_BIND_FROM_ENV#${CKPOOL_BIND}#" \
    -e "s#CKPOOL_PORT_FROM_ENV#${CKPOOL_PORT}#" \
    "$ROOT/config/ckpool.conf" > "$ROOT/runtime/ckpool.conf"

echo "ckpool.conf -> $ROOT/runtime/ckpool.conf"
