#!/usr/bin/env bash
# Bootstrap a Debian 12 Proxmox LXC for myvitals.
# Run on the CT itself (not the host) as root.

set -euo pipefail

apt-get update
apt-get install -y --no-install-recommends \
    ca-certificates curl git gnupg lsb-release

# Docker (official repo)
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/debian/gpg \
    | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
https://download.docker.com/linux/debian $(lsb_release -cs) stable" \
    > /etc/apt/sources.list.d/docker.list
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Inside an unprivileged Proxmox LXC, runc 1.2+ (bundled with containerd.io)
# crashes on container start with "open sysctl net.ipv4.ip_unprivileged_port_start
# ... permission denied". Swap in Debian's runc 1.1.x, which doesn't try to
# write that sysctl.
if grep -qa container=lxc /proc/1/environ 2>/dev/null; then
    echo ">>> unprivileged LXC detected — swapping runc to Debian's 1.1.x"
    apt-get install -y runc
    cp /usr/sbin/runc /root/runc-debian
    apt-get install -y --reinstall containerd.io
    systemctl stop docker
    cp /root/runc-debian /usr/bin/runc
    systemctl start docker
fi

# App
mkdir -p /opt
cd /opt
if [ ! -d myvitals ]; then
    git clone https://github.com/Pr0zak/myvitals.git
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
