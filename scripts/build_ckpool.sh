#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
sudo apt-get update -y
sudo apt-get install -y build-essential autoconf automake libtool pkg-config \
  libevent-dev libjansson-dev libcurl4-openssl-dev libssl-dev jq

cd third_party/ckpool
[ -x configure ] || ./autogen.sh
./configure --without-ckdb
make -j"$(nproc)"
echo "ckpool built: $(pwd)/src/ckpool"
