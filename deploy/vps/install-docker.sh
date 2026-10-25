#!/usr/bin/env bash
# Install Docker Engine + Compose plugin from the official Docker apt repository
# (Ubuntu 22.04/24.04, Debian 12) and open SSH/HTTP/HTTPS in ufw. Run as root.
set -euo pipefail

if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  echo "Docker and Compose are already installed:"; docker --version; docker compose version
  exit 0
fi

. /etc/os-release
case "$ID" in ubuntu|debian) ;; *) echo "Unsupported OS: $ID (use Ubuntu or Debian)"; exit 1 ;; esac

apt-get update
apt-get install -y ca-certificates curl gnupg unzip openssl
install -m 0755 -d /etc/apt/keyrings
curl -fsSL "https://download.docker.com/linux/$ID/gpg" -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/$ID ${VERSION_CODENAME} stable" \
  > /etc/apt/sources.list.d/docker.list
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
systemctl enable --now docker

if command -v ufw >/dev/null 2>&1; then
  ufw allow OpenSSH
  ufw allow 80/tcp
  ufw allow 443/tcp
  ufw --force enable
fi

docker --version
docker compose version
