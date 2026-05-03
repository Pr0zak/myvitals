#!/usr/bin/env bash
# Bootstrap a Debian 12 Proxmox LXC for myvitals.
# Run on the CT itself (not the host) as root.

set -euo pipefail

apt-get update
apt-get install -y --no-install-recommends \
    ca-certificates curl git gnupg lsb-release

# Docker
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/debian/gpg \
    | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
https://download.docker.com/linux/debian $(lsb_release -cs) stable" \
    > /etc/apt/sources.list.d/docker.list
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# App
mkdir -p /opt
cd /opt
if [ ! -d myvitals ]; then
    git clone https://github.com/CHANGE_ME/myvitals.git
fi
cd myvitals

if [ ! -f .env ]; then
    cp .env.example .env
    echo ">>> Edit /opt/myvitals/.env (set INGEST_TOKEN, QUERY_TOKEN, POSTGRES_PASSWORD)"
    echo ">>> Then run: docker compose up -d --build"
    exit 0
fi

docker compose up -d --build
echo ">>> myvitals is up at http://$(hostname -I | awk '{print $1}'):8080"
